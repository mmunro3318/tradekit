"""AC-11 (T6, SPEC-bridge-read): probe artifact round-trip + grade-field
consistency, and the `_pywinauto.real_session` import-guard-first
ordering. Pure-helper tests only — `scripts/probe_uia_kraken.py`'s `main()`
requires a live Kraken Desktop attach (T7, MIKE-GATED); this batch tests
`dump_tree`/`build_artifact`/`load_artifact` directly, importable without
one, per the T6 done criterion ("probe runs to --help on this machine").
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import node

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from probe_uia_kraken import build_artifact, dump_tree, load_artifact

from tradekit.bridge._elementmap import ElementMap, Selector, grade_exposure
from tradekit.bridge._errors import BridgeError


class TestArtifactRoundTrip:
    def test_build_dump_write_load_round_trips_the_same_tree(self, tmp_path: Path) -> None:
        """AC-11 BEHAVIOR: artifact JSON round-trips (load -> same tree)."""
        tree = node(
            "root",
            role="Window",
            children=[
                node("balance", automation_id="balanceValue", value="$5,000.00"),
                node("account", automation_id="accountNameValue", value="Starter Eval 1"),
            ],
        )
        element_map = ElementMap(
            app_version="1.0.0",
            captured_utc="2026-07-19T00:00:00Z",
            selectors={
                "BALANCE": Selector(by="automation_id", value="balanceValue"),
                "ACCOUNT_NAME": Selector(by="automation_id", value="accountNameValue"),
            },
        )

        artifact = build_artifact(
            tree, element_map, app_version="1.0.0", captured_utc="2026-07-19T00:00:00Z"
        )
        out = tmp_path / "probe.json"
        out.write_text(json.dumps(artifact), encoding="utf-8")

        loaded = load_artifact(str(out))

        assert loaded["app_version"] == "1.0.0"
        assert loaded["exposure_grade"] == "A"
        assert loaded["tree"] == dump_tree(tree)
        assert loaded["tree"]["children"][0]["automation_id"] == "balanceValue"
        assert loaded["tree"]["children"][0]["value"] == "$5,000.00"


class TestGradeFieldConsistency:
    @pytest.mark.parametrize(
        ("balance_aid", "balance_name", "selector_value", "expected_grade"),
        [
            # A: BALANCE resolvable by automation_id (selector value matches it).
            ("balanceValue", "", "balanceValue", "A"),
            # B: BALANCE only resolvable by name (no matching automation_id;
            # the selector's own value matches the node's `name` instead —
            # `_resolve_tier` cascades the SAME value string automation_id -> name).
            ("", "balanceValue", "balanceValue", "B"),
            # C: BALANCE unresolvable (selector value matches neither).
            ("", "", "balanceValue", "C"),
        ],
    )
    def test_artifact_exposure_grade_matches_grade_exposure_directly(
        self, balance_aid: str, balance_name: str, selector_value: str, expected_grade: str
    ) -> None:
        """AC-11 GOLDEN: the artifact's `exposure_grade` field is exactly
        `grade_exposure(tree, element_map)` — one fixture per grade A/B/C
        per the pinned rule."""
        tree = node(
            "root",
            role="Window",
            children=[node("balance", automation_id=balance_aid, name=balance_name)],
        )
        element_map = ElementMap(
            app_version="1.0.0",
            captured_utc="2026-07-19T00:00:00Z",
            selectors={"BALANCE": Selector(by="automation_id", value=selector_value)},
        )

        artifact = build_artifact(
            tree, element_map, app_version="1.0.0", captured_utc="2026-07-19T00:00:00Z"
        )

        assert artifact["exposure_grade"] == expected_grade
        assert artifact["exposure_grade"] == grade_exposure(tree, element_map)


class TestPywinautoGuardOrdering:
    """T6: `_pywinauto.real_session()` checks the optional dependency
    BEFORE any attach/NotImplementedError work (guard-first ordering)."""

    def test_missing_pywinauto_raises_bridge_error_before_not_implemented(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import builtins

        real_import = builtins.__import__

        def _fake_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "pywinauto":
                raise ImportError("no module named pywinauto")
            return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(builtins, "__import__", _fake_import)

        from tradekit.bridge._pywinauto import real_session

        with pytest.raises(BridgeError):
            real_session()


class TestProbeScriptHelp:
    def test_probe_script_runs_to_help_without_pywinauto_or_live_app(self) -> None:
        """T6 done criterion: `probe_uia_kraken.py --help` runs on this
        machine without needing a live Kraken Desktop or pywinauto."""
        script = Path(__file__).resolve().parents[3] / "scripts" / "probe_uia_kraken.py"
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert "probe" in result.stdout.lower() or "usage" in result.stdout.lower()
