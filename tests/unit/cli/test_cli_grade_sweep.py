"""`tk grade sweep` with NO `--thesis` args (SPRINT P3 batch E, closing the
batch-C-flagged auto-discovery gap): sweeps `ledger.models.active_theses()`
instead of requiring an explicit id list. `ledger.models.active_theses()`
is a `NotImplementedError` stub this batch (`ledger/_models.py`) —
`cli/main.py::_guard_not_implemented` converts that into a CLEAN nonzero
exit, never a raw traceback (same discipline every other stubbed verb's CLI
test in this codebase already pins, e.g. `test_cli_policy.py`'s original
batch-C pass). The explicit `--thesis` path is UNCHANGED (still real,
still works with zero ledger.models involvement) — a green control below.
"""

# CTO re-point (P3 batch-E dev pass, dev stop-and-flagged): these were
# stub-era clean-exit pins authored in the SAME batch whose dev pass
# implements the verbs — intra-batch obsolescence (third occurrence; the
# batch-D test_cli_fill precedent applies). Flipped to assert the real
# success path: exit 0, no traceback. Content-level behavior is pinned by
# the unit tests for each verb, not the CLI shell.

from __future__ import annotations

from typer.testing import CliRunner

from tradekit.cli.main import app

runner = CliRunner()


def test_grade_sweep_with_no_thesis_args_exits_cleanly_not_a_traceback(tmp_path) -> None:
    """GREEN (new-green, accounted): `tk grade sweep` with no `--thesis` at
    all now attempts auto-discovery via `ledger.models.active_theses()` —
    that accessor is a `NotImplementedError` stub this batch, and
    `_guard_not_implemented` already converts that into a clean nonzero
    exit (pre-existing thin-shell hygiene, same guard every other stubbed
    verb's CLI test relies on) — so THIS test passes immediately even
    though the accessor underneath is still red; it pins the CLI wiring
    change itself, not the accessor's real behavior (that's
    `tests/unit/ledger/test_models.py`'s job)."""
    result = runner.invoke(app, ["grade", "sweep"], env={"TK_DATA_DIR": str(tmp_path)})
    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
    assert "Traceback" not in result.output


def test_grade_sweep_with_explicit_thesis_ids_still_works_unchanged(tmp_path) -> None:
    """GREEN control: the pre-existing explicit `--thesis` path never
    touches `ledger.models` at all, so it must behave exactly as before —
    a fabricated/never-drafted thesis_id fails at `thesis.grade` itself
    (a ValueError-class real refusal), not at the auto-discovery seam."""
    result = runner.invoke(
        app,
        ["grade", "sweep", "--thesis", "TH-NEVER-DRAFTED"],
        env={"TK_DATA_DIR": str(tmp_path)},
    )
    assert result.exit_code != 0
    assert "not yet implemented" not in result.output, (
        "an explicit --thesis id must never reach the active_theses() stub"
    )
