"""`tk bridge snapshot` (T5, SPEC-bridge-read AC-9/AC-12). Typer CliRunner,
follows `test_cli_account.py` conventions. Drives the CLI down to `_read.py`'s
stubs -- red comes from `bridge.snapshot()` raising `NotImplementedError`
(caught nowhere in the CLI dispatch, so these tests fail loudly rather than
silently passing) except where a test injects its own fake via monkeypatch
to isolate the CLI's own exit-code/stream-purity contract from T4's
unfinished driver body.

FLAG (ASSUMPTIONS candidate — see report): AC-12 pins "the result's
provenance warning is emitted via the CLI on stderr" but leaves HOW the
driver signals drift up to the CLI layer entirely unspecified (dispatch
prompt explicitly routes this ambiguity to the CLI test only). This suite
pins a test-only internal seam, `tradekit.cli.main._check_bridge_map_drift`,
monkeypatched to simulate a drift warning -- not a spec pin, the minimum
hook needed to test AC-12's stderr contract independent of T4's unresolved
driver-level drift detection.

NOTE: exception classes are fetched via a fresh `import tradekit.bridge`
inside each test (not a top-level `from tradekit.bridge import ...`) to
stay identical to what `main.py`'s `bridge_snapshot()` resolves at call
time — `tests/unit/bridge/test_import_guard.py` (T2, AC-10) deliberately
deletes+reimports `tradekit.bridge` mid-session, which can leave a stale
class object bound to a module-level import captured before that reload
runs (test-order-dependent `except` identity mismatch otherwise).
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from typer.testing import CliRunner

from tradekit.cli.main import app
from tradekit.contracts import PropPanelSnapshot

runner = CliRunner()


def _snapshot() -> PropPanelSnapshot:
    return PropPanelSnapshot(
        captured_at="2026-07-19T12:00:00+00:00",  # type: ignore[arg-type]
        account_name="Starter Eval 1",
        instrument="BTC/USD",
        balance_usd=Decimal("5000.00"),
        equity_usd=None,
        mdl_remaining_usd=Decimal("1234.56"),
        mdd_remaining_usd=Decimal("-500.00"),
        target_remaining_usd=Decimal("2000.00"),
        positions=(),
    )


class TestBridgeSnapshotSuccess:
    def test_success_exits_zero_with_pure_json_decimals_as_strings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-9 CONTRACT: exit 0, stdout is ONLY the snapshot JSON, Decimal
        fields serialize as strings (never float)."""
        monkeypatch.setattr("tradekit.bridge.snapshot", lambda: _snapshot())

        result = runner.invoke(app, ["bridge", "snapshot"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["account_name"] == "Starter Eval 1"
        assert payload["balance_usd"] == "5000.00"
        assert payload["mdd_remaining_usd"] == "-500.00"
        assert result.stdout.strip().count("\n") == 0, (
            "nothing else on stdout besides the single JSON line"
        )


class TestBridgeSnapshotAppAbsent:
    def test_app_not_found_exits_two_with_one_line_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-9 CONTRACT: Kraken Desktop absent -> exit 2, one-line message."""

        def _raise() -> PropPanelSnapshot:
            from tradekit import bridge as bridge_module

            raise bridge_module.AppNotFound("Kraken Desktop not running")

        monkeypatch.setattr("tradekit.bridge.snapshot", _raise)

        result = runner.invoke(app, ["bridge", "snapshot"])

        assert result.exit_code == 2
        assert result.stdout == ""
        assert "Kraken Desktop not running" in result.stderr
        assert result.stderr.strip().count("\n") == 0, "one-line message"


class TestBridgeSnapshotParseFailure:
    def test_parse_failure_exits_three_naming_field_and_raw(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-9 CONTRACT: a `PanelParseError` -> exit 3, message names both
        the field and the raw text."""

        def _raise() -> PropPanelSnapshot:
            from tradekit import bridge as bridge_module

            raise bridge_module.PanelParseError("BALANCE", "5 000,00")

        monkeypatch.setattr("tradekit.bridge.snapshot", _raise)

        result = runner.invoke(app, ["bridge", "snapshot"])

        assert result.exit_code == 3
        assert result.stdout == ""
        assert "BALANCE" in result.stderr
        assert "5 000,00" in result.stderr


class TestBridgeSnapshotMapDrift:
    def test_app_version_drift_emits_stderr_warning_not_fatal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-12 BEHAVIOR: a map/app_version mismatch is visible (stderr)
        but does not block the read -- exit 0, snapshot JSON still on
        stdout, warning text isolated to stderr."""
        monkeypatch.setattr("tradekit.bridge.snapshot", lambda: _snapshot())
        monkeypatch.setattr(
            "tradekit.cli.main._check_bridge_map_drift",
            lambda: "warning: element map app_version 1.0.0 != connected app 1.1.0",
        )

        result = runner.invoke(app, ["bridge", "snapshot"])

        assert result.exit_code == 0
        assert "app_version" in result.stderr
        payload = json.loads(result.stdout)
        assert payload["account_name"] == "Starter Eval 1"


class TestBridgeSnapshotNoDrift:
    def test_no_drift_emits_no_stderr_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-12 BEHAVIOR (negative case): matching versions -> silent stderr."""
        monkeypatch.setattr("tradekit.bridge.snapshot", lambda: _snapshot())

        result = runner.invoke(app, ["bridge", "snapshot"])

        assert result.exit_code == 0
        assert result.stderr == ""
