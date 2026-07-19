"""tradekit.bridge — read-only UIA driver over Kraken Desktop (feature 1+2
of docs/design/BRIDGE-UIA.md, SPEC-bridge-read). Import-safe without the
optional ``bridge`` dependency group (pywinauto): only ``real_session()``
requires it, and only at call time (AC-10).

Public verbs ``snapshot()``/``read_ticket()`` land with T4 (``_read.py``).
"""

from __future__ import annotations

from tradekit.bridge._errors import (
    AmbiguousElement,
    AppNotFound,
    BridgeError,
    ElementMapMiss,
    PanelParseError,
)
from tradekit.bridge._read import read_ticket, snapshot
from tradekit.bridge._session import UiaNode, UiaSession, real_session

__all__ = [
    "AmbiguousElement",
    "AppNotFound",
    "BridgeError",
    "ElementMapMiss",
    "PanelParseError",
    "UiaNode",
    "UiaSession",
    "read_ticket",
    "real_session",
    "snapshot",
]
