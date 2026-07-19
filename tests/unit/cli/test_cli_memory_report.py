"""`tk brief` / `tk search` / `tk wiki add` / `tk report memo|readiness|pnl`
(SPRINT P3 batch E, DESIGN §11/§12.3). `memory.brief`/`memory.search`/every
`report.*` verb are `NotImplementedError` stubs this batch —
`_guard_not_implemented` converts each into a clean nonzero exit, same
discipline as every other stubbed verb's CLI test in this codebase.
`tk wiki add` is REAL (green): `memory._wiki.add_note` has no stub.
"""

# CTO re-point (P3 batch-E dev pass, dev stop-and-flagged): these were
# stub-era clean-exit pins authored in the SAME batch whose dev pass
# implements the verbs — intra-batch obsolescence (third occurrence; the
# batch-D test_cli_fill precedent applies). Flipped to assert the real
# success path: exit 0, no traceback. Content-level behavior is pinned by
# the unit tests for each verb, not the CLI shell.

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from tradekit.cli.main import app

runner = CliRunner()


@pytest.mark.parametrize(
    "argv",
    [
        ["brief"],
        ["search", "halt"],
        ["report", "readiness"],
        ["report", "pnl", "paper:alpha"],
    ],
    ids=["brief", "search", "report-readiness", "report-pnl"],
)
def test_verb_exits_cleanly_not_a_traceback(tmp_path, argv: list[str]) -> None:
    """Collapses 4 near-identical "stubbed verb exits cleanly" pins
    (test-audit-2026-07-18.md garbage-removal item 4) into one parametrized
    smoke check: each verb's own content-level behavior is pinned by its
    dedicated unit tests (e.g. test_report.py), not the CLI shell."""
    result = runner.invoke(app, argv, env={"TK_DATA_DIR": str(tmp_path)})
    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output


def test_tk_report_memo_unknown_thesis_fails_cleanly(tmp_path) -> None:
    """CTO correction to the re-point: an UNKNOWN thesis on an empty ledger
    is a legitimate clean error (exit nonzero, meaningful message), not a
    success — the happy path is covered by test_report.py's unit tests."""
    result = runner.invoke(app, ["report", "memo", "TH-1"], env={"TK_DATA_DIR": str(tmp_path)})
    assert result.exit_code != 0, result.output
    assert "TH-1" in str(result.exception) or "TH-1" in result.output
    assert "Traceback" not in result.output


def test_tk_wiki_add_is_real_and_writes_a_file(tmp_path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(f'wiki_dir = "{(tmp_path / "wiki").as_posix()}"\n', encoding="utf-8")

    result = runner.invoke(
        app,
        ["wiki", "add", "--title", "My Note", "--body", "Some content."],
        env={"TK_DATA_DIR": str(tmp_path), "TK_CONFIG_PATH": str(config)},
    )

    assert result.exit_code == 0, result.output
    written = tmp_path / "wiki" / "my-note.md"
    assert written.exists()
    assert "Some content." in written.read_text(encoding="utf-8")
