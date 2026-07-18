"""`tk fill record` (DESIGN §4.4/§8.4, D16, SPRINT P3 batch D) --
representative subset only (house convention, `test_cli_policy.py`'s own
docstring: "not exhaustive flags").

`broker.record_manual_fill` is a `NotImplementedError` stub this batch --
this test pins the SAME clean-nonzero-exit stub-era behavior
`test_cli_order.py`'s original batch-B/C red pass used for
`execute_order`/`reconcile` (`_guard_not_implemented`'s own docstring):
a stubbed verb is still a CLEAN nonzero exit, never a raw traceback."""

from __future__ import annotations

from typer.testing import CliRunner

from tradekit.cli.main import app

runner = CliRunner()


def test_fill_record_succeeds_now_that_record_manual_fill_is_real(tmp_path) -> None:
    """CTO re-point (batch-D dev pass, dev stop-and-flagged the conflict):
    this test was authored as a stub-era clean-exit pin in the SAME batch
    whose dev pass implements record_manual_fill — intra-batch obsolescence,
    a TDD authoring slip. Flipped to assert the real success path (same
    pattern as test_cli_policy/test_broker_stubs), asserting MORE, not
    less."""
    result = runner.invoke(
        app,
        [
            "fill",
            "record",
            "--thesis",
            "TH-1",
            "--price",
            "60000.00",
            "--qty",
            "0.001",
            "--fees",
            "0.50",
            "--side",
            "buy",
            "--symbol",
            "BTC/USD",
            "--account-ref",
            "advisory:kraken",
        ],
        env={"TK_DATA_DIR": str(tmp_path)},
    )
    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
