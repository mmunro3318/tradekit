"""Read verbs over an injectable UiaSession (SPEC-bridge-read Interface
pins, T4). RED stub — real bodies (selector resolution over the
automation_id -> name -> path cascade, panel parsing via `_parse.parse_money`,
positions/ticket field mapping) land with T4 GREEN work. Signatures and the
`session=None` -> real-session default are pinned now.
"""

from __future__ import annotations

from tradekit.bridge._elementmap import ElementMap
from tradekit.bridge._session import UiaSession, real_session
from tradekit.contracts import PropPanelSnapshot, TicketReadback


def _load_element_map_for_session(session: UiaSession) -> ElementMap:
    """Resolve which `ElementMap` a session's tree should be read against
    (real body: derive `app_version` from the tree/window title per
    ASSUMPTIONS S2, then load `elementmaps/kraken-<app_version>.json`).
    RED stub for T4 — GREEN work fills this in; tests monkeypatch it
    directly (test-writer-flagged seam, see test_read_verbs.py module
    docstring)."""
    raise NotImplementedError("bridge._load_element_map_for_session: T4 green work")


def snapshot(*, session: UiaSession | None = None) -> PropPanelSnapshot:
    """Read the prop panel into a `PropPanelSnapshot` (AC-1/2/3/4/6/8/12).

    `session=None` uses the real pywinauto-backed session (`real_session()`);
    fixture injection is for tests only.
    """
    _session = session if session is not None else real_session()
    raise NotImplementedError("bridge.snapshot: T4 green work")


def read_ticket(*, session: UiaSession | None = None) -> TicketReadback:
    """Read the order ticket into a `TicketReadback` (AC-7/8)."""
    _session = session if session is not None else real_session()
    raise NotImplementedError("bridge.read_ticket: T4 green work")


__all__ = ["read_ticket", "snapshot"]
