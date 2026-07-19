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

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal

import tradekit.mae._runtime as mae_runtime
from tradekit.contracts import AdvisoryTicket, GateResult, HudState, ScanReportEntry
from tradekit.contracts._marketdata import BarSeries

_TIMEFRAME = "1h"
_LOOKBACK_DAYS = 30
_MIN_BARS = 20
_FEE_RATE = Decimal("0.0004")  # 4 bps/side (ASSUMPTIONS 144)
_SETUP_FILTERS = {"macd_signal": "bullish", "volume_spike": 1.5}
# Setup scan runs at 4h: the scanner's 90-day lookback at 1h implies 2160
# bars > Kraken's 720-bar OHLC call cap (ProviderRangeError, smoke-tested
# 2026-07-19); 4h -> 540 bars fits, and matches the doctrine's 4h/1h
# structure (STRATEGY-PROCEDURE stage 2).
_SETUP_TIMEFRAME = "4h"


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


def _default_scan_setup(symbol: str) -> _SetupResult:
    """Real setup scan (ASSUMPTIONS 159b): momentum + volume confirmation,
    post-regime-gate. Empty `signal_tags` when no match survives for the
    symbol."""
    from tradekit import mae

    result = mae.scan_markets(
        "crypto", [_SETUP_TIMEFRAME], filters=_SETUP_FILTERS, symbols=[symbol], regime_gate=True
    )
    for match in result["matches"]:
        if match.get("symbol") == symbol:
            return _SetupResult(signal_tags=list(match.get("signal_tags", [])))
    return _SetupResult(signal_tags=[])


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


def build_state(symbols: list[str], *, captured_at: datetime, equity_usd: Decimal) -> HudState:
    """Walk the funnel for each symbol, grading buy/sell/hold/wait, and
    assembling an `AdvisoryTicket` only when every gate passes AND policy
    allows. `captured_at` is verbatim `generated_at` — no wall-clock reads
    (AC-8). Gate order (ASSUMPTIONS 159): open-position (hold) ->
    data_integrity -> setup -> sizing -> policy_verdict."""
    positions = open_position_symbols()
    tickets: list[AdvisoryTicket] = []
    report: list[ScanReportEntry] = []

    for symbol in symbols:
        if symbol in positions:
            report.append(
                ScanReportEntry(
                    symbol=symbol,
                    timeframe=_TIMEFRAME,
                    indicators=(),
                    gates=(
                        GateResult(
                            name="open_position",
                            passed=True,
                            observed="open",
                            threshold="no open position",
                            rationale=f"{symbol} has an open thesis/position; no exit signal",
                        ),
                    ),
                    grade="hold",
                    grade_rationale="open position with no exit signal — position safety trumps",
                )
            )
            continue

        bars, gap_reason = _fetch_bars(symbol)
        if bars is None:
            report.append(
                ScanReportEntry(
                    symbol=symbol,
                    timeframe=_TIMEFRAME,
                    indicators=(),
                    gates=(
                        GateResult(
                            name="data_integrity",
                            passed=False,
                            observed=gap_reason,
                            threshold=f">= {_MIN_BARS} closed bars",
                            rationale=f"insufficient closed bar history for {symbol}",
                        ),
                    ),
                    grade="wait",
                    grade_rationale="insufficient data to evaluate the setup",
                )
            )
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
            setup = scan_setup(symbol)
        except Exception as exc:
            setup = _SetupResult(signal_tags=[])
            setup_error = f"provider error: {type(exc).__name__}"
        else:
            setup_error = ""
        if not setup.signal_tags:
            report.append(
                ScanReportEntry(
                    symbol=symbol,
                    timeframe=_TIMEFRAME,
                    indicators=(("limit_price", str(limit_price)),),
                    gates=(
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
                    ),
                    grade="wait",
                    grade_rationale="no confirmed setup",
                )
            )
            continue

        setup_gate = GateResult(
            name="setup",
            passed=True,
            observed=f"signal_tags={setup.signal_tags}",
            threshold=">= 1 surviving signal_tag",
            rationale="setup confirmed",
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
            report.append(
                ScanReportEntry(
                    symbol=symbol,
                    timeframe=_TIMEFRAME,
                    indicators=(("limit_price", str(limit_price)),),
                    gates=(
                        data_gate,
                        setup_gate,
                        GateResult(
                            name="sizing",
                            passed=False,
                            observed=sizing_error or f"qty={sizing.qty}",
                            threshold="qty > 0",
                            rationale=sizing_error
                            or f"sizing recommended no position for {symbol}",
                        ),
                    ),
                    grade="wait",
                    grade_rationale="sizing produced no tradeable quantity",
                )
            )
            continue

        sizing_gate = GateResult(
            name="sizing",
            passed=True,
            observed=f"qty={sizing.qty}",
            threshold="qty > 0",
            rationale="sizing produced a tradeable quantity",
        )

        fields = _build_ticket_fields(
            symbol,
            limit_price,
            sizing.qty,
            sizing.stop_distance_usd,
            sizing.r_multiple_target,
        )
        # Interim provenance (review round: not a ledgered thesis): honest
        # prefix + a rendered warning until real thesis wiring lands (T5).
        thesis_id = f"interim-thesis-{symbol.replace('/', '-').lower()}"
        proposal = _make_proposal(symbol, thesis_id, fields)
        decision = evaluate_policy(proposal)

        if not decision.allowed:
            report.append(
                ScanReportEntry(
                    symbol=symbol,
                    timeframe=_TIMEFRAME,
                    indicators=(("limit_price", str(limit_price)),),
                    gates=(
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
                    ),
                    grade="wait",
                    grade_rationale=decision.rationale,
                )
            )
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
        )
        tickets.append(ticket)
        report.append(
            ScanReportEntry(
                symbol=symbol,
                timeframe=_TIMEFRAME,
                indicators=(("limit_price", str(limit_price)),),
                gates=(
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
                ),
                grade="buy",
                grade_rationale="all gates passed",
            )
        )

    return HudState(
        generated_at=captured_at,
        tickets=tuple(tickets),
        report=tuple(report),
    )


__all__ = ["build_state"]
