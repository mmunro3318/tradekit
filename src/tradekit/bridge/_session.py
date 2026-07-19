"""THE determinism seam (design §7, SPEC-bridge-read Interface pins).

``UiaNode``/``UiaSession`` are the only surfaces production code and test
fakes share — real pywinauto wiring lands in T6 (``_pywinauto.py``);
fixture-injected sessions must work without pywinauto installed (AC-10).
"""

from __future__ import annotations

from typing import Protocol


class UiaNode(Protocol):
    @property
    def node_id(self) -> str: ...  # stable within one tree dump

    @property
    def role(self) -> str: ...  # UIA control type name

    @property
    def name(self) -> str: ...  # UIA Name property, "" if unset

    @property
    def automation_id(self) -> str: ...  # "" if unset

    @property
    def value(self) -> str: ...  # Value/Text pattern text, "" if none

    def children(self) -> list[UiaNode]: ...


class UiaSession(Protocol):
    def root(self) -> UiaNode: ...  # raises AppNotFound if app absent


def real_session() -> UiaSession:
    """Construct the pywinauto-backed session (T6). Delegates to
    `_pywinauto.real_session`, which does the guard-first optional
    dependency check before any other work (AC-10; fix round F3 — this
    used to be a duplicate unconditional-raise stub that lied about the
    install hint even when the bridge group WAS installed)."""
    from tradekit.bridge._pywinauto import real_session as _real_session

    return _real_session()


__all__ = ["UiaNode", "UiaSession", "real_session"]
