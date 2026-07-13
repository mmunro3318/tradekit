"""`tk` CLI — thin-shell dispatch only (DESIGN §4.4, TD-15).

These tests exercise the CLI *plumbing*: verb routing, --json output, exit
codes, TK_DATA_DIR resolution. Business behavior is tested at the module
level; a CLI test that re-tests ledger logic is theater.
"""

import json
import sqlite3

from typer.testing import CliRunner

from tradekit.cli.main import app

runner = CliRunner()


def test_version_prints_package_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0 and "tradekit" in result.output


def test_schema_export_writes_json_schema_files(tmp_path) -> None:
    out = tmp_path / "schemas"
    result = runner.invoke(app, ["schema", "export", "--out", str(out)])
    assert result.exit_code == 0, result.output
    thesis = out / "ThesisContract.json"
    assert thesis.exists(), (
        f"schema export wrote {sorted(p.name for p in out.glob('*.json'))}: non-Python "
        "agents get contracts ONLY through these files (§5, D9)"
    )
    parsed = json.loads(thesis.read_text(encoding="utf-8"))
    assert "properties" in parsed, "exported file must be a JSON-Schema document"


def test_ledger_verify_ok_on_fresh_data_dir(tmp_path) -> None:
    result = runner.invoke(app, ["ledger", "verify"], env={"TK_DATA_DIR": str(tmp_path)})
    assert result.exit_code == 0, (
        f"exit {result.exit_code}, output: {result.output!r} — a fresh install must "
        "verify clean (empty chain is valid, §6.2)"
    )


def test_ledger_verify_json_flag_emits_chain_report(tmp_path) -> None:
    result = runner.invoke(
        app, ["ledger", "verify", "--json"], env={"TK_DATA_DIR": str(tmp_path)}
    )
    report = json.loads(result.output)
    assert report["ok"] is True and report["first_bad_seq"] is None, (
        f"--json must emit the ChainReport shape verbatim, got {result.output!r} — "
        "agents parse this, not prose (§4.4 --json convention)"
    )


def test_ledger_verify_exits_nonzero_on_tampered_chain(tmp_path, make_event) -> None:
    from tradekit.ledger import Ledger

    ledger = Ledger(tmp_path / "ledger.db")
    ledger.append(make_event(payload={"note": "victim event", "salience": 1}))
    con = sqlite3.connect(tmp_path / "ledger.db")
    con.execute("UPDATE events SET actor = 'mallory'")
    con.commit()
    con.close()

    result = runner.invoke(app, ["ledger", "verify"], env={"TK_DATA_DIR": str(tmp_path)})
    assert result.exit_code == 1, (
        f"exit {result.exit_code}: a broken chain must be a NONZERO exit — scripts and "
        "agents branch on exit codes, and a zero here silently blesses tampered history"
    )


def test_ledger_rebuild_and_query_roundtrip(tmp_path, make_event) -> None:
    from tradekit.ledger import Ledger

    ledger = Ledger(tmp_path / "ledger.db")
    ledger.append(
        make_event(
            type="RunStarted",
            run_id="run-cli",
            payload={"run_id": "run-cli", "model": "m", "framework": "f"},
        )
    )

    rebuilt = runner.invoke(app, ["ledger", "rebuild"], env={"TK_DATA_DIR": str(tmp_path)})
    assert rebuilt.exit_code == 0, rebuilt.output

    result = runner.invoke(
        app,
        ["ledger", "query", "--type", "RunStarted", "--json"],
        env={"TK_DATA_DIR": str(tmp_path)},
    )
    events = json.loads(result.output)
    assert [e["type"] for e in events] == ["RunStarted"], (
        f"query --type RunStarted returned {events!r}: the CLI must pass filters through "
        "to Ledger.query untouched (thin shell, TD-2)"
    )
