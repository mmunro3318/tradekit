"""tradekit.ledger — append-only, hash-chained event store (DESIGN §6, TD-4/16/22).

Deep interface: six verbs on ``Ledger``. Everything else — SQLite/WAL/FTS5,
canonical-JSON hashing, retry-with-jitter, projections, migrations, run-id
stamping — is private implementation.

The events table is the source of truth; read models are rebuildable caches.
``ledger.db`` is sacred; the market-data cache lives elsewhere (TD-22).
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from tradekit.contracts import ChainReport, Event, EventFilter
from tradekit.ledger import _db, _hash, _projections


class Ledger:
    """Handle to one ledger database file.

    Opens (and migrates, if needed) the SQLite file at ``db_path`` with WAL
    mode and busy_timeout. Instances are cheap; every verb is one short
    transaction wrapped in bounded retry-with-jitter (TD-16).
    """

    def __init__(self, db_path: Path) -> None:
        self._con = _db.connect(db_path)
        _db.migrate(self._con)
        # Projection tables exist (empty) from birth so rebuild-on-fresh and
        # projection reads never hit a missing table.
        _projections.ensure_tables(self._con)

    def append(self, event: Event) -> str:
        """Validate, hash-chain, and durably append one event.

        Stamps ``run_id`` from TK_RUN_ID if the event doesn't carry one.
        Returns the event_id (ULID). The ONLY write path into the ledger.
        """
        event = _stamp_run_id(event)
        ts = _db.to_stored_ts(event.ts_utc)
        payload_json = _hash.canonical_json(event.payload)

        def _write() -> None:
            with self._transaction() as con:
                row = con.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
                prev_hash = row[0] if row is not None else _hash.GENESIS_HASH
                digest = _hash.event_hash(
                    prev_hash,
                    event.event_id,
                    ts,
                    event.type,
                    event.actor,
                    event.run_id,
                    event.schema_ver,
                    payload_json,
                )
                con.execute(
                    "INSERT INTO events"
                    " (event_id, ts_utc, type, actor, run_id, schema_ver,"
                    "  payload, prev_hash, hash)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event.event_id,
                        ts,
                        event.type,
                        event.actor,
                        event.run_id,
                        event.schema_ver,
                        payload_json,
                        prev_hash,
                        digest,
                    ),
                )
                # FTS row rides the same transaction — index and truth can't diverge.
                con.execute(
                    "INSERT INTO events_fts (event_id, type, payload_text) VALUES (?, ?, ?)",
                    (event.event_id, event.type, payload_json),
                )

        _db.with_write_retry(_write)
        return event.event_id

    def query(self, filter: EventFilter) -> list[Event]:
        """Return events matching the filter, in seq order."""
        clauses: list[str] = []
        params: list[str] = []
        if filter.types is not None:
            if not filter.types:
                return []
            clauses.append(f"type IN ({', '.join('?' * len(filter.types))})")
            params.extend(filter.types)
        # since/until are INCLUSIVE (ASSUMPTIONS 12, ratified).
        if filter.since is not None:
            clauses.append("ts_utc >= ?")
            params.append(_db.to_stored_ts(filter.since))
        if filter.until is not None:
            clauses.append("ts_utc <= ?")
            params.append(_db.to_stored_ts(filter.until))
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._con.execute(
            f"SELECT {_db.EVENT_COLUMNS} FROM events{where} ORDER BY seq", params
        ).fetchall()
        return [_db.row_to_event(row) for row in rows]

    def search(self, text: str, k: int = 20) -> list[Event]:
        """FTS5 keyword search over event payloads (TD-20)."""
        # Quoted as an FTS5 phrase: user text is a query *value*, never query
        # syntax — hostile input can't raise, so a genuine fault (corrupted or
        # missing FTS table) is allowed to propagate instead of masquerading
        # as "no results" (reviewer D6).
        phrase = '"' + text.replace('"', '""') + '"'
        rows = self._con.execute(
            f"SELECT {_db.EVENT_COLUMNS} FROM events"
            " WHERE event_id IN"
            "   (SELECT event_id FROM events_fts WHERE events_fts MATCH ?)"
            " ORDER BY seq LIMIT ?",
            (phrase, k),
        ).fetchall()
        return [_db.row_to_event(row) for row in rows]

    def verify_chain(self) -> ChainReport:
        """Recompute the hash chain end-to-end; report first break, if any."""
        expected_prev = _hash.GENESIS_HASH
        rows = self._con.execute(
            "SELECT seq, event_id, ts_utc, type, actor, run_id, schema_ver,"
            " payload, prev_hash, hash FROM events ORDER BY seq"
        )
        for seq, event_id, ts, type_, actor, run_id, schema_ver, payload, prev_hash, digest in rows:
            recomputed = _hash.event_hash(
                expected_prev, event_id, ts, type_, actor, run_id, schema_ver, payload
            )
            if prev_hash != expected_prev or digest != recomputed:
                return ChainReport(ok=False, first_bad_seq=seq)
            expected_prev = digest
        return ChainReport(ok=True, first_bad_seq=None)

    def rebuild(self) -> None:
        """Drop and re-derive all read-model projections from events. Idempotent."""
        events = self.query(EventFilter())

        def _apply() -> None:
            with self._transaction() as con:
                _projections.rebuild(con, events)

        _db.with_write_retry(_apply)

    @contextlib.contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """One short IMMEDIATE transaction; rollback on any failure."""
        self._con.execute("BEGIN IMMEDIATE")
        try:
            yield self._con
            self._con.execute("COMMIT")
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                self._con.execute("ROLLBACK")
            raise


def default_ledger() -> Ledger:
    """Ledger at the configured data dir (TK_DATA_DIR, default ./data)."""
    data_dir = Path(os.environ.get("TK_DATA_DIR", "data"))
    return Ledger(data_dir / "ledger.db")


def _stamp_run_id(event: Event) -> Event:
    """TK_RUN_ID fills a missing run_id only; an explicit one always wins
    (ASSUMPTIONS 15). The envelope is frozen, so stamping is a copy."""
    if event.run_id is not None:
        return event
    env_run_id = os.environ.get("TK_RUN_ID")
    if not env_run_id:
        return event
    return event.model_copy(update={"run_id": env_run_id})


__all__ = ["Ledger", "default_ledger"]
