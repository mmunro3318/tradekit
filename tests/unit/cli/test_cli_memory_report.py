"""`tk brief` / `tk search` / `tk wiki add` / `tk report memo|readiness|pnl`
(SPRINT P3 batch E, DESIGN §11/§12.3). `memory.brief`/`memory.search`/every
`report.*` verb are `NotImplementedError` stubs this batch —
`_guard_not_implemented` converts each into a clean nonzero exit, same
discipline as every other stubbed verb's CLI test in this codebase.
`tk wiki add` is REAL (green): `memory._wiki.add_note` has no stub.
"""

from __future__ import annotations

from typer.testing import CliRunner

from tradekit.cli.main import app

runner = CliRunner()


def test_tk_brief_stub_exits_cleanly_not_a_traceback(tmp_path) -> None:
    result = runner.invoke(app, ["brief"], env={"TK_DATA_DIR": str(tmp_path)})
    assert result.exit_code == 1, result.output
    assert "not yet implemented" in result.output
    assert "Traceback" not in result.output


def test_tk_search_stub_exits_cleanly_not_a_traceback(tmp_path) -> None:
    result = runner.invoke(app, ["search", "halt"], env={"TK_DATA_DIR": str(tmp_path)})
    assert result.exit_code == 1, result.output
    assert "not yet implemented" in result.output


def test_tk_report_memo_stub_exits_cleanly(tmp_path) -> None:
    result = runner.invoke(app, ["report", "memo", "TH-1"], env={"TK_DATA_DIR": str(tmp_path)})
    assert result.exit_code == 1, result.output
    assert "not yet implemented" in result.output


def test_tk_report_readiness_stub_exits_cleanly(tmp_path) -> None:
    result = runner.invoke(app, ["report", "readiness"], env={"TK_DATA_DIR": str(tmp_path)})
    assert result.exit_code == 1, result.output


def test_tk_report_pnl_stub_exits_cleanly(tmp_path) -> None:
    result = runner.invoke(
        app, ["report", "pnl", "paper:alpha"], env={"TK_DATA_DIR": str(tmp_path)}
    )
    assert result.exit_code == 1, result.output


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
