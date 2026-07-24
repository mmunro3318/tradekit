"""SPRINT-AUDIT-BUNDLE P6 (CTO adjudication A2, ASSUMPTIONS 165-167):
`policy/_context.py::strategy_metrics_for_account`'s `except ValueError:
return None` narrows to `except ValueError: if trade_log: raise; return
None` — an empty trade log stays a clean `None` (insufficient_context,
never a fabricated verdict), but a `ValueError` from the metrics compute
WITH a non-empty trade log must PROPAGATE (loud), never silently swallowed
into a `None` that looks identical to "nothing to evaluate yet".

Monkeypatch style mirrors `test_promotion.py`'s sanctioned seam (dotted
string path `"tradekit.mae.compute_strategy_metrics"`) — that file's tests
monkeypatch it to RETURN a `StrategyMetrics` instance; these monkeypatch it
to RAISE `ValueError` instead. No conflict: different test functions, same
external boundary (the `mae.compute_strategy_metrics` call), reviewer-
confirmed compatible per the dispatch prompt.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from ulid import ULID

from tradekit.contracts import Event
from tradekit.ledger import default_ledger
from tradekit.policy._context import strategy_metrics_for_account
from tradekit.policy._dials import PolicyDials

ACCOUNT = "paper:alpha"
EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


def _append(event_type: str, payload: dict, ts: datetime) -> None:
    event = Event(
        event_id=str(ULID()),
        ts_utc=ts,
        type=event_type,  # type: ignore[arg-type]
        actor="test:harness",
        run_id=None,
        schema_ver=1,
        payload=payload,
    )
    default_ledger().append(event)


def _seed_one_graded_trade() -> None:
    """A single graded, non-void, with-pnl thesis for ACCOUNT — enough for
    `_trade_log_for_account` to derive a non-empty `TradeRecord` log."""
    _append(
        "ThesisDrafted",
        {"thesis_id": "th-1", "contract": {"account_ref": ACCOUNT}},
        EPOCH,
    )
    # _trade_log_for_account skips (never guesses) a thesis missing its
    # SizingComputed or an entry marker — seed both so the derived log is
    # genuinely non-empty (CTO fixture fix after green-stage flag).
    _append(
        "SizingComputed",
        {"thesis_id": "th-1", "sizing": {"recommended_size_usd": "50"}},
        EPOCH + timedelta(hours=1),
    )
    _append(
        "ThesisSubmitted",
        {"thesis_id": "th-1"},
        EPOCH + timedelta(hours=2),
    )
    _append(
        "ThesisGraded",
        {
            "thesis_id": "th-1",
            "outcome": "PASS",
            "measured": [],
            "ambiguous_bar": False,
            "pnl_usd": "5.00",
            "graded_ts": (EPOCH + timedelta(days=1)).isoformat(),
        },
        EPOCH + timedelta(days=1),
    )


def test_metrics_error_propagates_with_nonempty_trade_log(monkeypatch) -> None:
    """CONTRACT (A2): a real trade log exists (non-empty), but
    `mae.compute_strategy_metrics` raises `ValueError` (e.g. a genuine data
    problem, not "too few trades") -> the error PROPAGATES, never silently
    becomes `None`.

    RED: current code is a bare `except ValueError: return None` with no
    `if trade_log: raise` narrowing -> this currently returns None instead
    of raising."""
    _seed_one_graded_trade()

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise ValueError("synthetic metrics compute failure")

    monkeypatch.setattr("tradekit.mae.compute_strategy_metrics", _raise)

    with pytest.raises(ValueError, match="synthetic metrics compute failure"):
        strategy_metrics_for_account(default_ledger(), ACCOUNT, PolicyDials())


def test_metrics_error_with_empty_trade_log_stays_none(monkeypatch) -> None:
    """CONTRACT (A2): NO graded trades on record (empty trade log) -> even
    though the call to `mae.compute_strategy_metrics` still happens (never
    short-circuited before the call — the monkeypatched seam is always
    exercised) and raises `ValueError`, the narrowed except swallows it into
    a clean `None` (insufficient_context, not a fabricated verdict).

    This assertion already matches the CURRENT (pre-narrowing) code — kept
    here as a no-regression companion pin: the narrowing must not flip this
    case to propagate too."""

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise ValueError("no trades to evaluate")

    monkeypatch.setattr("tradekit.mae.compute_strategy_metrics", _raise)

    result = strategy_metrics_for_account(default_ledger(), ACCOUNT, PolicyDials())
    assert result is None
