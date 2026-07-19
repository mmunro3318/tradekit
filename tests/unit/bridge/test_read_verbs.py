"""AC-1,2,3,4,6,7,8 (T4, SPEC-bridge-read): `bridge.snapshot()` /
`bridge.read_ticket()` over `FakeUiaSession` fixture trees.

FLAG (ASSUMPTIONS candidate — see report, do not silently trust): the spec
pins `POSITIONS_TABLE` as a single logical selector but does NOT pin how
per-row fields (symbol/side/qty/entry_price/unrealized_pnl_usd) are
extracted from that node. This suite assumes the resolved POSITIONS_TABLE
node's `.children()` are row nodes in on-screen order, and each row
node's `.children()` are five cell nodes in FIXED order
`[symbol, side, qty, entry_price, unrealized_pnl_usd]` read via `.value`.

FLAG: `by:"path"` selector semantics are unpinned (ASSUMPTIONS 154a covers
the automation_id/name cascade only). This suite assumes a `path`
selector's `value` is a list of `name` strings, each resolved as the
unique node anywhere in the previous match's subtree carrying that
`name` (root-relative ordered descent) — exercised by `POSITIONS_TABLE`
in every fixture map below, per batch-2 dispatch instruction.

FLAG: `PropPanelSnapshot.captured_at` is pinned "supplied by caller/CLI,
not wall-clocked in the driver", but the pinned `snapshot(*, session=None)`
signature has no `captured_at` parameter to receive it. This suite does
NOT assert an exact `captured_at` value (untestable against the pin as
written) — only that it is present and timezone-aware; the golden
comparison below excludes that field.

FLAG: the pinned `snapshot(*, session=None)`/`read_ticket(*, session=None)`
signatures carry no way to inject WHICH `ElementMap` a fixture session
resolves against (the real path is `elementmaps/kraken-<app_version>.json`,
but T7's real map doesn't exist yet and fixture trees aren't real Kraken
builds). This suite pins a test-only internal seam,
`tradekit.bridge._read._load_element_map_for_session(session)`, monkeypatched
per test to return a hand-built `ElementMap` — NOT part of the public
surface, invented here only as the minimum hook GREEN work needs to make
map resolution testable at all.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from conftest import FakeUiaSession, node
from tradekit.bridge import AmbiguousElement, AppNotFound, ElementMapMiss, read_ticket, snapshot
from tradekit.bridge._elementmap import ElementMap, Selector
from tradekit.contracts import PropPanelSnapshot, PropPositionRow, TicketReadback


def _use_map(monkeypatch: pytest.MonkeyPatch, element_map: ElementMap) -> None:
    monkeypatch.setattr(
        "tradekit.bridge._read._load_element_map_for_session", lambda session: element_map
    )


def _row(symbol: str, side: str, qty: str, entry: str, pnl: str, *, node_id: str) -> object:
    return node(
        node_id,
        role="DataItem",
        children=[
            node(f"{node_id}-symbol", value=symbol),
            node(f"{node_id}-side", value=side),
            node(f"{node_id}-qty", value=qty),
            node(f"{node_id}-entry", value=entry),
            node(f"{node_id}-pnl", value=pnl),
        ],
    )


def _positions_panel(rows: list[object]) -> object:
    """`by:"path": ["Panel", "PositionsGrid"]` resolves through this
    root -> Panel -> PositionsGrid chain (see module docstring FLAG)."""
    return node(
        "panel",
        name="Panel",
        children=[node("grid", name="PositionsGrid", children=rows)],
    )


def _base_map(**selector_overrides: Selector) -> ElementMap:
    selectors: dict[str, Selector] = {
        "ACCOUNT_NAME": Selector(by="automation_id", value="accountNameValue"),
        "INSTRUMENT": Selector(by="automation_id", value="instrumentValue"),
        "BALANCE": Selector(by="automation_id", value="balanceValue"),
        "MDL_REMAINING": Selector(by="automation_id", value="mdlValue"),
        "MDD_REMAINING": Selector(by="automation_id", value="mddValue"),
        "TARGET_REMAINING": Selector(by="automation_id", value="targetValue"),
        "POSITIONS_TABLE": Selector(by="path", value=["Panel", "PositionsGrid"]),
    }
    selectors.update(selector_overrides)
    return ElementMap(
        app_version="1.0.0", captured_utc="2026-07-19T00:00:00Z", selectors=selectors
    )


def _base_tree(*, positions: list[object] | None = None) -> object:
    return node(
        "root",
        role="Window",
        name="Kraken Desktop",
        children=[
            node("account", automation_id="accountNameValue", value="Starter Eval 1"),
            node("instrument", automation_id="instrumentValue", value="BTC/USD"),
            node("balance", automation_id="balanceValue", value="$5,000.00"),
            node("mdl", automation_id="mdlValue", value="$1,234.56"),
            node("mdd", automation_id="mddValue", value="-$500.00"),
            node("target", automation_id="targetValue", value="$2,000.00"),
            _positions_panel(positions or []),
        ],
    )


class TestSnapshotGolden:
    def test_full_fixture_tree_yields_hand_derived_golden_snapshot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-1 GOLDEN. Hand derivation (independent of `_parse.parse_money`,
        per the pinned numeric rule: strip `$`/`,`, cent-quantize):
            "$5,000.00" -> "5000.00"   -> Decimal("5000.00")
            "$1,234.56" -> "1234.56"   -> Decimal("1234.56")
            "-$500.00"  -> "-500.00"   -> Decimal("-500.00")
            "$2,000.00" -> "2000.00"   -> Decimal("2000.00")
        Row 1: qty "10" -> Decimal("10"); entry "150.25" -> Decimal("150.25");
        pnl "25.50" -> Decimal("25.50").
        Row 2: qty "5" -> Decimal("5"); entry "800.00" -> Decimal("800.00");
        pnl "-120.75" -> Decimal("-120.75").
        No EQUITY selector exists in the pinned logical-selector list at all
        -> `equity_usd` is always None (panel never shows it, per spec text).
        """
        rows = [
            _row("AAPL", "long", "10", "150.25", "25.50", node_id="row1"),
            _row("TSLA", "short", "5", "800.00", "-120.75", node_id="row2"),
        ]
        tree = _base_tree(positions=rows)
        session = FakeUiaSession(tree)
        _use_map(monkeypatch, _base_map())

        result = snapshot(session=session)

        assert result.captured_at.tzinfo is not None, "captured_at must be timezone-aware"
        expected = PropPanelSnapshot(
            captured_at=result.captured_at,
            account_name="Starter Eval 1",
            instrument="BTC/USD",
            balance_usd=Decimal("5000.00"),
            equity_usd=None,
            mdl_remaining_usd=Decimal("1234.56"),
            mdd_remaining_usd=Decimal("-500.00"),
            target_remaining_usd=Decimal("2000.00"),
            positions=(
                PropPositionRow(
                    symbol="AAPL",
                    side="long",
                    qty=Decimal("10"),
                    entry_price=Decimal("150.25"),
                    unrealized_pnl_usd=Decimal("25.50"),
                ),
                PropPositionRow(
                    symbol="TSLA",
                    side="short",
                    qty=Decimal("5"),
                    entry_price=Decimal("800.00"),
                    unrealized_pnl_usd=Decimal("-120.75"),
                ),
            ),
        )
        assert result == expected


