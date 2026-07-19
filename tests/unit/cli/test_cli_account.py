"""`tk account create-paper` (TD-24, SPRINT P3 batch A) — thin CLI dispatch
over `broker.create_paper_account` (DESIGN §4.4, TD-15/TD-2).
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from tradekit.cli.main import app

runner = CliRunner()


def _write_config(tmp_path, **overrides: object) -> str:
    base: dict[str, object] = {
        "account_ref": "paper:cli-account",
        "principal_usd": "500.00",
    }
    base.update(overrides)
    path = tmp_path / "account.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    return str(path)


def test_create_paper_from_a_config_file_emits_the_account_ref(tmp_path) -> None:
    config_path = _write_config(tmp_path)
    result = runner.invoke(
        app,
        ["account", "create-paper", "--config", config_path],
        env={"TK_DATA_DIR": str(tmp_path)},
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"account_ref": "paper:cli-account"}


def test_create_paper_fills_missing_fields_from_config_toml_defaults(tmp_path) -> None:
    """The JSON file omits `max_trades_per_day` entirely — the CLI must fill
    it from `PolicyDials.max_trades_per_day_default` (0, per Mike's "paper/
    sim only" default, `src/tradekit/cli/main.py`'s own
    `raw.setdefault("max_trades_per_day", dials.max_trades_per_day_default)`)
    rather than raising a missing-field ValidationError. Strengthened from
    exit_code-only (test-audit-2026-07-18.md garbage-removal item 7): reads
    back the `AccountCreated` event's own `config` payload — the same
    ledger-projection round trip `broker.create_paper_account` performs — and
    asserts the DEFAULTED VALUE actually landed, not just that the CLI
    didn't crash."""
    from tradekit.ledger import default_ledger

    config_path = _write_config(tmp_path)
    result = runner.invoke(
        app,
        ["account", "create-paper", "--config", config_path],
        env={"TK_DATA_DIR": str(tmp_path)},
    )
    assert result.exit_code == 0, result.output

    # The suite-wide autouse `_tk_data_dir_isolation` fixture (tests/conftest.py)
    # already points TK_DATA_DIR at this SAME `tmp_path` for the whole test, so
    # `default_ledger()` here resolves to the exact ledger file the CLI just wrote.
    from tradekit.contracts import EventFilter

    events = default_ledger().query(EventFilter(types=["AccountCreated"]))
    assert len(events) == 1, "exactly one AccountCreated event must be appended"
    assert events[0].payload["config"]["max_trades_per_day"] == 0, (
        "max_trades_per_day must be filled from PolicyDials.max_trades_per_day_default "
        "(0) when the config file omits it — this is the config.toml default this test "
        "must actually observe landing, not merely a clean exit code"
    )


def test_create_paper_duplicate_account_ref_is_a_clean_nonzero_exit(tmp_path) -> None:
    config_path = _write_config(tmp_path)
    first = runner.invoke(
        app,
        ["account", "create-paper", "--config", config_path],
        env={"TK_DATA_DIR": str(tmp_path)},
    )
    assert first.exit_code == 0, first.output

    second = runner.invoke(
        app,
        ["account", "create-paper", "--config", config_path],
        env={"TK_DATA_DIR": str(tmp_path)},
    )
    assert second.exit_code == 1, second.output
    assert "already exists" in second.output
    assert second.exception is None or isinstance(second.exception, SystemExit), (
        "a duplicate account_ref must exit cleanly via typer.Exit, never an "
        "unhandled traceback"
    )
