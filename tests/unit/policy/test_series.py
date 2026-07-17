"""`policy._series` — series accounting (DESIGN §7.3; CTO addendum, story-4
pins). RED this batch — `_series.py` is entirely unconditional
`NotImplementedError` stubs (same discipline as `test_evaluate.py`/
`test_halt.py` in batch C's own red phase: assertions below describe the
REAL behavior the dev pass implements, so every test fails today with
`NotImplementedError`, not wrapped in `pytest.raises`).

FIXTURE-FREEZE: every Decimal/float literal below is copy-pasted verbatim
from `scratchpad/p2_batch_d_freeze_derivation.py`'s output (paste kept in
that file's own header) — nothing here is hand-computed at test-authoring
time. Equity base is `PolicyDials().paper_starting_equity_usd` (Decimal
"500"), zero realized pnl entering series_index=0 (first series, no prior
graded history for the account).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ulid import ULID

from tradekit.contracts import Event
from tradekit.policy import _series
from tradekit.policy._dials import PolicyDials

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
DIALS = PolicyDials()  # paper_starting_equity_usd == Decimal("500")
ACCOUNT = "paper:alpha"


# ---------------------------------------------------------------------------
# series_index — pure UTC calendar arithmetic (no ledger, no I/O)
# ---------------------------------------------------------------------------


def test_series_index_at_epoch_is_zero() -> None:
    assert _series.series_index(EPOCH, EPOCH) == 0, (
        "a grade timestamp exactly AT the epoch belongs to series 0 — the window is "
        "[epoch, epoch + 30d), left-closed"
    )


def test_series_index_one_second_before_epoch_is_negative_one() -> None:
    assert _series.series_index(EPOCH - timedelta(seconds=1), EPOCH) == -1, (
        "a grade timestamp one second before the epoch belongs to series -1 — "
        "floor((-1s) / 30d) == -1, not 0 (no rounding toward zero)"
    )


def test_series_index_at_epoch_plus_30d_exactly_is_one_not_zero() -> None:
    assert _series.series_index(EPOCH + timedelta(days=30), EPOCH) == 1, (
        "the CTO addendum's own boundary pin: 'grade at epoch+30d lands in series 1, "
        "not 0' — the window is right-open, [epoch + 30d*k, epoch + 30d*(k+1))"
    )


def test_series_index_one_second_before_epoch_plus_30d_is_still_zero() -> None:
    assert _series.series_index(EPOCH + timedelta(days=30) - timedelta(seconds=1), EPOCH) == 0, (
        "the last instant of series 0's window is 30d minus one second after epoch"
    )


def test_series_index_at_epoch_plus_60d_exactly_is_two() -> None:
    assert _series.series_index(EPOCH + timedelta(days=60), EPOCH) == 2, (
        "calendar-aligned 30-day blocks compound linearly — series 2 starts at "
        "epoch + 60d exactly (§7.3: 'fixed calendar-aligned 30-day blocks')"
    )


def test_series_index_is_pure_and_deterministic() -> None:
    ts = EPOCH + timedelta(days=47, hours=3, minutes=17)
    first = _series.series_index(ts, EPOCH)
    second = _series.series_index(ts, EPOCH)
    assert first == second == 1, "same inputs must always produce the same series index"


def test_window_for_round_trips_series_index_boundaries() -> None:
    start, end = _series.window_for(1, EPOCH)
    assert start == EPOCH + timedelta(days=30)
    assert end == EPOCH + timedelta(days=60)
    # The boundary instants must re-derive the SAME series index (round trip).
    assert _series.series_index(start, EPOCH) == 1
    assert _series.series_index(end - timedelta(seconds=1), EPOCH) == 1
    assert _series.series_index(end, EPOCH) == 2


# ---------------------------------------------------------------------------
# series_stats — derived from ThesisGraded/GateViolationDetected events
# ---------------------------------------------------------------------------


def _graded_event(thesis_id: str, ts: datetime, pnl: str | None, outcome: str = "PASS") -> Event:
    return Event(
        event_id=str(ULID()),
        ts_utc=ts,
        type="ThesisGraded",  # type: ignore[arg-type]
        actor="test:harness",
        run_id=None,
        schema_ver=1,
        payload={
            "thesis_id": thesis_id,
            "outcome": outcome,
            "measured": [],
            "ambiguous_bar": False,
            "pnl_usd": pnl,
            "graded_ts": ts.isoformat(),
        },
    )


def _drafted_event(thesis_id: str, account_ref: str = ACCOUNT) -> Event:
    return Event(
        event_id=str(ULID()),
        ts_utc=EPOCH,
        type="ThesisDrafted",  # type: ignore[arg-type]
        actor="test:harness",
        run_id=None,
        schema_ver=1,
        payload={"thesis_id": thesis_id, "contract": {"account_ref": account_ref}},
    )


def _gate_violation_event(ts: datetime, account_ref: str = ACCOUNT) -> Event:
    return Event(
        event_id=str(ULID()),
        ts_utc=ts,
        type="GateViolationDetected",  # type: ignore[arg-type]
        actor="test:harness",
        run_id=None,
        schema_ver=1,
        payload={
            "rule_id": "R-009",
            "account_ref": account_ref,
            "thesis_id": None,
            "measured": "0.11",
            "limit": "0.10",
            "why": "test-harness gate violation, in-window",
        },
    )


def _seed_series(ledger, pnls: list[str | None], *, outcome: str = "PASS") -> None:
    """Append one ThesisDrafted + ThesisGraded per pnl, spaced one day apart
    starting at EPOCH (series_index 0), graded_ts strictly increasing so the
    MDD walk order is unambiguous."""
    for i, pnl in enumerate(pnls):
        thesis_id = f"th-series-{i}"
        ledger.append(_drafted_event(thesis_id))
        ledger.append(_graded_event(thesis_id, EPOCH + timedelta(days=i), pnl, outcome=outcome))


NOW_WINDOW_CLOSED = EPOCH + timedelta(days=31)  # safely past series 0's window_end


def test_series_stats_expectancy_and_mdd_arithmetic_three_trade_freeze(ledger) -> None:
    """FIXTURE-FREEZE (scratchpad scenario 1): pnls +5.874, -2.10, +1.00.
    total = 4.774; expectancy = 4.774 / 3 = 1.5913333... (repeating).
    equity curve (base 500): 500 -> 505.874 -> 503.774 -> 504.774.
    peak sequence: 505.874, 505.874, 505.874 (never re-exceeded after trade 1).
    mdd_usd = 505.874 - 503.774 = 2.100.
    mdd_pct = 2.100 / 505.874 = 0.0041512313342848219121757591811399676599311290953874
            (~0.415123%)."""
    _seed_series(ledger, ["5.874", "-2.10", "1.00"])
    stats = _series.series_stats(ledger, ACCOUNT, 0, DIALS, NOW_WINDOW_CLOSED)
    assert stats.graded_count == 3
    assert stats.void_count == 0
    assert stats.expectancy == Decimal("4.774") / Decimal("3")
    assert stats.mdd_pct is not None
    assert abs(stats.mdd_pct - 0.0041512313342848219) < 1e-12
    # Only 3 graded (< 10) — incomplete regardless of the arithmetic above.
    assert stats.complete is False
    assert stats.clean is False


def test_series_stats_clean_ten_graded_positive_expectancy_low_mdd(ledger) -> None:
    """FIXTURE-FREEZE (scratchpad scenario 2): the same 3 pnls + 7 flat
    zero-pnl theses (real Decimal 0, not None). total = 4.774,
    expectancy = 4.774 / 10 = 0.4774. mdd_pct unchanged from scenario 1
    (0.00415...) since the trailing zeros never move the equity curve.
    Window closed, graded_count == 10, zero gate violations -> COMPLETE and
    CLEAN."""
    _seed_series(ledger, ["5.874", "-2.10", "1.00", "0", "0", "0", "0", "0", "0", "0"])
    stats = _series.series_stats(ledger, ACCOUNT, 0, DIALS, NOW_WINDOW_CLOSED)
    assert stats.graded_count == 10
    assert stats.expectancy == Decimal("0.4774")
    assert stats.mdd_pct is not None
    assert abs(stats.mdd_pct - 0.0041512313342848219) < 1e-12
    assert stats.gate_violations == 0
    assert stats.complete is True
    assert stats.clean is True


def test_series_stats_not_clean_when_mdd_pct_at_or_above_15_pct(ledger) -> None:
    """FIXTURE-FREEZE (scratchpad scenario 3): pnls +250, -130, +40, then 7
    zeros. expectancy = 160 / 10 = 16 (POSITIVE — isolates the mdd failure).
    equity curve: 500 -> 750 (peak) -> 620 -> 660 -> flat.
    mdd_usd = 750 - 620 = 130; mdd_pct = 130 / 750 = 0.173333...  (>= 0.15)."""
    _seed_series(ledger, ["250", "-130", "40", "0", "0", "0", "0", "0", "0", "0"])
    stats = _series.series_stats(ledger, ACCOUNT, 0, DIALS, NOW_WINDOW_CLOSED)
    assert stats.expectancy == Decimal("16")
    assert stats.mdd_pct is not None
    assert abs(stats.mdd_pct - 0.17333333333333334) < 1e-12
    assert stats.complete is True, "count/window criteria alone are satisfied"
    assert stats.clean is False, "mdd_pct 17.33% >= the 15% clean threshold"


def test_series_stats_not_clean_when_expectancy_not_positive(ledger) -> None:
    """FIXTURE-FREEZE (scratchpad scenario 4): ten -5.00 pnls. expectancy =
    -50 / 10 = -5 (<= 0). mdd_pct = 50 / 500 = 0.10 (< 0.15, isolates the
    expectancy failure)."""
    _seed_series(ledger, ["-5"] * 10)
    stats = _series.series_stats(ledger, ACCOUNT, 0, DIALS, NOW_WINDOW_CLOSED)
    assert stats.expectancy == Decimal("-5")
    assert stats.mdd_pct is not None
    assert abs(stats.mdd_pct - 0.1) < 1e-12
    assert stats.complete is True
    assert stats.clean is False, "expectancy -5 is not > 0"


def test_series_stats_zero_measured_pnl_theses_expectancy_is_none_and_not_clean(ledger) -> None:
    """ASSUMPTIONS 71's forward-pin, binding this batch: ten PASS/FAIL
    theses, every one graded with pnl_usd=None (no fills to account).
    expectancy must be None (never coerced to 0) — 'unmeasurable != clean',
    anti-permissive. graded_count still counts all ten (None-pnl exclusion
    is from the EXPECTANCY aggregation only, not from the tally)."""
    _seed_series(ledger, [None] * 10)
    stats = _series.series_stats(ledger, ACCOUNT, 0, DIALS, NOW_WINDOW_CLOSED)
    assert stats.graded_count == 10, "None-pnl theses still count toward graded/non-void tallies"
    assert stats.expectancy is None, (
        "zero measured pnl in-window -> expectancy is None, never a fabricated 0 "
        "(ASSUMPTIONS 71's forward-pin)"
    )
    assert stats.complete is True, "count/window criteria are satisfied regardless of pnl"
    assert stats.clean is False, (
        "expectancy is None -> NOT clean, even though 'zero gate violations' and 'mdd < 15%' "
        "both hold vacuously — unmeasurable is not the same fact as clean (anti-permissive)"
    )


def test_series_stats_gate_violation_in_window_is_not_clean(ledger) -> None:
    """Same 10-thesis fixture as the CLEAN test above, plus one
    GateViolationDetected timestamped inside the window — isolates the
    gate-violation failure (expectancy/mdd both still pass)."""
    _seed_series(ledger, ["5.874", "-2.10", "1.00", "0", "0", "0", "0", "0", "0", "0"])
    ledger.append(_gate_violation_event(EPOCH + timedelta(days=5)))
    stats = _series.series_stats(ledger, ACCOUNT, 0, DIALS, NOW_WINDOW_CLOSED)
    assert stats.gate_violations == 1
    assert stats.complete is True
    assert stats.clean is False, "any in-window GateViolationDetected forbids 'clean'"


def test_series_stats_void_excluded_from_graded_count(ledger) -> None:
    """A VOID outcome is neither PASS nor FAIL: it must NOT count toward
    graded_count (the >=10 completeness threshold), but it DOES bump
    void_count (§7.2's R-015 void-rate audit reads this same tally)."""
    _seed_series(ledger, ["1"] * 9, outcome="PASS")
    _seed_series(ledger, ["0"], outcome="VOID")
    stats = _series.series_stats(ledger, ACCOUNT, 0, DIALS, NOW_WINDOW_CLOSED)
    assert stats.graded_count == 9, "the VOID thesis must not count toward graded_count"
    assert stats.void_count == 1
    assert stats.complete is False, "9 non-void graded is one short of the >=10 floor"


def test_series_stats_nine_graded_is_incomplete_boundary(ledger) -> None:
    """FIXTURE-FREEZE (scratchpad scenario 5): nine +1.00 pnls, window
    closed. graded_count == 9 -> incomplete regardless of otherwise-clean
    arithmetic (expectancy 1, mdd 0%)."""
    _seed_series(ledger, ["1"] * 9)
    stats = _series.series_stats(ledger, ACCOUNT, 0, DIALS, NOW_WINDOW_CLOSED)
    assert stats.graded_count == 9
    assert stats.complete is False
    assert stats.clean is False, "clean requires complete; 9 < 10 fails completeness alone"


def test_series_stats_ten_graded_is_complete_boundary(ledger) -> None:
    """Ten graded non-void, window closed -> complete boundary crossed
    exactly at 10 (reuses scenario 2's clean fixture)."""
    _seed_series(ledger, ["5.874", "-2.10", "1.00", "0", "0", "0", "0", "0", "0", "0"])
    stats = _series.series_stats(ledger, ACCOUNT, 0, DIALS, NOW_WINDOW_CLOSED)
    assert stats.graded_count == 10
    assert stats.complete is True


def test_series_stats_window_not_yet_closed_is_incomplete_regardless_of_count(ledger) -> None:
    """Ten graded non-void theses (would otherwise be complete+clean), but
    `now` is still INSIDE the window (window_end not yet reached) ->
    incomplete regardless of count (CTO addendum: 'a window not yet closed
    is ALWAYS incomplete, regardless of count')."""
    _seed_series(ledger, ["5.874", "-2.10", "1.00", "0", "0", "0", "0", "0", "0", "0"])
    now_inside_window = EPOCH + timedelta(days=9)  # last graded event is at EPOCH + 9d
    stats = _series.series_stats(ledger, ACCOUNT, 0, DIALS, now_inside_window)
    assert stats.graded_count == 10
    assert stats.complete is False, "window_end (EPOCH + 30d) has not yet been reached"
    assert stats.clean is False


def test_series_stats_scoped_to_account_ref(ledger) -> None:
    """A different account_ref's graded theses in the SAME calendar window
    must never leak into this account's stats."""
    _seed_series(ledger, ["1"] * 10)  # account "paper:alpha", the module default
    for i in range(10):
        thesis_id = f"th-other-{i}"
        ledger.append(_drafted_event(thesis_id, account_ref="paper:beta"))
        ledger.append(_graded_event(thesis_id, EPOCH + timedelta(days=i), "999"))
    stats = _series.series_stats(ledger, ACCOUNT, 0, DIALS, NOW_WINDOW_CLOSED)
    assert stats.graded_count == 10, "only paper:alpha's ten theses should be counted"
    assert stats.expectancy == Decimal("1"), "paper:beta's pnl must never leak into this mean"
