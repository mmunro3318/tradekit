"""`tk order submit|status|cancel` + `tk account reconcile` — thin-dispatch
CLI extensions (SPRINT P3 batch C, DESIGN §4.4/§8.2). Representative subset
only (per house convention, `test_cli_policy.py`'s own docstring: "not
exhaustive flags") — `broker.execute_order`/`reconcile`/`cancel_order` are
`NotImplementedError` stubs this batch, so every command below currently
exits 1 via `_guard_not_implemented`'s CLEAN-nonzero-exit guard (thin-shell
hygiene, real behavior, NOT the business logic itself — see
`cli/main.py::_guard_not_implemented`'s own docstring). These tests pin
that clean-exit contract NOW and are expected to flip to asserting the real
success path once the dev pass lands `_pipeline.py`'s real bodies (same
obsolescence-update pattern `test_cli_policy.py` already documents for its
own batch-C/D verbs)."""

from __future__ import annotations

from typer.testing import CliRunner

from tradekit.cli.main import app

runner = CliRunner()


def test_order_submit_on_an_unimplemented_pipeline_exits_cleanly_nonzero(tmp_path) -> None:
    result = runner.invoke(
        app,
        ["order", "submit", "TH-does-not-matter-yet"],
        env={"TK_DATA_DIR": str(tmp_path)},
    )
    assert result.exit_code == 1, result.output
    assert "not yet implemented" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_account_reconcile_on_an_unimplemented_pipeline_exits_cleanly_nonzero(tmp_path) -> None:
    result = runner.invoke(
        app,
        ["account", "reconcile", "paper:alpha"],
        env={"TK_DATA_DIR": str(tmp_path)},
    )
    assert result.exit_code == 1, result.output
    assert "not yet implemented" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_order_cancel_on_an_unimplemented_pipeline_exits_cleanly_nonzero(tmp_path) -> None:
    result = runner.invoke(
        app,
        ["order", "cancel", "--account-ref", "paper:alpha", "O-1"],
        env={"TK_DATA_DIR": str(tmp_path)},
    )
    assert result.exit_code == 1, result.output
    assert "not yet implemented" in result.output


def test_order_status_for_an_unknown_order_reports_rejected(tmp_path) -> None:
    # `broker.get(...).order_status` is REAL (PaperBroker, batch B) — an
    # order_id with no OrderSubmitted event on record returns a real
    # OrderStatus(status="rejected"), not a stub NotImplementedError. This
    # verb is thin dispatch straight to the (already-real) adapter method,
    # unlike submit/cancel/reconcile above.
    result = runner.invoke(
        app,
        ["order", "status", "--account-ref", "paper:alpha", "O-never-submitted", "--json"],
        env={"TK_DATA_DIR": str(tmp_path)},
    )
    assert result.exit_code == 0, result.output
    assert "rejected" in result.output