class TestSnapshotAppNotFound:
    def test_app_absent_propagates_typed_app_not_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-2 BEHAVIOR: never a bare COM/pywinauto error, never a
        fabricated snapshot."""
        session = FakeUiaSession(None, app_present=False)
        _use_map(monkeypatch, _base_map())
        with pytest.raises(AppNotFound):
            snapshot(session=session)


class TestSnapshotElementMapMiss:
    def test_missing_balance_selector_raises_with_selector_and_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-3 BEHAVIOR: `ElementMapMiss` carries `selector="BALANCE"` and
        a hint naming nearest-role candidates — never a partial snapshot
        with a defaulted balance. The fixture tree has NO node with
        automation_id/name matching the BALANCE selector's value at all."""
        tree = node(
            "root",
            role="Window",
            children=[
                node("account", automation_id="accountNameValue", value="Starter Eval 1"),
                node("instrument", automation_id="instrumentValue", value="BTC/USD"),
                # balance node deliberately absent
                node("mdl", automation_id="mdlValue", value="$1,234.56"),
                node("mdd", automation_id="mddValue", value="-$500.00"),
                node("target", automation_id="targetValue", value="$2,000.00"),
                _positions_panel([]),
            ],
        )
        session = FakeUiaSession(tree)
        _use_map(monkeypatch, _base_map())

        with pytest.raises(ElementMapMiss) as excinfo:
            snapshot(session=session)

        assert excinfo.value.selector == "BALANCE"
        assert excinfo.value.hint


