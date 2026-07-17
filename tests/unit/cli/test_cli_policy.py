"""`tk thesis|grade|policy|promote` — thin-dispatch CLI extensions (SPRINT P2
batch C; DESIGN §4.4, TD-15). A representative subset only, per the sprint
doc ("not exhaustive flags"): `tk thesis draft` from a JSON file exercises
the one verb group that's REAL this sprint end-to-end (GREEN); `tk policy
status`/`halt`/`resume` originally exercised the CLEAN-nonzero-exit guard
around batch-C's stubbed `policy.*` verbs; `tk promote status`/`confirm`
originally did the same for batch-D's stubbed `promotion_status`/
`confirm_promotion` (the guard itself is real thin-shell hygiene, not the
business logic it's guarding; see `cli/main.py::_guard_not_implemented`'s
docstring) — both groups' tests were updated in their own dev pass to assert
the real success path once the underlying verb landed (see each test's own
note).
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


def test_policy_status_exits_zero_now_that_policy_status_is_real(tmp_path) -> None:
    # NOTE (batch-C dev pass): `policy.status`/`halt`/`resume` landed REAL
    # this batch (the sprint doc's own batch-C dispatch scope). These two
    # tests originally pinned `_guard_not_implemented`'s CLEAN-nonzero-exit
    # behavior for a batch-C state that's now superseded — the file's own
    # docstring flagged this as pinning "this batch's stubbed policy.*
    # verbs", not permanent business behavior. Updated to assert the real
    # success path instead of re-deriving stub semantics that no longer
    # exist; flagged for CTO ratification alongside the rest of this
    # batch's flags.
    result = runner.invoke(
        app, ["policy", "status", "--json"], env={"TK_DATA_DIR": str(tmp_path)}
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["halted"] is False
    assert "policy_version_hash" in payload
    assert "rules" in payload


def test_policy_halt_then_resume_round_trip_exits_zero_now_that_real(tmp_path) -> None:
    # See the note on test_policy_status_exits_zero_now_that_policy_status_is_real
    # above — halt/resume are real this batch, not stubs.
    env = {"TK_DATA_DIR": str(tmp_path)}

    halt_result = runner.invoke(app, ["policy", "halt", "reconciliation mismatch"], env=env)
    assert halt_result.exit_code == 0, halt_result.output
    assert "halted" in halt_result.output

    resume_result = runner.invoke(app, ["policy", "resume"], env=env)
    assert resume_result.exit_code == 0, resume_result.output
    assert "resumed" in resume_result.output


def test_promote_status_exits_zero_now_that_promotion_status_is_real(tmp_path) -> None:
    # NOTE (batch-D dev pass): `policy.promotion_status` landed REAL this
    # batch (story 4) — same obsolescence-update pattern already applied to
    # `policy status`/`halt`/`resume` in the batch-C dev pass (see the note
    # on test_policy_status_exits_zero_now_that_policy_status_is_real
    # above). This test originally pinned `_guard_not_implemented`'s
    # CLEAN-nonzero-exit behavior for the (now superseded) batch-C/D-red
    # stub state; updated to assert the real success path instead.
    result = runner.invoke(
        app, ["promote", "status", "--json"], env={"TK_DATA_DIR": str(tmp_path)}
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["tier"] in {"T0", "T1", "T2"}
    assert "t2_eligible" in payload
