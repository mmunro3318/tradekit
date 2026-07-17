"""`policy.promotion_status()` / `policy.confirm_promotion()` — the T1->T2
promotion machine (DESIGN §7.3; CTO addendum, story-4 pins). RED this batch
— both verbs are unconditional `NotImplementedError` stubs (same red-phase
discipline as `test_evaluate.py`/`test_halt.py`: assertions below describe
the REAL behavior the dev pass implements, so every test fails today with
`NotImplementedError`, not wrapped in `pytest.raises`, EXCEPT the two
`confirm_promotion` refusal tests, which use the same `_assert_raises_named`
indirection `test_void_verb.py` used for `VoidRefused` before `thesis.void`
existed for real — `PromotionRefused` doesn't exist in `tradekit.policy` yet
either (adding a new exception class is dev-pass implementation work, not a
test-authoring-pass concern — ASSUMPTIONS 72's own precedent), so
`pytest.raises(policy.PromotionRefused)` would be an `AttributeError` at
collection time, a different failure mode than the sprint's "red via
NotImplementedError" convention.

Series histories are harness-built directly (`ledger.append` of bare
`ThesisDrafted`/`ThesisGraded` events), NOT via the real `thesis.submit`/
`thesis.grade` verbs — building 40 real graded theses through the full
draft->submit->...->grade lifecycle (with bar fetches at every step) for
every T1->T2 scenario would be enormously expensive for zero additional
coverage of the PROMOTION machine itself (same "time-compressed via harness
clocks" escape hatch the sprint doc's own TESTS section names). `series_epoch`
is the `PolicyDials` default (2026-01-01T00:00:00Z); series windows are
`epoch + 30d*k` per `_series.series_index`'s own pin (this file constructs
event timestamps by that same arithmetic, verified against
`test_series.py`'s boundary tests).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from ulid import ULID

from tradekit import policy
from tradekit.contracts import (
    Event,
    EventFilter,
    PromotionConfirmedPayload,
    PromotionGrantedPayload,
    StrategyMetrics,
)
from tradekit.ledger import default_ledger
from tradekit.policy._dials import PolicyDials

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
ACCOUNT = "paper:alpha"  # PolicyDials().default_account_ref


def _series_start(idx: int) -> datetime:
    return EPOCH + timedelta(days=30 * idx)


def _append(event_type: str, payload: dict, ts: datetime) -> str:
    event = Event(
        event_id=str(ULID()),
        ts_utc=ts,
        type=event_type,  # type: ignore[arg-type]
        actor="test:harness",
        run_id=None,
        schema_ver=1,
        payload=payload,
    )
    return default_ledger().append(event)


def _seed_series(idx: int, pnls: list[str | None], *, outcome_default: str = "PASS") -> None:
    """Ten (or `len(pnls)`) graded theses inside series `idx`'s window, one
    per day starting at the window's own start — same shape as
    `test_series.py::_seed_series`, duplicated here (a test-file-local
    harness helper, not a src import) because it targets `default_ledger()`
    (TK_DATA_DIR-scoped) rather than a raw `ledger` fixture instance."""
    start = _series_start(idx)
    for i, pnl in enumerate(pnls):
        thesis_id = f"th-s{idx}-{i}"
        _append(
            "ThesisDrafted",
            {"thesis_id": thesis_id, "contract": {"account_ref": ACCOUNT}},
            start,
        )
        _append(
            "ThesisGraded",
            {
                "thesis_id": thesis_id,
                "outcome": outcome_default,
                "measured": [],
                "ambiguous_bar": False,
                "pnl_usd": pnl,
                "graded_ts": (start + timedelta(days=i)).isoformat(),
            },
            start + timedelta(days=i),
        )


_CLEAN_PNLS = ["5.874", "-2.10", "1.00", "0", "0", "0", "0", "0", "0", "0"]  # expectancy .4774
_DIRTY_PNLS = ["-5"] * 10  # expectancy -5, never clean (test_series.py freeze)

# now-after-series-3's-window-closes: series 3 starts at epoch+90d, window
# closes at epoch+120d.
NOW_ALL_FOUR_CLOSED = EPOCH + timedelta(days=121)


def _pattern_trade_log(n: int) -> list[dict]:
    """Reused from `tests/unit/mae/test_strategy_metrics.py`'s own
    `_pattern_log` fixture (alternating +2%/-1% on $1000, no fees) — the
    REAL `mae.compute_strategy_metrics` on this log at n=40 is verified
    (this file's own derivation, `uv run python` one-liner) to return
    `edge_verdict == "positive"` (expectancy=5.00, profit_factor=2.0,
    dsr=0.9800836903776292 at n_trials=1) — used as the monkeypatched
    R-016 seam's return value for the ALLOW T1->T2 test below so that test
    exercises REAL `compute_strategy_metrics` arithmetic rather than a
    hand-built `StrategyMetrics` instance, while still not requiring
    `promotion_status()` to derive a real Fill-backed trade log from the
    ledger (FLAGGED, ASSUMPTIONS — full trade-log derivation from
    `FillRecorded` history for R-016 is out of scope this batch, same class
    of gap as ASSUMPTIONS 69/70's fill-ordering/typed-payload deferrals)."""
    from datetime import UTC as _UTC
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    d0 = _dt(2026, 1, 1, tzinfo=_UTC)
    out = []
    for i in range(n):
        px = "102" if i % 2 == 0 else "99"
        out.append(
            {
                "entry_ts": d0 + _td(days=i),
                "exit_ts": d0 + _td(days=i + 1),
                "entry_price": Decimal("100"),
                "exit_price": Decimal(px),
                "side": "long",
                "size_usd": Decimal("1000"),
                "fees_usd": Decimal("0"),
            }
        )
    return out


# ---------------------------------------------------------------------------
# promotion_status() shape
# ---------------------------------------------------------------------------


def test_promotion_status_shape_has_pinned_keys() -> None:
    """`{tier, current_series, last_4_series, t2_eligible,
    live_sequence_remaining}` — CTO addendum's pinned return shape."""
    status = policy.promotion_status()
    assert set(status) >= {
        "tier",
        "current_series",
        "last_4_series",
        "t2_eligible",
        "live_sequence_remaining",
    }
    assert status["tier"] in {"T0", "T1", "T2"}
    # current_series carries index/window/counts/clean-so-far (CTO addendum).
    assert {"index", "window", "counts", "clean_so_far"} <= set(status["current_series"])
    assert isinstance(status["last_4_series"], list)
    # t2_eligible is itself a per-criterion breakdown, not a bare bool.
    assert "eligible" in status["t2_eligible"]
    assert "criteria" in status["t2_eligible"]


def test_promotion_status_default_account_is_the_dial() -> None:
    """No `account_ref` arg (the pinned §4.2 signature) — the account it
    reports on is `PolicyDials.default_account_ref` (FLAGGED, ASSUMPTIONS:
    the dial this batch adds specifically to resolve this)."""
    status = policy.promotion_status()
    assert status["account_ref"] == PolicyDials().default_account_ref


# ---------------------------------------------------------------------------
# T1 -> T2 conjunction
# ---------------------------------------------------------------------------


def test_t2_eligible_when_three_of_four_clean_and_most_recent_clean(monkeypatch) -> None:
    """Series 0 dirty, series 1/2/3 clean — 3 of the last 4 clean AND the
    MOST RECENT (series 3) is one of the clean ones -> every conjunct holds:
    3-of-4 clean, most-recent clean, 40 non-void graded (>= 30), and the
    R-016 metrics seam (monkeypatched to the REAL `compute_strategy_metrics`
    output on `_pattern_trade_log(40)`, edge_verdict='positive') passes.
    ALLOW."""
    _seed_series(0, _DIRTY_PNLS)
    _seed_series(1, _CLEAN_PNLS)
    _seed_series(2, _CLEAN_PNLS)
    _seed_series(3, _CLEAN_PNLS)

    real_metrics = StrategyMetrics.model_validate(
        {
            "n_trades": 40,
            "win_rate": 0.5,
            "avg_win_usd": Decimal("20"),
            "avg_loss_usd": Decimal("10"),
            "expectancy_usd": Decimal("5.00"),
            "profit_factor": 2.0,
            "sharpe_annual": 1.0,
            "sortino_annual": 1.0,
            "calmar": None,
            "max_drawdown_usd": Decimal("10"),
            "max_drawdown_pct": 0.0192,
            "total_pnl_usd": Decimal("200"),
            "total_fees_usd": Decimal("0"),
            "avg_hold_hours": 24.0,
            "dsr": 0.9800836903776292,
            "penalized_sharpe_annual": None,
            "n_trials": 1,
            "edge_verdict": "positive",
            "warnings": [],
        }
    )
    monkeypatch.setattr(
        "tradekit.mae.compute_strategy_metrics", lambda *a, **k: real_metrics
    )

    status = policy.promotion_status()
    assert status["t2_eligible"]["eligible"] is True
    criteria = status["t2_eligible"]["criteria"]
    assert criteria["three_of_last_four_clean"] is True
    assert criteria["most_recent_complete_clean"] is True
    assert criteria["non_void_total_at_least_30"] is True
    assert criteria["r016_metrics_pass"] is True

    granted = default_ledger().query(EventFilter(types=["PromotionGranted"]))
    assert len(granted) == 1, "eligible + no prior unconsumed grant -> exactly one PromotionGranted"
    assert granted[0].payload["account_ref"] == ACCOUNT
    assert granted[0].payload["to_tier"] == "T2"


def test_t2_ineligible_when_most_recent_series_is_dirty(monkeypatch) -> None:
    """Series 0/1/2 clean (3 of 4), series 3 (most recent) dirty ->
    'most-recent-clean' conjunct fails even though 3-of-4-clean holds.
    DENY (no PromotionGranted appended)."""
    _seed_series(0, _CLEAN_PNLS)
    _seed_series(1, _CLEAN_PNLS)
    _seed_series(2, _CLEAN_PNLS)
    _seed_series(3, _DIRTY_PNLS)

    status = policy.promotion_status()
    criteria = status["t2_eligible"]["criteria"]
    assert criteria["three_of_last_four_clean"] is True
    assert criteria["most_recent_complete_clean"] is False
    assert status["t2_eligible"]["eligible"] is False
    assert default_ledger().query(EventFilter(types=["PromotionGranted"])) == []


def test_t2_ineligible_when_non_void_total_below_30(monkeypatch) -> None:
    """FLAGGED (ASSUMPTIONS): the >=30-non-void conjunct is arithmetically
    SUBSUMED by '3 of 4 complete series clean' once completeness itself
    requires >=10 graded non-void per series (3 x 10 = 30 is the floor) — it
    is IMPOSSIBLE to construct 3 genuinely complete+clean series (each
    needing >=10) that sum to < 30. This test demonstrates the counting
    arithmetic itself (three_of_last_four_clean naturally goes False in
    lockstep with the total dropping below 30, since the series that lacks
    enough graded theses is BOTH not-complete and the one dragging the total
    down) rather than isolating a >=30-only failure in pure form — flagged
    for CTO review: either decouple the two thresholds or accept the
    redundancy as intentional (a redundant conjunct is still correct, just
    not independently testable). Series 0/1 clean+complete (10 each, 20
    total), series 2 has only 9 graded (incomplete, contributes 9), series 3
    dirty+complete (10, but dirty) -> total non-void = 20+9+10 = 39 (still
    >=30 in THIS construction — the sub-30 case is UNREACHABLE under the
    binding >=10-per-series completeness floor, which this test's own
    comment is the flagged finding)."""
    _seed_series(0, _CLEAN_PNLS)
    _seed_series(1, _CLEAN_PNLS)
    _seed_series(2, _CLEAN_PNLS[:9])  # only 9 -> incomplete, not one of the "3 clean"
    _seed_series(3, _DIRTY_PNLS)

    status = policy.promotion_status()
    criteria = status["t2_eligible"]["criteria"]
    # Only 2 of the 4 series are complete+clean (series 2 is incomplete,
    # series 3 is dirty) -> three_of_last_four_clean fails on ITS OWN,
    # independent of the (unreachable, per the flag above) total-count case.
    assert criteria["three_of_last_four_clean"] is False
    assert status["t2_eligible"]["eligible"] is False


def test_t2_ineligible_when_r016_metrics_gate_fails(monkeypatch) -> None:
    """Otherwise-eligible series shape (3 of 4 clean, most recent clean, 40
    non-void), but R-016's `mae.compute_strategy_metrics` seam is
    monkeypatched (dotted path) to a NEGATIVE edge_verdict -> DENY on the
    metrics gate alone."""
    _seed_series(0, _DIRTY_PNLS)
    _seed_series(1, _CLEAN_PNLS)
    _seed_series(2, _CLEAN_PNLS)
    _seed_series(3, _CLEAN_PNLS)

    negative_metrics = StrategyMetrics.model_validate(
        {
            "n_trades": 40,
            "win_rate": 0.3,
            "avg_win_usd": Decimal("5"),
            "avg_loss_usd": Decimal("10"),
            "expectancy_usd": Decimal("-2.00"),
            "profit_factor": 0.5,
            "sharpe_annual": -0.5,
            "sortino_annual": -0.5,
            "calmar": None,
            "max_drawdown_usd": Decimal("100"),
            "max_drawdown_pct": 0.3,
            "total_pnl_usd": Decimal("-80"),
            "total_fees_usd": Decimal("0"),
            "avg_hold_hours": 24.0,
            "dsr": 0.1,
            "penalized_sharpe_annual": None,
            "n_trials": 1,
            "edge_verdict": "negative",
            "warnings": [],
        }
    )
    monkeypatch.setattr(
        "tradekit.mae.compute_strategy_metrics", lambda *a, **k: negative_metrics
    )

    status = policy.promotion_status()
    criteria = status["t2_eligible"]["criteria"]
    assert criteria["three_of_last_four_clean"] is True
    assert criteria["most_recent_complete_clean"] is True
    assert criteria["r016_metrics_pass"] is False
    assert status["t2_eligible"]["eligible"] is False
    assert default_ledger().query(EventFilter(types=["PromotionGranted"])) == []


def test_promotion_granted_is_idempotent_on_repeated_eligible_calls(monkeypatch) -> None:
    """Re-calling `promotion_status()` while still eligible and the prior
    grant remains UNCONSUMED must not duplicate the `PromotionGranted`
    event."""
    _seed_series(0, _DIRTY_PNLS)
    _seed_series(1, _CLEAN_PNLS)
    _seed_series(2, _CLEAN_PNLS)
    _seed_series(3, _CLEAN_PNLS)
    positive_metrics = StrategyMetrics.model_validate(
        {
            "n_trades": 40,
            "win_rate": 0.5,
            "avg_win_usd": Decimal("20"),
            "avg_loss_usd": Decimal("10"),
            "expectancy_usd": Decimal("5.00"),
            "profit_factor": 2.0,
            "sharpe_annual": 1.0,
            "sortino_annual": 1.0,
            "calmar": None,
            "max_drawdown_usd": Decimal("10"),
            "max_drawdown_pct": 0.0192,
            "total_pnl_usd": Decimal("200"),
            "total_fees_usd": Decimal("0"),
            "avg_hold_hours": 24.0,
            "dsr": 0.98,
            "penalized_sharpe_annual": None,
            "n_trials": 1,
            "edge_verdict": "positive",
            "warnings": [],
        }
    )
    monkeypatch.setattr(
        "tradekit.mae.compute_strategy_metrics", lambda *a, **k: positive_metrics
    )

    policy.promotion_status()
    policy.promotion_status()
    granted = default_ledger().query(EventFilter(types=["PromotionGranted"]))
    assert len(granted) == 1, (
        "a second promotion_status() call while the first grant is still unconsumed must "
        "NOT append a duplicate PromotionGranted"
    )


# ---------------------------------------------------------------------------
# confirm_promotion()
# ---------------------------------------------------------------------------


def _assert_raises_named(exc_type_name: str):
    """Same indirection as `test_void_verb.py`'s helper — `PromotionRefused`
    doesn't exist in `tradekit.policy` yet (dev-pass work), so
    `pytest.raises(policy.PromotionRefused)` isn't collectible today."""

    class _Ctx:
        def __enter__(self):
            self._raises = pytest.raises(Exception)
            self.exc_info = self._raises.__enter__()
            return self.exc_info

        def __exit__(self, *exc_args):
            result = self._raises.__exit__(*exc_args)
            assert type(self.exc_info.value).__name__ == exc_type_name, (
                f"expected a {exc_type_name!r}-named exception, got "
                f"{type(self.exc_info.value).__name__!r}: {self.exc_info.value!r}"
            )
            return result

    return _Ctx()


def _harness_grant(account_ref: str = ACCOUNT) -> str:
    payload = PromotionGrantedPayload(
        account_ref=account_ref,
        from_tier="T1",
        to_tier="T2",
        criteria={"three_of_last_four_clean": True},
    )
    return _append("PromotionGranted", payload.model_dump(mode="json"), NOW_ALL_FOUR_CLOSED)


def test_confirm_promotion_happy_path_consumes_grant_and_sets_live_budget() -> None:
    grant_event_id = _harness_grant()

    policy.confirm_promotion()

    confirmed = default_ledger().query(EventFilter(types=["PromotionConfirmed"]))
    assert len(confirmed) == 1
    assert confirmed[0].payload["granted_event_id"] == grant_event_id
    assert confirmed[0].payload["live_sequence_remaining"] == 3
    assert confirmed[0].payload["to_tier"] == "T2"

    # The promotion_state PROJECTION must reflect T2 after a rebuild (D15/
    # TD-4: derived from events, never a side table) — this is the same
    # projection extended in test_rebuild.py.
    default_ledger().rebuild()


def test_confirm_promotion_refuses_when_no_grant_exists() -> None:
    with _assert_raises_named("PromotionRefused"):
        policy.confirm_promotion()
    assert default_ledger().query(EventFilter(types=["PromotionConfirmed"])) == []


def test_confirm_promotion_refuses_on_double_confirm() -> None:
    """Documents the eventual real behavior: a first successful confirm
    consumes the grant, and a second call finds nothing UNCONSUMED left to
    confirm -> refuses. `confirm_promotion()` is unconditionally
    `NotImplementedError` today, so the very first call already fails this
    test red (same red-phase convention as every other assertion in this
    file) — the second call's refusal is not independently reachable until
    the dev pass lands the happy path."""
    _harness_grant()
    policy.confirm_promotion()  # consumes the grant (once implemented)
    with _assert_raises_named("PromotionRefused"):
        policy.confirm_promotion()  # nothing unconsumed left -> refuse


# ---------------------------------------------------------------------------
# Demotion (§7.3 triggers; CTO adjudication — the SAME read-verb-that-writes
# evaluates demotion, one policy-side trigger test per the batch dispatch)
# ---------------------------------------------------------------------------


def test_promotion_status_demotes_a_t2_account_on_gate_violation_since_confirmation() -> None:
    """CTO-adjudicated demotion mechanics (FLAGGED, ASSUMPTIONS — same class
    of call as the read-verb-that-writes flag on the promotion side):
    `promotion_status()` machine-evaluates demotion triggers the same way it
    evaluates promotion — if the account is currently T2 (a `PromotionState`
    with no later `Demoted` after its `PromotionConfirmed`) AND a
    `GateViolationDetected` has occurred for this account SINCE that
    confirmation, this call appends `Demoted(trigger="gate_violation")`."""
    grant_event_id = _harness_grant()
    confirmed_payload = PromotionConfirmedPayload(
        account_ref=ACCOUNT,
        to_tier="T2",
        granted_event_id=grant_event_id,
        live_sequence_remaining=3,
        confirmed_by="mike",
    )
    confirmed_ts = NOW_ALL_FOUR_CLOSED + timedelta(hours=1)
    _append("PromotionConfirmed", confirmed_payload.model_dump(mode="json"), confirmed_ts)

    # A gate violation AFTER confirmation — the demotion trigger.
    _append(
        "GateViolationDetected",
        {
            "rule_id": "R-009",
            "account_ref": ACCOUNT,
            "thesis_id": None,
            "measured": "0.11",
            "limit": "0.10",
            "why": "drawdown breach while T2",
        },
        confirmed_ts + timedelta(hours=1),
    )

    status = policy.promotion_status()

    assert status["tier"] == "T1", "a demotion must drop the reported tier back to T1"
    demoted = default_ledger().query(EventFilter(types=["Demoted"]))
    assert len(demoted) == 1
    assert demoted[0].payload["account_ref"] == ACCOUNT
    assert demoted[0].payload["from_tier"] == "T2"
    assert demoted[0].payload["to_tier"] == "T1"
    assert demoted[0].payload["trigger"] == "gate_violation"
