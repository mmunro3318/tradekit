"""`policy._series.maybe_close_series` — SeriesClosed EMISSION + idempotence
(sprint-doc addendum, SPRINT P3 batch E). Unconditional `NotImplementedError`
stub this batch (`_series.py`'s own docstring); every test below describes
REAL target behavior and is red for that reason alone (never wrapped in
`pytest.raises(NotImplementedError)`, same discipline as every other
red-phase file this sprint).

Scope note: `policy.promotion_status()` itself is UNTOUCHED by this batch —
it is already real and green (SPRINT P2 batch D), and wiring
`maybe_close_series` into its call graph is the dev pass's job (see
`_series.py`'s docstring). These tests call `maybe_close_series` DIRECTLY,
so the pre-existing `test_promotion.py`/`test_series.py` suites stay green
throughout this red phase.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ulid import ULID

from tradekit.contracts import Event, EventFilter
from tradekit.policy import _series
from tradekit.policy._dials import PolicyDials

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
DIALS = PolicyDials()
ACCOUNT = "paper:alpha"
_WINDOW_END = EPOCH + timedelta(days=30)


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


def _seed_ten_clean_graded(ledger) -> None:
    """10 graded theses, positive pnl, low MDD, no gate violations — a
    COMPLETE, CLEAN series 0 (mirrors `test_series.py`'s own "clean ten
    graded" fixture)."""
    for i in range(10):
        thesis_id = f"th-close-{i}"
        ledger.append(_drafted_event(thesis_id))
        ledger.append(_graded_event(thesis_id, EPOCH + timedelta(days=i), "10.00"))


def _series_closed_events(ledger) -> list[Event]:
    return [
        e
        for e in ledger.query(EventFilter(types=["SeriesClosed"]))
        if e.payload.get("account_ref") == ACCOUNT and e.payload.get("series_index") == 0
    ]


def test_closed_and_no_prior_event_appends_exactly_one_series_closed(ledger) -> None:
    _seed_ten_clean_graded(ledger)
    now = _WINDOW_END + timedelta(seconds=1)  # window closed

    event_id = _series.maybe_close_series(ledger, ACCOUNT, 0, DIALS, now)

    assert event_id is not None
    closed = _series_closed_events(ledger)
    assert len(closed) == 1
    assert closed[0].event_id == event_id
    payload = closed[0].payload
    assert payload["account_ref"] == ACCOUNT
    assert payload["series_index"] == 0
    assert payload["graded_count"] == 10
    assert payload["void_count"] == 0
    assert payload["gate_violations"] == 0
    assert payload["clean"] is True


def test_second_call_on_the_same_closed_window_does_not_duplicate(ledger) -> None:
    _seed_ten_clean_graded(ledger)
    now = _WINDOW_END + timedelta(seconds=1)

    first = _series.maybe_close_series(ledger, ACCOUNT, 0, DIALS, now)
    second = _series.maybe_close_series(ledger, ACCOUNT, 0, DIALS, now)

    assert first is not None
    assert second is None, "idempotent: a second call for an already-closed window is a no-op"
    assert len(_series_closed_events(ledger)) == 1


def test_window_not_yet_closed_is_a_noop(ledger) -> None:
    _seed_ten_clean_graded(ledger)
    now = _WINDOW_END - timedelta(seconds=1)  # still inside the window

    result = _series.maybe_close_series(ledger, ACCOUNT, 0, DIALS, now)

    assert result is None
    assert _series_closed_events(ledger) == []


def test_different_account_refs_get_independent_series_closed_events(ledger) -> None:
    _seed_ten_clean_graded(ledger)  # paper:alpha, series 0
    for i in range(10):
        thesis_id = f"th-beta-{i}"
        ledger.append(_drafted_event(thesis_id, account_ref="paper:beta"))
        ledger.append(_graded_event(thesis_id, EPOCH + timedelta(days=i), "10.00"))
    now = _WINDOW_END + timedelta(seconds=1)

    a = _series.maybe_close_series(ledger, "paper:alpha", 0, DIALS, now)
    b = _series.maybe_close_series(ledger, "paper:beta", 0, DIALS, now)

    assert a is not None
    assert b is not None
    assert a != b
