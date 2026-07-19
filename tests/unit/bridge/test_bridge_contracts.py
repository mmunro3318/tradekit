"""Bridge read-verb payload contracts (SPEC-bridge-read Interface pins, T1;
satisfies AC-1/AC-6/AC-7 shape leg). CONTRACT tests only — read-verb
behavior lives in test_read_verbs.py (T4).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from tradekit.contracts import PropPanelSnapshot, PropPositionRow, TicketReadback


def _snapshot(**overrides: object) -> PropPanelSnapshot:
    base: dict[str, object] = dict(
        captured_at=datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
        account_name="Starter Eval 1",
        instrument="BTC/USD",
        balance_usd=Decimal("5000.00"),
        equity_usd=Decimal("5010.25"),
        mdl_remaining_usd=Decimal("150.00"),
        mdd_remaining_usd=Decimal("300.00"),
        target_remaining_usd=Decimal("500.00"),
        positions=(),
    )
    base.update(overrides)
    return PropPanelSnapshot(**base)  # type: ignore[arg-type]


class TestPropPositionRowContract:
    """CONTRACT: shape/typing of one positions-table row."""

    def test_money_and_qty_fields_are_decimal(self) -> None:
        row = PropPositionRow(
            symbol="BTC/USD",
            side="long",
            qty=Decimal("0.5"),
            entry_price=Decimal("60000.00"),
            unrealized_pnl_usd=Decimal("125.50"),
        )
        assert isinstance(row.qty, Decimal)
        assert isinstance(row.entry_price, Decimal)
        assert isinstance(row.unrealized_pnl_usd, Decimal)

    def test_side_rejects_value_outside_long_short(self) -> None:
        """side is Literal["long", "short"] verbatim per the pin — not the
        ticket's buy/sell vocabulary."""
        with pytest.raises(ValidationError):
            PropPositionRow(
                symbol="BTC/USD",
                side="buy",  # type: ignore[arg-type]
                qty=Decimal("0.5"),
                entry_price=Decimal("60000.00"),
                unrealized_pnl_usd=Decimal("125.50"),
            )

    def test_row_is_frozen(self) -> None:
        row = PropPositionRow(
            symbol="BTC/USD",
            side="short",
            qty=Decimal("1"),
            entry_price=Decimal("100"),
            unrealized_pnl_usd=Decimal("-5"),
        )
        with pytest.raises(ValidationError):
            row.qty = Decimal("2")  # type: ignore[misc]


class TestPropPanelSnapshotContract:
    """CONTRACT: shape of the panel snapshot payload."""

    def test_all_usd_fields_are_decimal(self) -> None:
        snap = _snapshot()
        assert isinstance(snap.balance_usd, Decimal)
        assert isinstance(snap.mdl_remaining_usd, Decimal)
        assert isinstance(snap.mdd_remaining_usd, Decimal)

    def test_equity_and_target_are_none_able(self) -> None:
        """AC-1/AC-3 lineage: panel doesn't always show equity/target —
        None is a legal, non-error value distinct from a missing field."""
        snap = _snapshot(equity_usd=None, target_remaining_usd=None)
        assert snap.equity_usd is None
        assert snap.target_remaining_usd is None

    def test_positions_is_tuple_not_list(self) -> None:
        """Pin: positions: tuple[PropPositionRow, ...] — frozen container,
        matches contracts convention (mutable list would break frozen-model
        hashing/equality)."""
        snap = _snapshot()
        assert isinstance(snap.positions, tuple)

    def test_positions_accepts_two_rows_in_given_order(self) -> None:
        """AC-6: two rows appear in on-screen order — the contract must not
        silently reorder (e.g. sort by symbol)."""
        row_a = PropPositionRow(
            symbol="BTC/USD",
            side="long",
            qty=Decimal("0.1"),
            entry_price=Decimal("60000"),
            unrealized_pnl_usd=Decimal("10"),
        )
        row_b = PropPositionRow(
            symbol="ETH/USD",
            side="short",
            qty=Decimal("2"),
            entry_price=Decimal("3000"),
            unrealized_pnl_usd=Decimal("-15"),
        )
        snap = _snapshot(positions=(row_a, row_b))
        assert snap.positions == (row_a, row_b)

    def test_captured_at_requires_timezone_aware_datetime(self) -> None:
        """Pin: AwareDatetime — captured_at is supplied by caller/CLI, never
        wall-clocked in the driver; a naive datetime is a caller bug."""
        with pytest.raises(ValidationError):
            _snapshot(captured_at=datetime(2026, 7, 19, 12, 0))  # naive

    def test_snapshot_is_frozen(self) -> None:
        snap = _snapshot()
        with pytest.raises(ValidationError):
            snap.balance_usd = Decimal("1")  # type: ignore[misc]


class TestTicketReadbackContract:
    """CONTRACT: shape of the ticket readback payload (AC-7 empty-form
    leg: side/qty/prices are None-able, not error states)."""

    def test_empty_form_is_legal_side_and_qty_none(self) -> None:
        ticket = TicketReadback(
            account_name="Starter Eval 1",
            instrument="BTC/USD",
            side=None,
            order_type="Market",
            qty=None,
            limit_price=None,
            stop_price=None,
        )
        assert ticket.side is None
        assert ticket.qty is None

    def test_side_vocabulary_is_buy_sell_not_long_short(self) -> None:
        """Ticket side uses the venue's order-entry vocabulary (buy/sell),
        distinct from PropPositionRow's long/short — a pin, not a typo."""
        with pytest.raises(ValidationError):
            TicketReadback(
                account_name="Starter Eval 1",
                instrument="BTC/USD",
                side="long",  # type: ignore[arg-type]
                order_type="Market",
                qty=None,
                limit_price=None,
                stop_price=None,
            )

    def test_order_type_is_verbatim_string(self) -> None:
        """Pin: order_type is the venue's own label, verbatim — no
        normalization/enum coercion at the contract layer."""
        ticket = TicketReadback(
            account_name="Starter Eval 1",
            instrument="BTC/USD",
            side="buy",
            order_type="Stop-Limit",
            qty=Decimal("0.25"),
            limit_price=Decimal("61000.00"),
            stop_price=Decimal("60500.00"),
        )
        assert ticket.order_type == "Stop-Limit"

    def test_readback_is_frozen(self) -> None:
        ticket = TicketReadback(
            account_name="Starter Eval 1",
            instrument="BTC/USD",
            side=None,
            order_type="Market",
            qty=None,
            limit_price=None,
            stop_price=None,
        )
        with pytest.raises(ValidationError):
            ticket.side = "buy"  # type: ignore[misc]
