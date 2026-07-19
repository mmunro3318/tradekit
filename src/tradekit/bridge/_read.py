"""Read verbs over an injectable UiaSession (SPEC-bridge-read Interface
pins, T4). Resolves the pinned logical selectors over the live tree via
the automation_id -> name -> path cascade, parses money fields via
`_parse.parse_money`, and maps the positions table / order ticket into
their contract shapes.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from tradekit.bridge._elementmap import ElementMap, Selector, resolve_selector
from tradekit.bridge._errors import PanelParseError
from tradekit.bridge._parse import parse_money
from tradekit.bridge._session import UiaNode, UiaSession, real_session
from tradekit.contracts import PropPanelSnapshot, PropPositionRow, TicketReadback

_POSITION_SIDES = {"long", "short"}
_TICKET_SIDES = {"buy", "sell"}


def _load_element_map_for_session(session: UiaSession) -> ElementMap:
    """Resolve which `ElementMap` a session's tree should be read against
    (real body: derive `app_version` from the tree/window title per
    ASSUMPTIONS S2, then load `elementmaps/kraken-<app_version>.json`).
    Tests monkeypatch this directly (test-writer-flagged seam, see
    test_read_verbs.py module docstring)."""
    raise NotImplementedError("bridge._load_element_map_for_session: T7 real map work")


def _resolve(root: UiaNode, name: str, selector: Selector) -> UiaNode:
    """Resolve a single logical selector against the live tree via the
    unified cascade in `_elementmap.resolve_selector` (ASSUMPTIONS
    154a/155b; fix round F1/F2/F6 — one resolver, not a duplicated copy)."""
    _tier, node = resolve_selector(root, name, selector)
    return node


def _resolve_optional(
    root: UiaNode, element_map: ElementMap, name: str
) -> UiaNode | None:
    selector = element_map.selectors.get(name)
    if selector is None:
        return None
    return _resolve(root, name, selector)


def _text(n: UiaNode | None) -> str:
    return n.value if n is not None else ""


def _optional_money(field: str, raw: str) -> Decimal | None:
    if raw == "":
        return None
    return parse_money(field, raw)


def _optional_qty(field: str, raw: str) -> Decimal | None:
    if raw == "":
        return None
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise PanelParseError(field, raw) from exc


def _row_from_node(row_node: UiaNode) -> PropPositionRow:
    cells = row_node.children()
    if len(cells) != 5:
        raise PanelParseError("positions_row", ",".join(c.value for c in cells))
    symbol_n, side_n, qty_n, entry_n, pnl_n = cells
    if side_n.value not in _POSITION_SIDES:
        raise PanelParseError("side", side_n.value)
    try:
        qty = Decimal(qty_n.value)
        entry_price = Decimal(entry_n.value)
    except InvalidOperation as exc:
        raise PanelParseError("qty/entry_price", f"{qty_n.value}/{entry_n.value}") from exc
    return PropPositionRow(
        symbol=symbol_n.value,
        side=side_n.value,  # type: ignore[arg-type]
        qty=qty,
        entry_price=entry_price,
        unrealized_pnl_usd=parse_money("unrealized_pnl_usd", pnl_n.value),
    )


def snapshot(
    *, session: UiaSession | None = None, captured_at: datetime
) -> PropPanelSnapshot:
    """Read the prop panel into a `PropPanelSnapshot` (AC-1/2/3/4/6/8/12).

    `session=None` uses the real pywinauto-backed session (`real_session()`);
    fixture injection is for tests only.
    """
    _session = session if session is not None else real_session()
    root = _session.root()
    element_map = _load_element_map_for_session(_session)

    account_name = _resolve(root, "ACCOUNT_NAME", element_map.selectors["ACCOUNT_NAME"]).value
    instrument = _resolve(root, "INSTRUMENT", element_map.selectors["INSTRUMENT"]).value
    balance_usd = parse_money(
        "BALANCE", _resolve(root, "BALANCE", element_map.selectors["BALANCE"]).value
    )
    mdl_remaining_usd = parse_money(
        "MDL_REMAINING",
        _resolve(root, "MDL_REMAINING", element_map.selectors["MDL_REMAINING"]).value,
    )
    mdd_remaining_usd = parse_money(
        "MDD_REMAINING",
        _resolve(root, "MDD_REMAINING", element_map.selectors["MDD_REMAINING"]).value,
    )
    target_node = _resolve_optional(root, element_map, "TARGET_REMAINING")
    target_remaining_usd = (
        _optional_money("TARGET_REMAINING", target_node.value) if target_node is not None else None
    )
    equity_node = _resolve_optional(root, element_map, "EQUITY")
    equity_usd = (
        _optional_money("EQUITY", equity_node.value) if equity_node is not None else None
    )

    positions_table = _resolve(
        root, "POSITIONS_TABLE", element_map.selectors["POSITIONS_TABLE"]
    )
    positions = tuple(_row_from_node(row) for row in positions_table.children())

    return PropPanelSnapshot(
        captured_at=captured_at,
        account_name=account_name,
        instrument=instrument,
        balance_usd=balance_usd,
        equity_usd=equity_usd,
        mdl_remaining_usd=mdl_remaining_usd,
        mdd_remaining_usd=mdd_remaining_usd,
        target_remaining_usd=target_remaining_usd,
        positions=positions,
    )


def read_ticket(*, session: UiaSession | None = None) -> TicketReadback:
    """Read the order ticket into a `TicketReadback` (AC-7/8)."""
    _session = session if session is not None else real_session()
    root = _session.root()
    element_map = _load_element_map_for_session(_session)

    account_name = _resolve(root, "ACCOUNT_NAME", element_map.selectors["ACCOUNT_NAME"]).value
    instrument = _resolve(root, "INSTRUMENT", element_map.selectors["INSTRUMENT"]).value
    side_raw = _resolve(root, "TICKET_SIDE", element_map.selectors["TICKET_SIDE"]).value
    order_type = _resolve(
        root, "TICKET_ORDER_TYPE", element_map.selectors["TICKET_ORDER_TYPE"]
    ).value
    qty_raw = _resolve(root, "TICKET_QTY", element_map.selectors["TICKET_QTY"]).value
    limit_raw = _resolve(
        root, "TICKET_LIMIT_PRICE", element_map.selectors["TICKET_LIMIT_PRICE"]
    ).value
    stop_raw = _resolve(
        root, "TICKET_STOP_PRICE", element_map.selectors["TICKET_STOP_PRICE"]
    ).value
    if side_raw != "" and side_raw not in _TICKET_SIDES:
        raise PanelParseError("TICKET_SIDE", side_raw)

    return TicketReadback(
        account_name=account_name,
        instrument=instrument,
        side=side_raw or None,  # type: ignore[arg-type]
        order_type=order_type,
        qty=_optional_qty("TICKET_QTY", qty_raw),
        limit_price=_optional_money("TICKET_LIMIT_PRICE", limit_raw),
        stop_price=_optional_money("TICKET_STOP_PRICE", stop_raw),
    )


__all__ = ["read_ticket", "snapshot"]
