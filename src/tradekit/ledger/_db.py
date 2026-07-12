"""SQLite plumbing (DESIGN §6.2, TD-16): connect, migrate, retry, row mapping.

Timestamps are stored as fixed-width ISO-8601 UTC (microsecond precision) so
lexicographic comparison in SQL equals chronological comparison.
"""

from __future__ import annotations

import json
import random
import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tradekit.contracts import Event

# events + events_fts per the §6.2 DDL; seq assigned by SQLite.
_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS events (
      seq        INTEGER PRIMARY KEY,
      event_id   TEXT NOT NULL UNIQUE,
      ts_utc     TEXT NOT NULL,
      type       TEXT NOT NULL,
      actor      TEXT NOT NULL,
      run_id     TEXT,
      schema_ver INTEGER NOT NULL,
      payload    TEXT NOT NULL,
      prev_hash  TEXT NOT NULL,
      hash       TEXT NOT NULL
    )
    """,
    "CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(event_id, type, payload_text)",
)

# Bounded retry-with-jitter around lock contention (TD-16). busy_timeout
# absorbs most waits; this covers "database is locked" surfacing past it.
_MAX_ATTEMPTS = 5
_BASE_DELAY_S = 0.05
_MAX_DELAY_S = 0.5


def connect(db_path: Path) -> sqlite3.Connection:
    """Open (creating parents if needed) with WAL + busy_timeout + FKs on."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, isolation_level=None)  # explicit transactions only
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def migrate(con: sqlite3.Connection) -> None:
    """Idempotent creation of the source-of-truth tables (events + FTS)."""
    for statement in _SCHEMA:
        con.execute(statement)


def with_write_retry[T](fn: Callable[[], T]) -> T:
    """Run one short write transaction, retrying lock errors with capped
    exponential backoff + jitter (TD-16). Non-lock errors propagate."""
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            message = str(exc)
            is_lock = "locked" in message or "busy" in message
            if not is_lock or attempt == _MAX_ATTEMPTS - 1:
                raise
            delay = min(_MAX_DELAY_S, _BASE_DELAY_S * 2**attempt)
            time.sleep(delay + random.uniform(0.0, delay))
    raise AssertionError("unreachable: loop returns or raises")


def to_stored_ts(ts: datetime) -> str:
    """Fixed-width ISO-8601 in UTC — sortable as text, parseable back."""
    return ts.astimezone(UTC).isoformat(timespec="microseconds")


EVENT_COLUMNS = "event_id, ts_utc, type, actor, run_id, schema_ver, payload"


def row_to_event(row: tuple[Any, ...]) -> Event:
    """Reconstruct an Event from an EVENT_COLUMNS-ordered row."""
    event_id, ts_utc, type_, actor, run_id, schema_ver, payload = row
    return Event(
        event_id=event_id,
        ts_utc=datetime.fromisoformat(ts_utc),
        type=type_,
        actor=actor,
        run_id=run_id,
        schema_ver=schema_ver,
        payload=json.loads(payload),
    )