class TestSnapshotAmbiguousElement:
    def test_balance_selector_matching_two_nodes_raises_ambiguous(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-4 BEHAVIOR: two nodes share the BALANCE selector's
        automation_id -> first-match is never silently taken."""
        tree = node(
            "root",
            role="Window",
            children=[
                node("account", automation_id="accountNameValue", value="Starter Eval 1"),
                node("instrument", automation_id="instrumentValue", value="BTC/USD"),
                node("balance1", automation_id="balanceValue", value="$5,000.00"),
                node("balance2", automation_id="balanceValue", value="$9,999.00"),
                node("mdl", automation_id="mdlValue", value="$1,234.56"),
                node("mdd", automation_id="mddValue", value="-$500.00"),
                node("target", automation_id="targetValue", value="$2,000.00"),
                _positions_panel([]),
            ],
        )
        session = FakeUiaSession(tree)
        _use_map(monkeypatch, _base_map())

        with pytest.raises(AmbiguousElement) as excinfo:
            snapshot(session=session)

        assert excinfo.value.selector == "BALANCE"
        assert excinfo.value.count == 2


class TestSnapshotEmptyPositions:
    def test_zero_position_rows_yields_empty_tuple_not_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-6 BEHAVIOR: empty positions table -> `()`, not an error."""
        tree = _base_tree(positions=[])
        session = FakeUiaSession(tree)
        _use_map(monkeypatch, _base_map())

        result = snapshot(session=session)

        assert result.positions == ()


class TestSnapshotTwoPositionRowsOrder:
    def test_two_rows_appear_in_on_screen_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-6 BEHAVIOR: rows appear in on-screen (tree) order, not
        resorted, with Decimal qty/prices."""
        rows = [
            _row("TSLA", "short", "5", "800.00", "-120.75", node_id="row1"),
            _row("AAPL", "long", "10", "150.25", "25.50", node_id="row2"),
        ]
        tree = _base_tree(positions=rows)
        session = FakeUiaSession(tree)
        _use_map(monkeypatch, _base_map())

        result = snapshot(session=session)

        assert [row.symbol for row in result.positions] == ["TSLA", "AAPL"]
        assert result.positions[0].qty == Decimal("5")
        assert result.positions[1].qty == Decimal("10")


def _ticket_map() -> ElementMap:
    return ElementMap(
        app_version="1.0.0",
        captured_utc="2026-07-19T00:00:00Z",
        selectors={
            "ACCOUNT_NAME": Selector(by="automation_id", value="accountNameValue"),
            "INSTRUMENT": Selector(by="automation_id", value="instrumentValue"),
            "TICKET_SIDE": Selector(by="automation_id", value="ticketSideValue"),
            "TICKET_ORDER_TYPE": Selector(by="automation_id", value="ticketOrderTypeValue"),
            "TICKET_QTY": Selector(by="automation_id", value="ticketQtyValue"),
            "TICKET_LIMIT_PRICE": Selector(by="automation_id", value="ticketLimitPriceValue"),
            "TICKET_STOP_PRICE": Selector(by="automation_id", value="ticketStopPriceValue"),
        },
    )


class TestReadTicketEmpty:
    def test_no_side_selected_and_empty_qty_returns_none_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-7 BEHAVIOR: empty-form is a valid readback, not an error;
        `order_type` is returned verbatim from the panel's own label."""
        tree = node(
            "root",
            role="Window",
            children=[
                node("account", automation_id="accountNameValue", value="Starter Eval 1"),
                node("instrument", automation_id="instrumentValue", value="BTC/USD"),
                node("side", automation_id="ticketSideValue", value=""),
                node("order_type", automation_id="ticketOrderTypeValue", value="Market"),
                node("qty", automation_id="ticketQtyValue", value=""),
                node("limit", automation_id="ticketLimitPriceValue", value=""),
                node("stop", automation_id="ticketStopPriceValue", value=""),
            ],
        )
        session = FakeUiaSession(tree)
        _use_map(monkeypatch, _ticket_map())

        result = read_ticket(session=session)

        assert result == TicketReadback(
            account_name="Starter Eval 1",
            instrument="BTC/USD",
            side=None,
            order_type="Market",
            qty=None,
            limit_price=None,
            stop_price=None,
        )


class TestReadOnlyCallLog:
    def test_snapshot_call_log_shows_only_read_operations(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-8 SEAM: the fake's call log records ONLY `root`/`children:*`
        entries — zero invoke/click/set/keyboard calls, because the
        `UiaSession`/`UiaNode` Protocol exposes no such verbs at all."""
        rows = [_row("AAPL", "long", "10", "150.25", "25.50", node_id="row1")]
        tree = _base_tree(positions=rows)
        session = FakeUiaSession(tree)
        _use_map(monkeypatch, _base_map())

        snapshot(session=session)

        assert session.calls, "expected at least one recorded call"
        for call in session.calls:
            assert call == "root" or call.startswith("children:"), (
                f"unexpected non-read call recorded: {call!r}"
            )
        assert not any(
            verb in call for call in session.calls for verb in FakeUiaSession.WRITE_VERBS
        )
