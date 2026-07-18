"""tradekit.memory — DESIGN §11/§4.2 deep module (TD-20).

Deep interface: `brief() -> str`, `search(query, k=10) -> list[dict]`,
`record_lesson(note, salience) -> str` (event_id). Internals `_brief.py`
(token-budgeted markdown assembly), `_search.py` (FTS + wiki), `_wiki.py`
(`tk wiki add`'s file writer) — never re-exported here (DESIGN §1).

Status (SPRINT P3 batch E, TDD red phase): `record_lesson` is REAL this
batch — a producer-side contract validate + one ledger append, same
"contracts are cheap" precedent as every other batch's declarative verbs
(`broker.create_paper_account`, `policy._rules`/`_dials`). `brief()`/
`search()` are thin delegates to `_brief.render`/`_search.search`, both
unconditional `NotImplementedError` stubs (`tests/unit/memory/`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ulid import ULID

from tradekit.contracts import Event, LessonRecordedPayload
from tradekit.ledger import default_ledger
from tradekit.memory import _brief, _search
from tradekit.policy._dials import PolicyDials

_ACTOR = "system:memory"


def _clock() -> datetime:
    """Module-attribute clock seam (house convention — same pattern as
    `tradekit.policy._context._clock`/`tradekit.mae._runtime._clock`):
    tests monkeypatch `"tradekit.memory._clock"` by dotted string path,
    never a bound-at-import-time reference."""
    return datetime.now(UTC)


def brief() -> str:
    """`tk brief` — token-budgeted markdown session-opening brief (DESIGN
    §11); thin dispatch to `_brief.render`."""
    ledger = default_ledger()
    dials = PolicyDials.load()
    return _brief.render(ledger, dials, _clock())


def search(query: str, k: int = 10) -> list[dict[str, Any]]:
    """`tk search "<query>"` — ledger FTS + wiki front-matter, implicit-AND
    / quoted-phrase semantics (DESIGN §11, ASSUMPTIONS round-21); thin
    dispatch to `_search.search`."""
    ledger = default_ledger()
    dials = PolicyDials.load()
    return _search.search(ledger, dials.wiki_dir, query, k)


def record_lesson(note: str, salience: int) -> str:
    """`record_lesson(note, salience) -> LessonRecorded` event_id (DESIGN
    §11: "record_lesson ledgers a pointer event so lessons are replayable
    too"). `salience` validated 1..5 by `contracts.LessonRecordedPayload`
    itself (a Pydantic `ValidationError` on an out-of-range value, same
    "validate through the model" convention as every other producer-side
    payload in this codebase)."""
    ledger = default_ledger()
    payload = LessonRecordedPayload(note=note, salience=salience)
    event = Event(
        event_id=str(ULID()),
        ts_utc=_clock(),
        type="LessonRecorded",
        actor=_ACTOR,
        run_id=None,
        schema_ver=1,
        payload=payload.model_dump(mode="json"),
    )
    return ledger.append(event)


__all__ = ["brief", "record_lesson", "search"]
