"""AC-10: tradekit.bridge import-without-pywinauto guard (SPEC-bridge-read,
T2). SEAM tests — the boundary under test is "does the optional
`bridge` dependency group being absent break the package import."
"""

from __future__ import annotations

import sys

import pytest

from tradekit.bridge import BridgeError, real_session


class TestImportWithoutPywinauto:
    def test_package_imports_when_pywinauto_module_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SEAM: simulate pywinauto not installed (module import raises)
        and re-import tradekit.bridge fresh — the package import itself
        must not touch pywinauto at all (AC-10)."""
        # Restore-parent-attr guard (green-bridge-2 finding): the fresh
        # importlib.import_module below rebinds the ATTRIBUTE
        # `tradekit.bridge` on the persistent top-level package; monkeypatch
        # only restores sys.modules entries. Register the attr restore
        # FIRST so teardown re-points the attribute chain at the original
        # module object (keeps dotted-string monkeypatching in later tests
        # honest).
        import tradekit

        monkeypatch.setattr(tradekit, "bridge", sys.modules["tradekit.bridge"])
        monkeypatch.setitem(sys.modules, "pywinauto", None)
        for mod in list(sys.modules):
            if mod == "tradekit.bridge" or mod.startswith("tradekit.bridge."):
                monkeypatch.delitem(sys.modules, mod, raising=False)

        import importlib

        module = importlib.import_module("tradekit.bridge")
        assert module is not None


class TestRealSessionGuard:
    """AC-10: constructing the REAL session (not fixture-injected) raises
    BridgeError with the install hint when the bridge group is absent."""

    def test_real_session_raises_bridge_error(self) -> None:
        with pytest.raises(BridgeError):
            real_session()

    def test_real_session_error_names_install_command(self) -> None:
        """Hint must name `uv sync --group bridge` verbatim per AC-10 so a
        user can copy-paste the fix directly from the error."""
        with pytest.raises(BridgeError, match=r"uv sync --group bridge"):
            real_session()
