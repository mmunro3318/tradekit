"""`PaperBroker.account()`/`.positions()` — ledger-projection arithmetic
(DESIGN §8.1/§8.3, TD-24). SPRINT P3 batch B: both methods are
`NotImplementedError` stubs (`src/tradekit/broker/_paper.py`); every test
below is RED for that reason — assertions pin the EXACT hand-derived
arithmetic the dev pass must produce.

State discipline under test (CTO pin, `_paper.py`'s module docstring):
`PaperBroker` holds no mutable state of its own — these tests seed
`AccountCreated` (via the already-real `broker.create_paper_account`,
batch A) and `FillRecorded` events directly on the ledger (the harness
pattern used throughout `tests/unit/thesis/`), then construct a FRESH
`PaperBroker(account_ref=...)` and assert its projection matches.

`FillRecordedPayload` (this batch's typed contract,
`tradekit.contracts.FillRecordedPayload`) is used to build every seeded
event so the fixture itself is validated against the real producer-side
shape — `model_dump(mode="json")` into the envelope, same pattern as every
other typed payload in the codebase (ASSUMPTIONS 10).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from ulid import ULID

from tradekit import broker
from tradekit.broker._paper import PaperBroker
from tradekit.contracts import AccountConfig, Event, FillRecordedPayload
from tradekit.ledger import Ledger

_ACCOUNT_REF = "paper:account-state-test"
_T0 = datetime(2026, 1, 2, tzinfo=UTC)


def _seed_account(ledger: Ledger, principal: str = "500.00") -> None:
    broker.create_paper_account(
        AccountConfig(
            account_ref=_ACCOUNT_REF, principal_usd=Decimal(principal), max_trades_per_day=0
        )
    )


def _append_fill(
    ledger: Ledger,
    *,
    order_id: str,
    thesis_id: str,
    ts: datetime,
    price: str,
    qty: str,
    fees_usd: str,
    side: str,
    symbol: str = "BTC/USD",
    fee_asset_qty: str | None = None,
) -> None:
    # `symbol` is REQUIRED on FillRecordedPayload (CTO adjudication
    # 2026-07-17: a defaulted symbol on a money payload is silent
    # fabrication) — the harness names it explicitly; the keyword default
    # here is a fixture convenience only, local to this file.
    #
    # `fee_asset_qty` (SPEC-inkind-fees, AC-2/AC-5): only passed through to
    # the payload model when a caller supplies it explicitly (kwarg not
    # None) — every PRE-EXISTING call site above omits it, so those fixed
    # regression pins stay unaffected by this batch's new field.
    kwargs: dict[str, Any] = dict(
        order_id=order_id,
        thesis_id=thesis_id,
        account_ref=_ACCOUNT_REF,
        ts_utc=ts,
        price=Decimal(price),
        qty=Decimal(qty),
        fees_usd=Decimal(fees_usd),
        side=side,  # type: ignore[arg-type]
        quote_snapshot={"ts_open": ts.isoformat(), "close": price, "source": "fixture"},
        symbol=symbol,
    )
    if fee_asset_qty is not None:
        kwargs["fee_asset_qty"] = Decimal(fee_asset_qty)
    payload = FillRecordedPayload(**kwargs)
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


def test_account_state_after_a_single_buy_fill(ledger: Ledger) -> None:
    """Buy-only round: kraken/crypto costs (fee_rate=0.0026, half_spread_
    rate=0.0010, TD-8), mid=50000.00, qty=0.001.
        fill_price = 50000.00 * 1.0010 = 50050.00
        cost       = 50050.00 * 0.001  = 50.05
        fee        = 0.0026 * 50.00    = 0.13   (notional = mid*qty = 50.00)
        settled_cash = principal - cost - fee = 500.00 - 50.05 - 0.13 = 449.82
    No margin modeled in MVP (FLAGGED, ASSUMPTIONS round-17): buying_power_
    usd == settled_cash_usd, a cash-settled paper account."""
    _seed_account(ledger)
    _append_fill(
        ledger,
        order_id="ord-1",
        thesis_id="TH-1",
        ts=_T0,
        price="50050.00",
        qty="0.001",
        fees_usd="0.13",
        side="buy",
    )

    account = PaperBroker(account_ref=_ACCOUNT_REF, ledger=ledger).account()
    assert account.account_ref == _ACCOUNT_REF
    assert account.settled_cash_usd == Decimal("449.82")
    assert account.buying_power_usd == Decimal("449.82")
    assert account.equity_usd == Decimal("449.82")


def test_positions_after_a_single_buy_fill(ledger: Ledger) -> None:
    _seed_account(ledger)
    _append_fill(
        ledger,
        order_id="ord-1",
        thesis_id="TH-1",
        ts=_T0,
        price="50050.00",
        qty="0.001",
        fees_usd="0.13",
        side="buy",
    )

    positions = PaperBroker(account_ref=_ACCOUNT_REF, ledger=ledger).positions()
    assert len(positions) == 1
    position = positions[0]
    assert position.account_ref == _ACCOUNT_REF
    assert position.symbol == "BTC/USD"
    assert position.qty == Decimal("0.001")
    assert position.avg_price == Decimal("50050.00")


def test_account_state_after_a_buy_and_sell_round_trip(ledger: Ledger) -> None:
    """Full round trip, hand-derived from the SAME costs-table constants:
        BUY  mid=50000.00 qty=0.001 -> fill=50050.00, fee=0.13
             cost = 50050.00 * 0.001 = 50.05
             buy total out = 50.05 + 0.13 = 50.18
        SELL mid=55000.00 qty=0.001 -> fill = 55000.00 * 0.9990 = 54945.00
             notional = 55000.00 * 0.001 = 55.00; fee = 0.0026 * 55.00 = 0.143
             proceeds = 54945.00 * 0.001 = 54.945
             sell net = 54.945 - 0.143 = 54.802
        settled_cash = 500.00 - 50.18 + 54.802 = 504.622
    """
    _seed_account(ledger)
    _append_fill(
        ledger,
        order_id="ord-1",
        thesis_id="TH-1",
        ts=_T0,
        price="50050.00",
        qty="0.001",
        fees_usd="0.13",
        side="buy",
    )
    _append_fill(
        ledger,
        order_id="ord-2",
        thesis_id="TH-1",
        ts=_T0 + timedelta(days=1),
        price="54945.00",
        qty="0.001",
        fees_usd="0.143",
        side="sell",
    )

    account = PaperBroker(account_ref=_ACCOUNT_REF, ledger=ledger).account()
    assert account.settled_cash_usd == Decimal("504.622")
    assert account.equity_usd == Decimal("504.622")
    assert account.buying_power_usd == Decimal("504.622")


def test_positions_omits_a_fully_closed_symbol_after_round_trip(ledger: Ledger) -> None:
    """A symbol whose net fill qty nets to zero is not "open" (BrokerPort.
    positions()'s own docstring: "Every open position on this account") —
    FLAGGED convention (ASSUMPTIONS round-17): a zero-qty Position row is
    OMITTED, never returned with qty == 0."""
    _seed_account(ledger)
    _append_fill(
        ledger,
        order_id="ord-1",
        thesis_id="TH-1",
        ts=_T0,
        price="50050.00",
        qty="0.001",
        fees_usd="0.13",
        side="buy",
    )
    _append_fill(
        ledger,
        order_id="ord-2",
        thesis_id="TH-1",
        ts=_T0 + timedelta(days=1),
        price="54945.00",
        qty="0.001",
        fees_usd="0.143",
        side="sell",
    )

    positions = PaperBroker(account_ref=_ACCOUNT_REF, ledger=ledger).positions()
    assert positions == []


def test_account_state_with_zero_fills_is_just_the_principal(ledger: Ledger) -> None:
    _seed_account(ledger, principal="500.00")
    account = PaperBroker(account_ref=_ACCOUNT_REF, ledger=ledger).account()
    assert account.settled_cash_usd == Decimal("500.00")
    assert account.equity_usd == Decimal("500.00")
    assert account.buying_power_usd == Decimal("500.00")
    assert PaperBroker(account_ref=_ACCOUNT_REF, ledger=ledger).positions() == []


# ---------------------------------------------------------------------------
# In-kind crypto fee physics, READ side (SPEC-inkind-fees, AC-2/AC-5) — a
# `fee_asset_qty`-bearing fill seeded DIRECTLY (bypassing PaperBroker.submit,
# same "ledger-projection arithmetic" isolation as every test above) pins
# how `account()`/`positions()` must consume the new field once it exists.
# `FillRecordedPayload` has no `fee_asset_qty` field yet, so `_append_fill`
# passing it raises `pydantic.ValidationError` (extra_forbidden) — the
# RIGHT reason for red here, until the dev pass adds the field.
# ---------------------------------------------------------------------------

# 2026-07-26 live-receipt buy leg (dev-log 07-26b): fee withheld IN-KIND,
# never a separate cash deduction (AC-2).
_INKIND_PRICE = Decimal("1885.45357")  # post-spread fill price, mid=1883.57 * 1.0010
_INKIND_QTY = Decimal("0.002602483")
_INKIND_FEE_ASSET_QTY = Decimal("0.000006507")  # ceil9(0.0025 * 0.002602483), spec's own example
_INKIND_FEES_USD = _INKIND_FEE_ASSET_QTY * _INKIND_PRICE  # USD valuation only, not a cash charge


def test_account_state_after_alpaca_crypto_buy_has_no_separate_fee_deduction(
    ledger: Ledger,
) -> None:
    """AC-2 (SPEC-inkind-fees), read side: once `fee_asset_qty > 0` on a
    buy fill, `account()` must NOT ALSO subtract `fees_usd` from cash — the
    fee is already embodied in the withheld qty, unlike the legacy
    kraken/equity buy physics pinned by `test_account_state_after_a_single_
    buy_fill` above (unchanged, still deducts notional + fees_usd).
        expected settled_cash = 500.00 - (qty * price), fees_usd ignored
    """
    _seed_account(ledger)
    _append_fill(
        ledger,
        order_id="ord-1",
        thesis_id="TH-1",
        ts=_T0,
        price=str(_INKIND_PRICE),
        qty=str(_INKIND_QTY),
        fees_usd=str(_INKIND_FEES_USD),
        side="buy",
        symbol="ETH/USD",
        fee_asset_qty=str(_INKIND_FEE_ASSET_QTY),
    )

    account = PaperBroker(account_ref=_ACCOUNT_REF, ledger=ledger).account()
    expected = Decimal("500.00") - (_INKIND_QTY * _INKIND_PRICE)
    assert account.settled_cash_usd == expected
    assert account.equity_usd == expected
    assert account.buying_power_usd == expected


def test_positions_after_alpaca_crypto_buy_subtracts_the_in_kind_withhold(
    ledger: Ledger,
) -> None:
    """AC-5 (SPEC-inkind-fees): `positions()` qty = sum(buy.qty -
    buy.fee_asset_qty) - sum(sell.qty) — held qty = 0.002602483 -
    0.000006507 = 0.002595976, matching the live-receipt held ETH amount."""
    _seed_account(ledger)
    _append_fill(
        ledger,
        order_id="ord-1",
        thesis_id="TH-1",
        ts=_T0,
        price=str(_INKIND_PRICE),
        qty=str(_INKIND_QTY),
        fees_usd=str(_INKIND_FEES_USD),
        side="buy",
        symbol="ETH/USD",
        fee_asset_qty=str(_INKIND_FEE_ASSET_QTY),
    )

    positions = PaperBroker(account_ref=_ACCOUNT_REF, ledger=ledger).positions()
    assert len(positions) == 1
    expected_qty = _INKIND_QTY - _INKIND_FEE_ASSET_QTY
    assert expected_qty == Decimal("0.002595976")
    assert positions[0].qty == expected_qty


def test_positions_flat_after_selling_exactly_the_net_in_kind_held_qty(
    ledger: Ledger,
) -> None:
    """AC-5 round trip, read side: selling EXACTLY the net held qty (Q - W,
    never the gross filled qty Q) must leave the account flat — same
    zero-qty-row-omitted representation as `test_positions_omits_a_fully_
    closed_symbol_after_round_trip` above (unchanged)."""
    _seed_account(ledger)
    held_qty = _INKIND_QTY - _INKIND_FEE_ASSET_QTY
    _append_fill(
        ledger,
        order_id="ord-1",
        thesis_id="TH-1",
        ts=_T0,
        price=str(_INKIND_PRICE),
        qty=str(_INKIND_QTY),
        fees_usd=str(_INKIND_FEES_USD),
        side="buy",
        symbol="ETH/USD",
        fee_asset_qty=str(_INKIND_FEE_ASSET_QTY),
    )
    _append_fill(
        ledger,
        order_id="ord-2",
        thesis_id="TH-1",
        ts=_T0 + timedelta(days=1),
        price="1882.03",
        qty=str(held_qty),
        fees_usd="0.0122",  # irrelevant to positions() qty
        side="sell",
        symbol="ETH/USD",
    )

    positions = PaperBroker(account_ref=_ACCOUNT_REF, ledger=ledger).positions()
    assert positions == []
