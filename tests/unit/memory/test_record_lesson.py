"""`memory.record_lesson(note, salience) -> LessonRecorded` (DESIGN §11).
REAL this batch (contract-validate + one ledger append — see
`memory/__init__.py`'s own docstring for the "cheap" precedent) — every
test below is GREEN, pinning the already-real behavior.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tradekit import memory
from tradekit.contracts import EventFilter


def test_record_lesson_appends_a_lesson_recorded_event(ledger) -> None:
    event_id = memory.record_lesson("R-009 trips reliably at -10% trailing 30d", salience=4)

    events = ledger.query(EventFilter(types=["LessonRecorded"]))
    assert len(events) == 1
    assert events[0].event_id == event_id
    assert events[0].payload["note"] == "R-009 trips reliably at -10% trailing 30d"
    assert events[0].payload["salience"] == 4


@pytest.mark.parametrize("salience", [0, 6, -1])
def test_record_lesson_rejects_out_of_range_salience(ledger, salience: int) -> None:
    with pytest.raises(ValidationError):
        memory.record_lesson("some note", salience=salience)


def test_record_lesson_rejects_empty_note(ledger) -> None:
    with pytest.raises(ValidationError):
        memory.record_lesson("", salience=3)
