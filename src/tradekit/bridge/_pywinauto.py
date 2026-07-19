"""Real pywinauto-backed `UiaSession` (SPEC-bridge-read T6/T7). Guard-first
ordering (pinned, AC-10): `real_session()` checks for the optional `bridge`
dependency group BEFORE any other work — the install-hint `BridgeError`
must fire first, never masked by a later error.

T7 attach (2026-07-20): wraps pywinauto's UIA backend. `root()` finds the
Kraken Desktop top-level window (title "Kraken") or raises `AppNotFound`.
Nodes adapt `UIAElementInfo` to the `UiaNode` protocol; `value` prefers the
UIA Value/Text patterns via `rich_text`, empty string when absent. READ
ONLY: nothing here (or in the read verbs) clicks, types, or invokes.
"""

from __future__ import annotations

from typing import Any

from tradekit.bridge._errors import AppNotFound, BridgeError
from tradekit.bridge._session import UiaNode, UiaSession

_KRAKEN_TITLE = "Kraken"


class _PywinautoNode:
    """`UiaNode` over a pywinauto `UIAElementInfo` (read-only adapter)."""

    def __init__(self, info: Any) -> None:
        self._info = info

    @property
    def node_id(self) -> str:
        rid = getattr(self._info, "runtime_id", None)
        return "-".join(str(p) for p in rid) if rid else ""

    @property
    def role(self) -> str:
        return str(getattr(self._info, "control_type", "") or "")

    @property
    def name(self) -> str:
        return str(getattr(self._info, "name", "") or "")

    @property
    def automation_id(self) -> str:
        return str(getattr(self._info, "automation_id", "") or "")

    @property
    def value(self) -> str:
        try:
            return str(getattr(self._info, "rich_text", "") or "")
        except Exception:  # COM elements can die mid-read; absent, not fatal
            return ""

    def children(self) -> list[UiaNode]:
        try:
            kids = self._info.children()
        except Exception:
            return []
        return [_PywinautoNode(k) for k in kids]


class _PywinautoSession:
    def root(self) -> UiaNode:
        from pywinauto import Desktop  # type: ignore[import-untyped]  # deferred; guard ran

        for win in Desktop(backend="uia").windows():
            try:
                if win.window_text().strip() == _KRAKEN_TITLE:
                    return _PywinautoNode(win.element_info)
            except Exception:
                continue
        raise AppNotFound(
            f"no top-level window titled {_KRAKEN_TITLE!r} — is Kraken Desktop running?"
        )


def real_session() -> UiaSession:
    """Construct the real pywinauto-backed session. Guard fires first
    (AC-10, install hint `uv sync --group bridge`)."""
    try:
        import pywinauto  # noqa: F401
    except ImportError as exc:
        raise BridgeError(
            "real UIA session requires the optional bridge dependency group — "
            "run `uv sync --group bridge`"
        ) from exc
    return _PywinautoSession()


__all__ = ["real_session"]
