"""Bridge error taxonomy (SPEC-bridge-read Interface pins). Real (not
stubbed) — errors are contracts, not implementation.
"""

from __future__ import annotations


class BridgeError(Exception):
    """Base for every bridge-raised error. Never a bare COM/pywinauto
    error crosses the bridge boundary (AC-2)."""


class AppNotFound(BridgeError):
    """Kraken Desktop not running."""


class ElementMapMiss(BridgeError):
    """A pinned logical selector has no match in the live tree.

    AC-3: carries the selector name and a hint naming nearest-role
    candidates — never a partial snapshot with a defaulted field.
    """

    def __init__(self, selector: str, hint: str) -> None:
        self.selector = selector
        self.hint = hint
        super().__init__(f"{selector}: {hint}")


class AmbiguousElement(BridgeError):
    """A selector matched more than one node — first-match is never
    silently taken (AC-4)."""

    def __init__(self, selector: str, count: int) -> None:
        self.selector = selector
        self.count = count
        super().__init__(f"{selector}: {count} matches")


class PanelParseError(BridgeError):
    """Raw panel text failed the numeric parse rule (AC-5)."""

    def __init__(self, field: str, raw_text: str) -> None:
        self.field = field
        self.raw_text = raw_text
        super().__init__(f"{field}: unparseable text {raw_text!r}")


__all__ = [
    "AmbiguousElement",
    "AppNotFound",
    "BridgeError",
    "ElementMapMiss",
    "PanelParseError",
]
