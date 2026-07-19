"""Real pywinauto-backed `UiaSession` (SPEC-bridge-read T6). Guard-first
ordering (pinned by dispatch): `real_session()` must check for the
optional `bridge` dependency group BEFORE any other work — even though
the actual attach logic isn't built yet, the install-hint `BridgeError`
must fire first, never masked by a later `NotImplementedError` or an
uncaught `ImportError`.
"""

from __future__ import annotations

from tradekit.bridge._errors import BridgeError
from tradekit.bridge._session import UiaSession


def real_session() -> UiaSession:
    """Construct the real pywinauto-backed session. Guard fires first
    (AC-10, install hint `uv sync --group bridge`); real attach to Kraken
    Desktop lands with T7."""
    try:
        import pywinauto  # type: ignore[import-not-found]  # noqa: F401
    except ImportError as exc:
        raise BridgeError(
            "real UIA session requires the optional bridge dependency group — "
            "run `uv sync --group bridge`"
        ) from exc
    raise NotImplementedError("bridge._pywinauto.real_session: real attach lands with T7")


__all__ = ["real_session"]
