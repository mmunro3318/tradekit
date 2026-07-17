"""`tk thesis|grade|policy|promote` — thin-dispatch CLI extensions (SPRINT P2
batch C; DESIGN §4.4, TD-15). A representative subset only, per the sprint
doc ("not exhaustive flags"): `tk thesis draft` from a JSON file exercises
the one verb group that's REAL this sprint end-to-end (GREEN); `tk policy
status`/`halt`/`resume`/`tk promote status` exercise the CLEAN-nonzero-exit
guard around this batch's stubbed `policy.*` verbs (also GREEN — the guard
itself is real thin-shell hygiene, not the business logic it's guarding;
see `cli/main.py::_guard_not_implemented`'s docstring).
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from tradekit.cli.main import app

runner = CliRunner()


def test_thesis_draft_from_a_json_file(tmp_path, thesis_kwargs) -> None:
    contract_file = tmp_path / "contract.json"
    contract_file.write_text(json.dumps(thesis_kwargs, default=str), encoding="utf-8")

    result = runner.invoke(
        app,
        ["thesis", "draft", "--file", str(contract_file)],
        env={"TK_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["thesis_id"] == thesis_kwargs["thesis_id"], (
        "tk thesis draft is pure dispatch to thesis.draft() — it must return the SAME "
        "thesis_id the contract file specified, not mint a new one (TD-2)"
    )


def test_thesis_draft_then_show_returns_the_drafted_events(tmp_path, thesis_kwargs) -> None:
    contract_file = tmp_path / "contract.json"
    contract_file.write_text(json.dumps(thesis_kwargs, default=str), encoding="utf-8")
    env = {"TK_DATA_DIR": str(tmp_path)}

    draft_result = runner.invoke(app, ["thesis", "draft", "--file", str(contract_file)], env=env)
    assert draft_result.exit_code == 0, draft_result.output
    thesis_id = json.loads(draft_result.output)["thesis_id"]

    show_result = runner.invoke(app, ["thesis", "show", thesis_id], env=env)
    assert show_result.exit_code == 0, show_result.output
    events = json.loads(show_result.output)
    assert [e["type"] for e in events] == ["ThesisDrafted"]


def test_policy_status_exits_nonzero_cleanly_on_not_implemented(tmp_path) -> None:
    result = runner.invoke(
        app, ["policy", "status", "--json"], env={"TK_DATA_DIR": str(tmp_path)}
    )
    assert result.exit_code == 1, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit), (
        "the CLI must catch NotImplementedError itself and exit cleanly — a raw traceback "
        "propagating out of CliRunner.invoke is not an acceptable failure mode "
        f"(got exception={result.exception!r})"
    )
    assert "not yet implemented" in result.output


def test_policy_halt_then_resume_round_trip_exits_nonzero_cleanly(tmp_path) -> None:
    env = {"TK_DATA_DIR": str(tmp_path)}

    halt_result = runner.invoke(app, ["policy", "halt", "reconciliation mismatch"], env=env)
    assert halt_result.exit_code == 1
    assert "not yet implemented" in halt_result.output

    resume_result = runner.invoke(app, ["policy", "resume"], env=env)
    assert resume_result.exit_code == 1
    assert "not yet implemented" in resume_result.output


def test_promote_status_exits_nonzero_cleanly_on_not_implemented(tmp_path) -> None:
    result = runner.invoke(
        app, ["promote", "status", "--json"], env={"TK_DATA_DIR": str(tmp_path)}
    )
    assert result.exit_code == 1, result.output
    assert "not yet implemented" in result.output
