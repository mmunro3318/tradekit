"""tradekit.ledger — append-only, hash-chained event store (DESIGN §6, TD-4/16/22).

Deep interface: six verbs on ``Ledger``. Everything else — SQLite/WAL/FTS5,
canonical-JSON hashing, retry-with-jitter, projections, migrations, run-id
stamping — is private implementation.

The events table is the source of truth; read models are rebuildable caches.
``ledger.db`` is sacred; the market-data cache lives elsewhere (TD-22).
"""

from __future__ import annotations

from pathlib import Path

from tradekit.contracts import ChainReport, Event, EventFilter


class Ledger:
    """Handle to one ledger database file.

    Opens (and migrates, if needed) the SQLite file at ``db_path`` with WAL
    mode and busy_timeout. Instances are cheap; every verb is one short
    transaction wrapped in bounded retry-with-jitter (TD-16).
    """

    def __init__(self, db_path: Path) -> None:
        raise NotImplementedError  # P0 M0.3

    def append(self, event: Event) -> str:
        """Validate, hash-chain, and durably append one event.

        Stamps ``run_id`` from TK_RUN_ID if the event doesn't carry one.
        Returns the event_id (ULID). The ONLY write path into the ledger.
        """
        raise NotImplementedError  # P0 M0.3

    def query(self, filter: EventFilter) -> list[Event]:
        """Return events matching the filter, in seq order."""
        raise NotImplementedError  # P0 M0.3

    def search(self, text: str, k: int = 20) -> list[Event]:
        """FTS5 keyword search over event payloads (TD-20)."""
        raise NotImplementedError  # P0 M0.3

    def verify_chain(self) -> ChainReport:
        """Recompute the hash chain end-to-end; report first break, if any."""
        raise NotImplementedError  # P0 M0.3

    def rebuild(self) -> None:
        """Drop and re-derive all read-model projections from events. Idempotent."""
        raise NotImplementedError  # P0 M0.3


def default_ledger() -> Ledger:
    """Ledger at the configured data dir (TK_DATA_DIR, default ./data)."""
    raise NotImplementedError  # P0 M0.3


__all__ = ["Ledger", "default_ledger"]
