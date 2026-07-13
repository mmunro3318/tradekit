"""Ledger.query + Ledger.search (DESIGN §6, TD-20).

Timestamps are chosen so the range filter's boundary semantics (inclusive vs
exclusive) can't change the outcome — only field EXISTENCE is pinned here; the
inclusivity convention is an ASSUMPTIONS.md item.
"""

from datetime import UTC, datetime

import pytest

from tradekit.contracts import EventFilter
from tradekit.ledger import Ledger  # noqa: F401 — collection gate for the module

T10 = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
T11 = datetime(2026, 1, 1, 11, 0, tzinfo=UTC)
T12 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def populated_ids(ledger, make_event) -> list[str]:
    """Three events: ThesisDrafted@10:00, LessonRecorded@11:00, ThesisDrafted@12:00."""
    return [
        ledger.append(make_event(type="ThesisDrafted", ts=T10, payload={"thesis_id": "T-1"})),
        ledger.append(
            make_event(
                type="LessonRecorded",
                ts=T11,
                payload={"note": "watch the quetzalcoatl divergence on weekends", "salience": 2},
            )
        ),
        ledger.append(make_event(type="ThesisDrafted", ts=T12, payload={"thesis_id": "T-2"})),
    ]


def test_query_filters_by_type(ledger, populated_ids) -> None:
    result = ledger.query(EventFilter(types=["ThesisDrafted"]))
    got = [e.event_id for e in result]
    assert got == [populated_ids[0], populated_ids[2]], (
        f"got {got}: type filter must return exactly the two ThesisDrafted events, in seq "
        "order — over-matching pollutes projections, wrong order breaks replay (§6)"
    )


def test_query_filters_by_time_range(ledger, populated_ids) -> None:
    result = ledger.query(
        EventFilter(
            since=datetime(2026, 1, 1, 10, 30, tzinfo=UTC),
            until=datetime(2026, 1, 1, 11, 30, tzinfo=UTC),
        )
    )
    got = [e.event_id for e in result]
    assert got == [populated_ids[1]], (
        f"got {got}: a 10:30-11:30 window strictly contains only the 11:00 event — "
        "time-range queries drive grading sweeps and series accounting (§10.2, TD-10)"
    )


def test_empty_filter_returns_everything_in_seq_order(ledger, populated_ids) -> None:
    got = [e.event_id for e in ledger.query(EventFilter())]
    assert got == populated_ids, (
        f"got {got}, expected all three in append order: the empty filter is the full "
        "replay path — missing or reordered events make rebuild() lie (§6.1)"
    )


def test_search_finds_distinctive_payload_word(ledger, populated_ids) -> None:
    hits = ledger.search("quetzalcoatl")
    assert populated_ids[1] in [e.event_id for e in hits], (
        "FTS5 search failed to reach payload text: tk search / memory recall depend on "
        "payload indexing, not just type/id columns (TD-20, §6.2 events_fts)"
    )


def test_search_no_match_returns_empty_list(ledger, populated_ids) -> None:
    assert ledger.search("zxqvbn-no-such-token") == [], (
        "no-match must be an empty list, not an exception — agents call search "
        "speculatively every session (§11 brief/search flow)"
    )


@pytest.mark.parametrize("hostile", ['AND (', 'quetzalcoatl" OR "x', "NEAR(a b)", "*"])
def test_search_treats_input_as_text_not_query_syntax(ledger, populated_ids, hostile) -> None:
    result = ledger.search(hostile)
    assert isinstance(result, list), (
        f"search({hostile!r}) must treat input as a text value, never FTS5 query syntax "
        "(ASSUMPTIONS 17) — agents pass arbitrary strings here every session"
    )


def test_event_filter_rejects_naive_datetimes() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EventFilter(since=datetime(2026, 1, 1, 10, 30))
    # A naive bound would be read as machine-local time and silently shift the
    # window — grading sweeps and series accounting ride these filters
    # (TD-17, reviewer D2, ASSUMPTIONS 20).
