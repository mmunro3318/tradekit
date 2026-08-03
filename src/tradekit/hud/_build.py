"""Funnel walk -> grade rule -> ticket assembly (SPEC-hud-orderbook T3).

`evaluate_policy` and `open_position_symbols` are the two SANCTIONED
module-level test seams pinned by ASSUMPTIONS 157(a) (alongside
`mae._runtime.clock`/`get_closed_bars`) — their defaults are the real
policy evaluation and real open-position query; nothing else in this
module is a monkeypatch point.

Grade rule (DESIGN §Grade rule / SPEC AC-5..7): position open with no exit
signal -> "hold" (checked first — position safety trumps a data gap, SPEC
§Unknowns register); insufficient closed bars -> "wait" + failed
`data_integrity` gate; policy refusal -> "wait" + failed `policy_verdict`
gate, no ticket; every gate passing AND policy allowing -> "buy"/"sell" +
one `AdvisoryTicket`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal
from typing import Any

import tradekit.mae._runtime as mae_runtime
from tradekit.contracts import AdvisoryTicket, GateResult, HudState, ScanReportEntry
from tradekit.contracts._marketdata import BarSeries
from tradekit.mae._data.errors import ProviderError
from tradekit.mae._scan_trace import ScanAuditMode

_TIMEFRAME = "1h"
_LOOKBACK_DAYS = 30
_MIN_BARS = 20
_FEE_RATE = Decimal("0.0004")  # 4 bps/side (ASSUMPTIONS 144)
# T-MTF-4 (docs/design/MTF-SCAN.md "Strategy registry" section): the old
# hardcoded S1 battery (`_SETUP_FILTERS`/`_SETUP_TIMEFRAME`, macd_signal +
# volume_spike @ 4h) is now `mae.STRATEGIES[0]` (`s1_momentum`) — see
# `_default_scan_setup` below, which walks the registry instead.


@dataclass(frozen=True)
class _PolicyDecision:
    allowed: bool
    verdict_id: str | None
    rationale: str


@dataclass(frozen=True)
class SizingInfo:
    """Real min-ATR/quarter-Kelly sizing result plus the ATR-bracket
    inputs derived from the same `mae.size_position` call (ASSUMPTIONS
    159a: one call powers both quantity and the bracket)."""

    qty: Decimal
    stop_distance_usd: Decimal
    r_multiple_target: Decimal


@dataclass(frozen=True)
class _SetupResult:
    signal_tags: list[str]
    attrition_stages: list[dict[str, str]] = field(default_factory=list)
    """A-FIX-1: the scanner's own P3 `stages` trail for this (symbol,
    setup timeframe) — defaulted so pre-existing monkeypatched test
    doubles (plain `signal_tags`-only objects) keep working. Empty means
    "the scanner reported none" (attrition_stages absent from the seam
    caller), in which case `_attrition_entry` falls back to the collapsed
    hud-level "setup" gate name."""
    strategy_key: str = ""
    """T-MTF-4: the `StrategyDef.key` that claimed this symbol in the
    `mae.STRATEGIES` walk (empty string when none armed — falsy sentinel,
    ASSUMPTIONS escape hatch 2)."""


def _round2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _default_evaluate_policy(proposal: object) -> _PolicyDecision:
    """Real policy evaluation via `tradekit.policy.evaluate` (ASSUMPTIONS
    157a default). `proposal` is the `ProposedAction` this module built."""
    from tradekit import policy as policy_mod

    verdict = policy_mod.evaluate(proposal)  # type: ignore[arg-type]
    if verdict.allow:
        return _PolicyDecision(allowed=True, verdict_id=verdict.verdict_id, rationale="allow")
    failing = [hit for hit in verdict.rule_hits if hit.outcome == "fail"]
    rationale = "; ".join(f"{hit.rule_id}: {hit.measured} vs {hit.limit}" for hit in failing)
    return _PolicyDecision(
        allowed=False, verdict_id=None, rationale=rationale or "policy denied action"
    )


def _default_open_position_symbols() -> set[str]:
    """Real open-position query via the ledger's public surface
    (ASSUMPTIONS 157a default): the symbol of every currently-active thesis,
    read off its own `ThesisDrafted` event (the `theses` projection carries
    no symbol column)."""
    from tradekit.contracts import EventFilter
    from tradekit.ledger import default_ledger

    ledger = default_ledger()
    active_ids = {thesis.thesis_id for thesis in ledger.models.active_theses()}
    if not active_ids:
        return set()
    symbols: set[str] = set()
    for event in ledger.query(EventFilter(types=["ThesisDrafted"])):
        thesis_id = event.payload.get("thesis_id")
        if thesis_id not in active_ids:
            continue
        contract = event.payload.get("contract") or {}
        asset = contract.get("asset") or {}
        symbol = asset.get("symbol")
        if symbol:
            symbols.add(symbol)
    return symbols


def _default_sizing_info(symbol: str, limit_price: Decimal, equity_usd: Decimal) -> SizingInfo:
    """Real min-ATR/quarter-Kelly sizing (ASSUMPTIONS 159a): one
    `mae.size_position` call powers both the quantity and the ATR-bracket
    inputs. Quantity is quantized to 8dp ROUND_DOWN — conservative, never
    oversize."""
    from tradekit import mae

    result = mae.size_position(symbol, account_equity_usd=equity_usd)
    qty = Decimal(str(result["recommended_units"])).quantize(
        Decimal("0.00000001"), rounding=ROUND_DOWN
    )
    return SizingInfo(
        qty=qty,
        stop_distance_usd=Decimal(str(result["stop_distance_usd"])),
        r_multiple_target=Decimal(str(result["r_multiple_target"])),
    )


def _default_scan_setup(symbol: str, *, audit: ScanAuditMode = "off") -> _SetupResult:
    """Real setup scan (T-MTF-4, docs/design/MTF-SCAN.md "Strategy
    registry" section): walks `mae.STRATEGIES` in priority order, arming
    the first def whose `regime_families` has a non-empty intersection
    with the symbol's regime-recommended families (ANY-semantics — CTO
    adjudication, this dispatch) AND whose `mae.scan_confluence` legs all
    pass with non-empty surviving tags on every leg (ASSUMPTIONS 173.4
    empty-tag guard — a `min_tags=0` leg's empty-tag "match" must not arm).
    First match wins; later defs (and their bar fetches) are never
    evaluated once a def claims the symbol. Empty `signal_tags` and a
    falsy `strategy_key` when nothing arms — the existing "wait" path.

    `audit` (T-AUDIT-2): `mae.scan_confluence` has no audit mode yet
    (T-AUDIT-2 predates T-MTF-4's registry walk) — an explicit audit
    request runs only the first (S1) def through the audited
    `mae.scan_markets` verb, same battery/behavior as before this batch,
    rather than silently dropping the request."""
    from tradekit import mae
    from tradekit.mae import _regime, _scanner

    if audit != "off":
        if not mae.STRATEGIES:
            # F4: an empty registry has no S1 to audit — the same
            # wait-shaped empty result the "nothing armed" error map
            # already returns below, not an IndexError on STRATEGIES[0].
            return _SetupResult(signal_tags=[], strategy_key="")
        s1 = mae.STRATEGIES[0]
        s1_leg = s1.legs[0]
        result = mae.scan_markets(
            "crypto",
            [s1_leg["timeframe"]],
            filters=s1_leg["filters"],
            symbols=[symbol],
            regime_gate=True,
            audit=audit,
        )
        stages: list[dict[str, str]] = []
        for entry in result.get("attrition", []):
            if entry.get("symbol") == symbol:
                stages = list(entry.get("stages", []))
                break
        for match in result["matches"]:
            if match.get("symbol") == symbol:
                return _SetupResult(
                    signal_tags=list(match.get("signal_tags", [])),
                    attrition_stages=stages,
                    strategy_key=s1.key,
                )
        return _SetupResult(signal_tags=[], attrition_stages=stages, strategy_key="")

    regime = _regime.compute_regime(
        symbol=symbol,
        lookback_days=_scanner._SCAN_REGIME_LOOKBACK_DAYS,
        n_states=_scanner._SCAN_REGIME_N_STATES,
    )
    recommended = set(regime.get("recommended_strategies") or [])

    # F2/ASSUMPTIONS 163b: per-def attrition trail for the whole walk, in
    # walk order, so `_attrition_entry` can name the real killer instead of
    # collapsing every setup kill into the uninformative "setup" gate.
    walk_stages: list[dict[str, str]] = []

    for strategy_def in mae.STRATEGIES:
        if not set(strategy_def.regime_families) & recommended:
            walk_stages.append(
                {
                    "name": f"{strategy_def.key} regime_prefilter",
                    "outcome": "fail",
                    "observed": (
                        f"regime_families={list(strategy_def.regime_families)} "
                        f"not in recommended={sorted(recommended)}"
                    ),
                }
            )
            continue
        # F1: this def's legs are contained to ProviderError only — that's
        # `compute_regime`'s OWN bar fetch inside `scan_confluence` (called
        # again there, per-leg, once a leg matches) escaping uncaught; the
        # fetch-site `ProviderError` `scan_confluence` catches for its own
        # leg bars does NOT cover that second, regime-side fetch. A
        # programming/config error (e.g. a typo'd def's vocabulary
        # `ValueError`) must escape LOUD instead of being silently skipped
        # here — `build_state`'s own `except Exception` at the caller
        # already degrades it to a visible failed setup gate naming the
        # exception (the anti-silent doctrine: a broken def must be seen,
        # not skipped).
        try:
            result = mae.scan_confluence(
                "crypto", list(strategy_def.legs), [symbol], regime_gate=True
            )
        except ProviderError:
            continue
        for warning in result["warnings"]:
            # The confluence warning strings already name the symbol/leg/
            # counts (leg failure or provider error caught inside
            # `scan_confluence` itself) — just tag them with the def key.
            walk_stages.append(
                {"name": f"{strategy_def.key} confluence", "outcome": "fail", "observed": warning}
            )
        for match in result["matches"]:
            if match.get("symbol") != symbol:
                continue
            legs_out = match["legs"]
            tags_per_leg = [leg["signal_tags"] for leg in legs_out.values()]
            if not tags_per_leg or any(not tags for tags in tags_per_leg):
                # empty-tag guard (ASSUMPTIONS 173.4): does not arm
                walk_stages.append(
                    {
                        "name": f"{strategy_def.key} empty_tag_guard",
                        "outcome": "fail",
                        "observed": "confluence matched with an empty-tag leg",
                    }
                )
                break
            signal_tags = [tag for tags in tags_per_leg for tag in tags]
            walk_stages.append(
                {
                    "name": f"{strategy_def.key} confluence",
                    "outcome": "pass",
                    "observed": f"signal_tags={signal_tags}",
                }
            )
            return _SetupResult(
                signal_tags=signal_tags,
                attrition_stages=walk_stages,
                strategy_key=strategy_def.key,
            )

    return _SetupResult(signal_tags=[], attrition_stages=walk_stages, strategy_key="")


# Test seams (ASSUMPTIONS 157a/158/159). Tests monkeypatch these module
# attributes directly; production code below calls them via this module's
# own namespace so the seam takes effect.
evaluate_policy = _default_evaluate_policy
open_position_symbols = _default_open_position_symbols
sizing_info = _default_sizing_info
scan_setup = _default_scan_setup


def _fetch_bars(symbol: str) -> tuple[BarSeries | None, str]:
    """`(None, reason)` signals "insufficient/gap" (AC-6): too few bars, or
    the provider raised — either way the symbol degrades to a visible failed
    `data_integrity` gate carrying the actual reason, never an escaping
    exception."""
    try:
        series = mae_runtime.get_closed_bars(symbol, _TIMEFRAME, _LOOKBACK_DAYS)
    except Exception as exc:
        return None, f"provider error: {type(exc).__name__}"
    if len(series.bars) < _MIN_BARS:
        return None, f"{len(series.bars)} closed bars"
    return series, ""


def _build_ticket_fields(
    symbol: str,
    limit_price: Decimal,
    quantity: Decimal,
    stop_distance_usd: Decimal,
    r_multiple_target: Decimal,
    side: str = "buy",
) -> dict[str, Decimal]:
    """ATR bracket (ASSUMPTIONS 159d): buy side SL = limit - stop_distance,
    TP = limit + r_multiple*stop_distance; sell side mirrors signs. Both
    quantized to the limit price's exponent ROUND_HALF_EVEN."""
    tp_offset = r_multiple_target * stop_distance_usd
    if side == "buy":
        tp_price = (limit_price + tp_offset).quantize(limit_price, rounding=ROUND_HALF_EVEN)
        sl_price = (limit_price - stop_distance_usd).quantize(limit_price, rounding=ROUND_HALF_EVEN)
    else:
        tp_price = (limit_price - tp_offset).quantize(limit_price, rounding=ROUND_HALF_EVEN)
        sl_price = (limit_price + stop_distance_usd).quantize(limit_price, rounding=ROUND_HALF_EVEN)

    fee_entry = _round2(limit_price * quantity * _FEE_RATE)
    fee_tp_exit = _round2(tp_price * quantity * _FEE_RATE)
    fee_sl_exit = _round2(sl_price * quantity * _FEE_RATE)

    est_pnl_tp = _round2(quantity * (tp_price - limit_price)) - (fee_entry + fee_tp_exit)
    est_pnl_sl = _round2(quantity * (sl_price - limit_price)) - (fee_entry + fee_sl_exit)

    tp_distance_pct = _round2(Decimal(100) * (tp_price - limit_price) / limit_price)
    sl_distance_pct = _round2(Decimal(100) * (sl_price - limit_price) / limit_price)

    return {
        "limit_price": limit_price,
        "quantity": quantity,
        "est_total_usd": _round2(limit_price * quantity),
        "tp_price": tp_price,
        "tp_distance_pct": tp_distance_pct,
        "sl_price": sl_price,
        "sl_distance_pct": sl_distance_pct,
        "est_pnl_tp_usd": est_pnl_tp,
        "est_pnl_sl_usd": est_pnl_sl,
        "est_fee_usd": fee_entry,
    }


def _make_proposal(symbol: str, thesis_id: str, fields: dict[str, Decimal]) -> object:
    from tradekit.contracts import AssetRef, OrderRequest, ProposedAction
    from tradekit.policy._dials import PolicyDials

    account_ref = PolicyDials.load().default_account_ref
    is_crypto = "/" in symbol
    asset = AssetRef(
        symbol=symbol,
        venue="kraken" if is_crypto else "alpaca",
        asset_class="crypto" if is_crypto else "equity",
        tick_size=Decimal("0.00001") if is_crypto else Decimal("0.01"),
    )
    order = OrderRequest(
        thesis_id=thesis_id,
        account_ref=account_ref,
        asset=asset,
        side="buy",
        order_type="limit",
        qty=fields["quantity"],
        limit_price=fields["limit_price"],
    )
    return ProposedAction(
        kind="submit_order",
        account_ref=account_ref,
        requested_by="hud",
        thesis_id=thesis_id,
        order=order,
    )


def _attrition_entry(
    symbol: str,
    timeframe: str,
    gates: tuple[GateResult, ...],
    setup_stages: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build a P4 attrition entry from the gates already assembled for this
    symbol's `ScanReportEntry` — same per-symbol shape as `_scanner.scan`'s
    P3 entries (`_build_ticket_fields` etc. never re-derive; this reuses the
    gate trail build_state already walked). `data_integrity` is renamed to
    `"bars"` to match the scanner's own stage vocabulary (P4: "same
    per-symbol shape ... plus hud's own two extra stage names").

    A-FIX-1/ASSUMPTIONS 163b: when `setup_stages` is non-empty (the scanner
    reported its own per-filter trail via `_SetupResult.attrition_stages`),
    the collapsed hud "setup" gate is SPLICED away and replaced by those
    real stages (e.g. `macd_signal`) — the killer must never collapse into
    an uninformative "setup" name. When empty (scanner reported none, or a
    pre-existing test double without `attrition_stages`), the "setup" gate
    is kept mapped as-is, unchanged from pre-fix behavior."""
    stages: list[dict[str, str]] = []
    for gate in gates:
        name = "bars" if gate.name == "data_integrity" else gate.name
        # ASSUMPTIONS 163b: hud's bars gate is kept only when the scanner
        # reported no stages — scanner stages open with their own bars entry,
        # and a doubled "bars" line misstates the funnel in the log.
        if name == "bars" and setup_stages:
            continue
        if name == "setup" and setup_stages:
            stages.extend(setup_stages)
            continue
        stages.append(
            {
                "name": name,
                "outcome": "pass" if gate.passed else "fail",
                "observed": gate.observed,
            }
        )
    killed_by = stages[-1]["name"] if stages and stages[-1]["outcome"] == "fail" else None
    return {"symbol": symbol, "timeframe": timeframe, "stages": stages, "killed_by": killed_by}


def render_attrition_log(state: HudState, *, equity_usd: Decimal) -> str:
    """Pure formatter (P4, TICKET-001 §4.2): header (timestamp + equity +
    universe size) + per-symbol stage lines + a SUMMARY naming per-stage
    kill counts and the overall killer filter. `equity_usd` is an explicit
    parameter (A-FIX-2) — `HudState` is a render contract and carries no
    equity field; equity is a scan input the CLI already holds. `observed`/
    log text is human prose, not a parsing surface (ASSUMPTIONS 163) —
    callers needing structured counts use `stage_kills`/`killer_filter` (see
    `ScanAttritionRecordedPayload`), not this string."""
    universe_n = len(state.attrition)
    rule = "-" * 72
    lines = [
        "====== New Scan ======",
        f"{state.generated_at.isoformat()}  equity=${equity_usd}  universe={universe_n} pairs",
        rule,
    ]

    stage_kills: dict[str, int] = {}
    for entry in state.attrition:
        lines.append(str(entry["symbol"]))
        for stage in entry["stages"]:
            lines.append(f"  {stage['name']:<15} {stage['outcome'].upper():<4} {stage['observed']}")
        killed_by = entry["killed_by"]
        if killed_by is not None:
            lines.append(f"  -> dropped at {killed_by}")
            stage_kills[killed_by] = stage_kills.get(killed_by, 0) + 1

    lines.append(rule)
    lines.append(f"SUMMARY  scanned={universe_n}  tickets={len(state.tickets)}")
    kills_line = " | ".join(f"{name} {count}" for name, count in stage_kills.items())
    lines.append(f"  attrition: {kills_line}")
    if stage_kills:
        killer_name, killer_count = max(stage_kills.items(), key=lambda item: item[1])
        lines.append(f"  killer filter: {killer_name} ({killer_count}/{universe_n})")
    else:
        lines.append("  killer filter: none")
    lines.append("=" * 72)
    return "\n".join(lines) + "\n"


def build_state(
    symbols: list[str],
    *,
    captured_at: datetime,
    equity_usd: Decimal,
    audit: ScanAuditMode = "off",
) -> HudState:
    """Walk the funnel for each symbol, grading buy/sell/hold/wait, and
    assembling an `AdvisoryTicket` only when every gate passes AND policy
    allows. `captured_at` is verbatim `generated_at` — no wall-clock reads
    (AC-8). Gate order (ASSUMPTIONS 159): open-position (hold) ->
    data_integrity -> setup -> sizing -> policy_verdict.

    `audit` (T-AUDIT-2): "off" (default) calls `scan_setup(symbol)` exactly
    as before — existing single-positional-arg test doubles keep working
    unchanged; any other mode calls `scan_setup(symbol, audit=audit)`."""
    positions = open_position_symbols()
    tickets: list[AdvisoryTicket] = []
    report: list[ScanReportEntry] = []
    attrition_entries: list[dict[str, Any]] = []

    for symbol in symbols:
        if symbol in positions:
            gates: tuple[GateResult, ...] = (
                GateResult(
                    name="open_position",
                    passed=True,
                    observed="open",
                    threshold="no open position",
                    rationale=f"{symbol} has an open thesis/position; no exit signal",
                ),
            )
            report.append(
                ScanReportEntry(
                    symbol=symbol,
                    timeframe=_TIMEFRAME,
                    indicators=(),
                    gates=gates,
                    grade="hold",
                    grade_rationale="open position with no exit signal — position safety trumps",
                )
            )
            attrition_entries.append(_attrition_entry(symbol, _TIMEFRAME, gates))
            continue

        bars, gap_reason = _fetch_bars(symbol)
        if bars is None:
            gates = (
                GateResult(
                    name="data_integrity",
                    passed=False,
                    observed=gap_reason,
                    threshold=f">= {_MIN_BARS} closed bars",
                    rationale=f"insufficient closed bar history for {symbol}",
                ),
            )
            report.append(
                ScanReportEntry(
                    symbol=symbol,
                    timeframe=_TIMEFRAME,
                    indicators=(),
                    gates=gates,
                    grade="wait",
                    grade_rationale="insufficient data to evaluate the setup",
                )
            )
            attrition_entries.append(_attrition_entry(symbol, _TIMEFRAME, gates))
            continue

        limit_price = bars.bars[-1].close
        bar_count = len(bars.bars)
        data_gate = GateResult(
            name="data_integrity",
            passed=True,
            observed=f"{bar_count} closed bars",
            threshold=f">= {_MIN_BARS} closed bars",
            rationale="sufficient closed bar history",
        )

        # Error map: a provider/scan failure degrades to a failed setup
        # gate (grade wait), never an escaping exception.
        try:
            setup = scan_setup(symbol) if audit == "off" else scan_setup(symbol, audit=audit)
        except Exception as exc:
            setup = _SetupResult(signal_tags=[])
            setup_error = f"provider error: {type(exc).__name__}"
        else:
            setup_error = ""
        # A-FIX-1/ASSUMPTIONS 163b: `getattr` — pre-existing test doubles in
        # the pinned batch suite duck-type only `.signal_tags`, no
        # `.attrition_stages` attribute; they must keep working unchanged.
        setup_stages: list[dict[str, str]] = getattr(setup, "attrition_stages", None) or []
        if not setup.signal_tags:
            gates = (
                data_gate,
                GateResult(
                    name="setup",
                    passed=False,
                    observed=setup_error or "signal_tags=[]",
                    threshold=">= 1 surviving signal_tag",
                    rationale=setup_error
                    or f"no surviving setup signal tags for {symbol} "
                    "(absent or dropped by regime gate)",
                ),
            )
            report.append(
                ScanReportEntry(
                    symbol=symbol,
                    timeframe=_TIMEFRAME,
                    indicators=(("limit_price", str(limit_price)),),
                    gates=gates,
                    grade="wait",
                    grade_rationale="no confirmed setup",
                )
            )
            attrition_entries.append(_attrition_entry(symbol, _TIMEFRAME, gates, setup_stages))
            continue

        # T-MTF-4: name the claiming strategy_key (registry walk) in the
        # gate text when present; `getattr` mirrors A-FIX-1's convention
        # so pre-existing plain `signal_tags`-only test doubles (no
        # `.strategy_key` attribute) keep working unchanged.
        strategy_key = getattr(setup, "strategy_key", "") or ""
        setup_gate = GateResult(
            name="setup",
            passed=True,
            observed=f"signal_tags={setup.signal_tags}",
            threshold=">= 1 surviving signal_tag",
            rationale=f"setup confirmed ({strategy_key})" if strategy_key else "setup confirmed",
        )

        try:
            sizing = sizing_info(symbol, limit_price, equity_usd)
        except Exception as exc:
            sizing = SizingInfo(
                qty=Decimal("0"),
                stop_distance_usd=Decimal("0"),
                r_multiple_target=Decimal("0"),
            )
            sizing_error = f"provider error: {type(exc).__name__}"
        else:
            sizing_error = ""
        if sizing.qty <= 0:
            gates = (
                data_gate,
                setup_gate,
                GateResult(
                    name="sizing",
                    passed=False,
                    observed=sizing_error or f"qty={sizing.qty}",
                    threshold="qty > 0",
                    rationale=sizing_error or f"sizing recommended no position for {symbol}",
                ),
            )
            report.append(
                ScanReportEntry(
                    symbol=symbol,
                    timeframe=_TIMEFRAME,
                    indicators=(("limit_price", str(limit_price)),),
                    gates=gates,
                    grade="wait",
                    grade_rationale="sizing produced no tradeable quantity",
                )
            )
            attrition_entries.append(_attrition_entry(symbol, _TIMEFRAME, gates, setup_stages))
            continue

        sizing_gate = GateResult(
            name="sizing",
            passed=True,
            observed=f"qty={sizing.qty}",
            threshold="qty > 0",
            rationale="sizing produced a tradeable quantity",
        )

        # SPEC-cadence T1-AC-1: the claiming def (if any) drives the
        # bracket's r_multiple and the sized qty; no def (strategy_key ""
        # or an unknown key) falls back to sizing's own r_multiple_target
        # and unscaled qty -- byte-identical to pre-batch behavior.
        from tradekit import mae

        strategy_def = mae.STRATEGY_BY_KEY.get(strategy_key) if strategy_key else None
        if strategy_def is not None and strategy_def.r_multiple_override is not None:
            r_multiple_target = strategy_def.r_multiple_override
        else:
            r_multiple_target = sizing.r_multiple_target
        qty = sizing.qty * strategy_def.size_scale if strategy_def is not None else sizing.qty

        fields = _build_ticket_fields(
            symbol,
            limit_price,
            qty,
            sizing.stop_distance_usd,
            r_multiple_target,
        )
        # Interim provenance (review round: not a ledgered thesis): honest
        # prefix + a rendered warning until real thesis wiring lands (T5).
        thesis_id = f"interim-thesis-{symbol.replace('/', '-').lower()}"
        proposal = _make_proposal(symbol, thesis_id, fields)
        decision = evaluate_policy(proposal)

        if not decision.allowed:
            gates = (
                data_gate,
                setup_gate,
                sizing_gate,
                GateResult(
                    name="policy_verdict",
                    passed=False,
                    observed="refused",
                    threshold="allow",
                    rationale=decision.rationale,
                ),
            )
            report.append(
                ScanReportEntry(
                    symbol=symbol,
                    timeframe=_TIMEFRAME,
                    indicators=(("limit_price", str(limit_price)),),
                    gates=gates,
                    grade="wait",
                    grade_rationale=decision.rationale,
                )
            )
            attrition_entries.append(_attrition_entry(symbol, _TIMEFRAME, gates, setup_stages))
            continue

        assert decision.verdict_id is not None
        ticket = AdvisoryTicket(
            pair=symbol,
            side="buy",
            mode="spot",
            order_type="limit",
            limit_price=fields["limit_price"],
            quantity=fields["quantity"],
            est_total_usd=fields["est_total_usd"],
            oso="bracket",
            tp_price=fields["tp_price"],
            tp_distance_pct=fields["tp_distance_pct"],
            sl_price=fields["sl_price"],
            sl_distance_pct=fields["sl_distance_pct"],
            est_pnl_tp_usd=fields["est_pnl_tp_usd"],
            est_pnl_sl_usd=fields["est_pnl_sl_usd"],
            est_fee_usd=fields["est_fee_usd"],
            trigger_signal="last",
            post_only=False,
            tif="gtc",
            warnings=(
                "interim provenance: thesis id not yet backed by a ledgered thesis",
            ),
            thesis_id=thesis_id,
            verdict_id=decision.verdict_id,
            created_at=captured_at,
            strategy_key=strategy_key,
        )
        tickets.append(ticket)
        gates = (
            data_gate,
            setup_gate,
            sizing_gate,
            GateResult(
                name="policy_verdict",
                passed=True,
                observed="allow",
                threshold="allow",
                rationale=decision.rationale,
            ),
        )
        report.append(
            ScanReportEntry(
                symbol=symbol,
                timeframe=_TIMEFRAME,
                indicators=(("limit_price", str(limit_price)),),
                gates=gates,
                grade="buy",
                grade_rationale="all gates passed",
            )
        )
        attrition_entries.append(_attrition_entry(symbol, _TIMEFRAME, gates, setup_stages))

    return HudState(
        generated_at=captured_at,
        tickets=tuple(tickets),
        report=tuple(report),
        attrition=tuple(attrition_entries),
    )


__all__ = ["build_state", "render_attrition_log"]
