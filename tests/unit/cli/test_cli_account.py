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
    # The JSON file omits max_trades_per_day entirely — the CLI must fill it
    # from PolicyDials.max_trades_per_day_default (0, per Mike's "paper/sim
    # only" default) rather than raising a missing-field ValidationError.
    config_path = _write_config(tmp_path)
    result = runner.invoke(
        app,
        ["account", "create-paper", "--config", config_path],
        env={"TK_DATA_DIR": str(tmp_path)},
    )
    assert result.exit_code == 0, result.output


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
