"""GOLDEN — `thesis._grade_wiring.compute_pnl` on the 2026-07-26 live $5 ETH
round-trip receipts (SPEC-inkind-fees, AC-7). Every number below is the
VERBATIM measured fill from the live Alpaca paper account (dev-log 07-26b);
the expected `pnl` is derived INDEPENDENTLY, in this file, from the SPEC's
own pinned formula applied to those inputs — never read off the code under
test.

Derivation source (independent, spec's own provenance note): Alpaca live
order receipts + account balance delta, 2026-07-26 UTC. The venue's own
account balance moved $50.00 -> $49.97 over this round trip — the ~-$0.03
cent-display figure this golden's `pnl` must agree with to the cent.

Provenance / hand arithmetic (Decimal, exact — reproduced from
docs/specs/SPEC-inkind-fees.md's "Measured ground truth"):

    ENTRY (buy, alpaca crypto — fee withheld IN-KIND from the received ETH):
        qty   = 0.002602483
        price = 1883.57
        fee_asset_qty = ceil9(0.0025 * 0.002602483)
                      = ceil9(0.0000065062075) = 0.000006507
        entry_notional = qty * price = 0.002602483 * 1883.57
                        = 4.90195890431

    EXIT (sell, USD-side fee — unchanged sell physics):
        qty   = 0.002595976   (== entry qty - fee_asset_qty, the NET held
                                amount — the exit-order-verb pin: sells are
                                sized from the net position, never the
                                gross entry filled_qty)
        price = 1882.03
        exit_notional  = qty * price = 0.002595976 * 1882.03
                        = 4.88570471128
        exit_fees_usd  = 0.0025 * exit_notional = 0.012214261778200

    PNL (SPEC's pinned long-round-trip formula):
        pnl = (exit.qty * exit.price - exit.fees_usd) - (entry.qty * entry.price)
              - (entry.fees_usd if entry.fee_asset_qty == 0 else Decimal("0"))
        entry.fee_asset_qty == 0.000006507 != 0, so the entry-fees term is
        DROPPED (rationale: the in-kind entry fee is already realized as
        the reduced exit qty — subtracting its USD valuation too would
        double-count):
        pnl = (4.88570471128 - 0.012214261778200) - 4.90195890431
            = 4.873490449501800 - 4.90195890431
            = -0.028468454808200

    Sanity band (spec's own venue-measured cent display, $50.00 -> $49.97):
        -0.03 < pnl < -0.028   ->  -0.028468454808200 satisfies this.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal

from ulid import ULID

from tradekit.contracts import Event, FillRecordedPayload
from tradekit.ledger import Ledger
from tradekit.thesis._grade_wiring import compute_pnl

_THESIS_ID = "TH-inkind-golden-eth-roundtrip"
_ENTRY_TS = datetime(2026, 7, 26, 2, 0, tzinfo=UTC)
_EXIT_TS = datetime(2026, 7, 26, 2, 5, tzinfo=UTC)

_ENTRY_QTY = Decimal("0.002602483")
_ENTRY_PRICE = Decimal("1883.57")
_ENTRY_FEE_ASSET_QTY = (Decimal("0.0025") * _ENTRY_QTY).quantize(
    Decimal("1e-9"), rounding=ROUND_CEILING
)

_EXIT_QTY = Decimal("0.002595976")
_EXIT_PRICE = Decimal("1882.03")
_EXIT_NOTIONAL = _EXIT_QTY * _EXIT_PRICE
_EXIT_FEES_USD = Decimal("0.0025") * _EXIT_NOTIONAL


def _append_fill(
    ledger: Ledger,
    *,
    order_id: str,
    ts: datetime,
    price: Decimal,
    qty: Decimal,
    fees_usd: Decimal,
    side: str,
    fee_asset_qty: Decimal,
) -> None:
    payload = FillRecordedPayload(
        order_id=order_id,
        thesis_id=_THESIS_ID,
        account_ref="alpaca-paper:main",
        ts_utc=ts,
        price=price,
        qty=qty,
        fees_usd=fees_usd,
        fee_asset_qty=fee_asset_qty,
        side=side,  # type: ignore[arg-type]
        quote_snapshot={},
        symbol="ETH/USD",
    )
    ledger.append(
        Event(
            event_id=str(ULID()),
            ts_utc=ts,
            type="FillRecorded",
            actor="system:test-harness",
            run_id=None,
            schema_ver=1,
            payload=payload.model_dump(mode="json"),
        )
    )


def test_compute_pnl_on_the_live_eth_round_trip_matches_the_venue_balance_delta_to_the_cent(
    ledger: Ledger,
) -> None:
    """GOLDEN (AC-7, SPEC-inkind-fees): the two live-receipt fills verbatim
    -> `compute_pnl` (direction="long") reproduces the exact Decimal
    hand-derived in this file's module docstring, and that value agrees
    with the venue's own $50.00 -> $49.97 balance delta to the cent."""
    _append_fill(
        ledger,
        order_id="ord-entry-eth",
        ts=_ENTRY_TS,
        price=_ENTRY_PRICE,
        qty=_ENTRY_QTY,
        # Realistic USD valuation (fee_asset_qty * price), NOT zero: the SPEC
        # formula must DROP this term when fee_asset_qty > 0 — feeding zero
        # here would let a double-subtracting implementation pass silently.
        fees_usd=_ENTRY_FEE_ASSET_QTY * _ENTRY_PRICE,
        side="buy",
        fee_asset_qty=_ENTRY_FEE_ASSET_QTY,
    )
    _append_fill(
        ledger,
        order_id="ord-exit-eth",
        ts=_EXIT_TS,
        price=_EXIT_PRICE,
        qty=_EXIT_QTY,
        fees_usd=_EXIT_FEES_USD,
        side="sell",
        fee_asset_qty=Decimal("0"),
    )

    pnl = compute_pnl(ledger, _THESIS_ID, "long")

    expected_pnl = (_EXIT_NOTIONAL - _EXIT_FEES_USD) - (_ENTRY_QTY * _ENTRY_PRICE)
    assert expected_pnl == Decimal("-0.0284684548082"), (
        "sanity check on this file's own independent hand-derivation (module docstring)"
    )
    assert pnl == expected_pnl
    assert Decimal("-0.03") < pnl < Decimal("-0.028"), (
        "must agree with the venue's own measured $50.00 -> $49.97 balance delta to the cent"
    )
