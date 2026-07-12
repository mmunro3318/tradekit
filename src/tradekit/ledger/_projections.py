"""Read-model projections (DESIGN §6.1/§6.2): disposable caches derived from
events. NEVER writes the events table — rebuild derives FROM it only.

P0 projections: ``runs`` (one row per RunStarted, D15 experiment registry)
and ``config_versions`` (from ConfigChanged). The rest of the §6.2 read-model
list lands with its producing subsystems.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from tradekit.contracts import Event
from tradekit.ledger._db import to_stored_ts

_TABLES: dict[str, str] = {
    "runs": """
        CREATE TABLE IF NOT EXISTS runs (
          run_id         TEXT PRIMARY KEY,
          started_ts     TEXT NOT NULL,
          model          TEXT,
          framework      TEXT,
          prompt_sha256  TEXT,
          config_version INTEGER
        )
    """,
    "config_versions": """
        CREATE TABLE IF NOT EXISTS config_versions (
          config_version INTEGER,
          changed_ts     TEXT NOT NULL,
          actor          TEXT NOT NULL
        )
    """,
}


def ensure_tables(con: sqlite3.Connection) -> None:
    """Create projection tables if absent — a fresh ledger has them empty."""
    for ddl in _TABLES.values():
        con.execute(ddl)


def rebuild(con: sqlite3.Connection, events: Iterable[Event]) -> None:
    """DROP + re-create + replay, inside the caller's transaction. Idempotent:
    output depends on the event log alone."""
    for name in _TABLES:
        con.execute(f"DROP TABLE IF EXISTS {name}")
    ensure_tables(con)
    for event in events:
        _apply(con, event)


def _apply(con: sqlite3.Connection, event: Event) -> None:
    payload = event.payload
    ts = to_stored_ts(event.ts_utc)
    if event.type == "RunStarted":
        con.execute(
            "INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?)",
            (
                payload.get("run_id", event.run_id),
                ts,
                payload.get("model"),
                payload.get("framework"),
                payload.get("prompt_sha256"),
                payload.get("config_version"),
            ),
        )
    elif event.type == "ConfigChanged":
        con.execute(
            "INSERT INTO config_versions VALUES (?, ?, ?)",
            (payload.get("config_version"), ts, event.actor),
        )
