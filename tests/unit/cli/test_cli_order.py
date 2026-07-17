"""`tk order submit|status|cancel` + `tk account reconcile` — thin-dispatch
CLI extensions (SPRINT P3 batch C, DESIGN §4.4/§8.2). Representative subset
only (per house convention, `test_cli_policy.py`'s own docstring: "not
exhaustive flags").

`broker.execute_order`/`reconcile`/`cancel_order` are REAL as of the batch-C
dev pass that lands `_pipeline.py`'s bodies — this file flips from asserting
the batch-A/B `_guard_not_implemented` CLEAN-nonzero-exit placeholder to
asserting the REAL success/refusal paths, the SAME obsolescence-update
pattern `test_cli_policy.py`'s own docstring documents for its batch-C/D
verbs ("both groups' tests were updated in their own dev pass to assert the
real success path once the underlying verb landed")."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from typer.testing import CliRunner
from ulid import ULID

from tradekit import thesis
from tradekit.cli.main import app
from tradekit.contracts import AssetRef, Bar, BarSeries, Event
from tradekit.ledger import default_ledger

runner = CliRunner()

_ASSET = AssetRef(symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))
_SUBMIT_BAR_START = datetime(2026, 1, 1, tzinfo=UTC)
_N_SUBMIT_BARS = 20


def _wide_atr_bars(n: int = _N_SUBMIT_BARS) -> BarSeries:
    # high=105/low=95 -> True Range 10 -> the SAME proven-safe ATR fixture
    # `tests/unit/broker/test_pipeline.py`/`tests/replay/test_p2_adversarial.py`
    # use: an honest $500-equity order sizes inside R-005/R-006's caps.
    bars = [
        Bar(
            ts_open=_SUBMIT_BAR_START + timedelta(days=i),
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("95"),
            close=Decimal("100"),
            volume=Decimal("1000"),
        )
        for i in range(n)
    ]
    return BarSeries(asset=_ASSET, timeframe="1d", bars=bars, source="fake-kraken")


def _fake_get_closed_bars(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
    return _wide_atr_bars()


def _fake_clock() -> datetime:
    return _SUBMIT_BAR_START + timedelta(days=_N_SUBMIT_BARS + 5)


def _build_approved_thesis(thesis_kwargs: dict, monkeypatch: pytest.MonkeyPatch) -> str:
    """Reach `approved` via the REAL draft/submit/approve verbs + a
    harness-appended `ReviewCompleted` (P2 ships no review verb) — mirrors
    `tests/unit/broker/test_pipeline.py::_build_approved_thesis`."""
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_get_closed_bars)
    monkeypatch.setattr("tradekit.mae._runtime._clock", _fake_clock)
    kw = dict(thesis_kwargs)
    kw["entry"] = {"order_type": "market", "valid_until": "2026-02-01T00:00:00Z"}
    thesis_id = thesis.draft(kw)
    thesis.submit(thesis_id)
    default_ledger().append(
        Event(
            event_id=str(ULID()),
            ts_utc=_fake_clock(),
            type="ReviewCompleted",
            actor="agent:test",
            run_id=None,
            schema_ver=1,
            payload={"thesis_id": thesis_id, "review_artifact_id": "rev-1", "passed": True},
        )
    )
    thesis.approve(thesis_id)
    return thesis_id


def test_order_submit_executes_a_real_approved_thesis(
    tmp_path, thesis_kwargs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TK_DATA_DIR", str(tmp_path))
    thesis_id = _build_approved_thesis(thesis_kwargs, monkeypatch)

    result = runner.invoke(
        app,
        ["order", "submit", thesis_id],
        env={"TK_DATA_DIR": str(tmp_path)},
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "accepted"


def test_account_reconcile_on_a_clean_paper_account_exits_zero(tmp_path) -> None:
    # No fills on either side (broker or ledger) -> a clean ReconciliationRun
    # (result="ok"), never a halt — `account reconcile` itself always exits 0
    # on a successful RUN (cli/main.py::account_reconcile's own docstring).
    result = runner.invoke(
        app,
        ["account", "reconcile", "paper:alpha"],
        env={"TK_DATA_DIR": str(tmp_path)},
    )
    assert result.exit_code == 0, result.output
    assert "reconciled paper:alpha" in result.output


def test_order_cancel_on_an_unknown_order_refuses_cleanly(tmp_path) -> None:
    # An order_id with no OrderSubmitted event on record is a real
    # OrderStatus(status="rejected") (PaperBroker, batch B) -> cancel_order's
    # OrderNotCancelable refusal (MVP: only a RESTING order is cancelable),
    # never a raw traceback.
    result = runner.invoke(
        app,
        ["order", "cancel", "--account-ref", "paper:alpha", "O-1"],
        env={"TK_DATA_DIR": str(tmp_path)},
    )
    assert result.exit_code == 1, result.output
    assert "cannot cancel" in result.output


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
