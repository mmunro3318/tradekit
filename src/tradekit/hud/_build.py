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
from decimal import ROUND_HALF_EVEN, Decimal

import tradekit.mae._runtime as mae_runtime
from tradekit.contracts import AdvisoryTicket, GateResult, HudState, ScanReportEntry
from tradekit.contracts._marketdata import BarSeries

_TIMEFRAME = "1h"
_LOOKBACK_DAYS = 30
_MIN_BARS = 20
_FEE_RATE = Decimal("0.0004")  # 4 bps/side (ASSUMPTIONS 144)
# Interim bracket rule (ASSUMPTIONS 158): TP/SL derived off the limit
# price until real thesis/sizing funnel wiring lands (T5).
_TP_MULT = Decimal("1.05")
_SL_MULT = Decimal("0.97")


@dataclass(frozen=True)
class _PolicyDecision:
    allowed: bool
    verdict_id: str | None
    rationale: str


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


def _default_size_qty(symbol: str, limit_price: Decimal) -> Decimal:
    """ASSUMPTIONS 158: real min-ATR/quarter-Kelly sizing wiring lands with
    the funnel task (T5). Until then the default is LOUD — never a
    fabricated quantity on an advisory surface Mike transcribes from."""
    raise RuntimeError(
        "hud sizing is not wired yet (ASSUMPTIONS 158 / task T5) — "
        "size_qty must be provided before advisory tickets can be built"
    )


# Test seams (ASSUMPTIONS 157a/158). Tests monkeypatch these module
# attributes directly; production code below calls them via this module's
# own namespace so the seam takes effect.
evaluate_policy = _default_evaluate_policy
open_position_symbols = _default_open_position_symbols
size_qty = _default_size_qty


def _fetch_bars(symbol: str) -> BarSeries | None:
    """`None` signals "insufficient/gap" (AC-6): too few bars, or the
    provider raised — either way the symbol degrades to a visible failed
    `data_integrity` gate, never an escaping exception."""
    try:
        series = mae_runtime.get_closed_bars(symbol, _TIMEFRAME, _LOOKBACK_DAYS)
    except Exception:
        return None
    if len(series.bars) < _MIN_BARS:
        return None
    return series


def _build_ticket_fields(
    symbol: str, limit_price: Decimal, quantity: Decimal
) -> dict[str, Decimal]:
    tp_price = (limit_price * _TP_MULT).quantize(limit_price, rounding=ROUND_HALF_EVEN)
    sl_price = (limit_price * _SL_MULT).quantize(limit_price, rounding=ROUND_HALF_EVEN)

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


def build_state(symbols: list[str], *, captured_at: datetime) -> HudState:
    """Walk the funnel for each symbol, grading buy/sell/hold/wait, and
    assembling an `AdvisoryTicket` only when every gate passes AND policy
    allows. `captured_at` is verbatim `generated_at` — no wall-clock reads
    (AC-8)."""
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

        bars = _fetch_bars(symbol)
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
                            observed=f"< {_MIN_BARS} closed bars",
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
        quantity = size_qty(symbol, limit_price)
        fields = _build_ticket_fields(symbol, limit_price, quantity)
        thesis_id = f"thesis-{symbol.replace('/', '-').lower()}"
        proposal = _make_proposal(symbol, thesis_id, fields)
        decision = evaluate_policy(proposal)

        bar_count = len(bars.bars)
        data_gate = GateResult(
            name="data_integrity",
            passed=True,
            observed=f"{bar_count} closed bars",
            threshold=f">= {_MIN_BARS} closed bars",
            rationale="sufficient closed bar history",
        )

        if not decision.allowed:
            report.append(
                ScanReportEntry(
                    symbol=symbol,
                    timeframe=_TIMEFRAME,
                    indicators=(("limit_price", str(limit_price)),),
                    gates=(
                        data_gate,
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
            warnings=(),
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
