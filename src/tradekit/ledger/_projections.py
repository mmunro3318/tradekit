"""Read-model projections (DESIGN §6.1/§6.2): disposable caches derived from
events. NEVER writes the events table — rebuild derives FROM it only.

P0 projections: ``runs`` (one row per RunStarted, D15 experiment registry)
and ``config_versions`` (from ConfigChanged). The rest of the §6.2 read-model
list lands with its producing subsystems.

SPRINT P2 batch A adds four more projection tables' DDL (`theses`,
`pnl_daily`, `series`, `promotion_state`) per §6.2's read-model list and the
sprint addendum's "these are PROJECTIONS in _projections.py; extend
test_rebuild.py idempotence to all four" pin. Consumers here read the DICT
event envelope, never the typed producer-side payload models in
``contracts._event_payloads`` (ASSUMPTIONS 10's ratified split — see that
module's docstring).

Batch-A scope (TDD test-author pass, "stubs + red tests"): the DDL for all
four tables is real (so `rebuild()`/`ensure_tables()` are green
infrastructure from birth, same as `runs`/`config_versions`). `ThesisDrafted`
gets minimal REAL handling (inserts a `state="draft"` row) — deliberately
NOT a stub, because the pre-existing P0 done-gate replay test
(`tests/replay/test_p0_replay.py`) already appends a bare `ThesisDrafted`
event and calls `rebuild()`; that baseline test must stay green. Every
STATE-TRANSITION past `draft` (`ThesisSubmitted` -> `ThesisGraded`) is an
explicit `NotImplementedError` stub — the `theses`-materializes-state test
in `tests/unit/ledger/test_rebuild.py` (which appends a full submitted ->
reviewed -> approved sequence) is therefore deliberately RED until the P2
dev pass lands it. `pnl_daily` (FillRecorded net-of-fees aggregation) and
`series`/`promotion_state` (batch D semantics) get NO `_apply` handling at
all this batch — an unhandled event type is silently skipped by `_apply`,
same as the existing `LessonRecorded`-is-noise pattern, so those three
tables stay empty and inert (which is exactly what "empty-ledger rebuild is
a no-op" and "tables exist after rebuild" require, with no red test
attached to them yet).
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
    # SPRINT P2 batch A (DESIGN §6.2 read-model list). State-derivation logic
    # for ThesisDrafted..ThesisGraded is a batch-A-dev-pass NotImplementedError
    # stub in _apply() below — see module docstring.
    "theses": """
        CREATE TABLE IF NOT EXISTS theses (
          thesis_id       TEXT PRIMARY KEY,
          account_ref     TEXT,
          state           TEXT NOT NULL,
          strategy_tag    TEXT,
          graded_outcome  TEXT,
          graded_ts       TEXT
        )
    """,
    # MVP schema only this batch — realized_pnl population from FillRecorded
    # (net of fees) is batch B/D's job (sprint addendum: "MVP schema now").
    "pnl_daily": """
        CREATE TABLE IF NOT EXISTS pnl_daily (
          account_ref    TEXT NOT NULL,
          utc_date       TEXT NOT NULL,
          realized_pnl   TEXT NOT NULL,
          PRIMARY KEY (account_ref, utc_date)
        )
    """,
    # Schema + rebuild wiring only this batch; SeriesClosed-driven population
    # (fixed 30-day calendar blocks, complete/clean per §7.3) is batch D.
    "series": """
        CREATE TABLE IF NOT EXISTS series (
          account_ref    TEXT NOT NULL,
          series_index   INTEGER NOT NULL,
          window_start   TEXT NOT NULL,
          window_end     TEXT NOT NULL,
          complete       INTEGER NOT NULL,
          clean          INTEGER NOT NULL,
          PRIMARY KEY (account_ref, series_index)
        )
    """,
    # Schema + rebuild wiring only this batch; PromotionGranted/Confirmed/
    # Demoted-driven population is batch D.
    "promotion_state": """
        CREATE TABLE IF NOT EXISTS promotion_state (
          account_ref              TEXT PRIMARY KEY,
          tier                     TEXT NOT NULL,
          live_sequence_remaining  INTEGER,
          updated_ts               TEXT NOT NULL
        )
    """,
}

# ThesisSubmitted..ThesisGraded (DESIGN §10.1 state machine transitions past
# `draft`, minus grade/void arithmetic which is batch B). State-TRANSITION
# derivation is a batch-A stub — see module docstring — so any ledger
# containing one of these event types makes rebuild() raise
# NotImplementedError rather than silently mis-projecting thesis state.
# `ThesisDrafted` itself is NOT in this set: it gets real (if minimal)
# handling below, because a lone ThesisDrafted event with no follow-on
# lifecycle event is exactly what the pre-existing P0 done-gate replay test
# (`tests/replay/test_p0_replay.py`) exercises, and that baseline test must
# stay green — this batch's "stubs + red tests" mandate applies to the NEW
# behavior it adds, not to breaking an already-green P0 scenario.
_THESIS_LIFECYCLE_EVENT_TYPES = frozenset(
    {
        "ThesisSubmitted",
        "ReviewCompleted",
        "ThesisApproved",
        "ThesisRejected",
        "ThesisActivated",
        "ThesisGraded",
    }
)


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
    elif event.type == "ThesisDrafted":
        # Minimal, real handling (NOT a stub): a fresh thesis starts life in
        # `draft`. Deliberately defensive about payload shape — the
        # pre-existing P0 done-gate replay fixture predates
        # `contracts._event_payloads.ThesisDraftedPayload` and uses a
        # flatter `{"thesis_id": ..., "strategy_tag": ...}` shape with no
        # nested `contract`/`account_ref` at all; both shapes must rebuild
        # without raising.
        contract = payload.get("contract", {})
        con.execute(
            "INSERT OR REPLACE INTO theses VALUES (?, ?, ?, ?, ?, ?)",
            (
                payload.get("thesis_id"),
                contract.get("account_ref", payload.get("account_ref")),
                "draft",
                contract.get("strategy_tag", payload.get("strategy_tag")),
                None,
                None,
            ),
        )
    elif event.type in _THESIS_LIFECYCLE_EVENT_TYPES:
        # SPRINT P2 batch B: derive `theses.state` transitions past `draft`
        # from this event sequence per DESIGN §10.1 (submitted -> reviewed ->
        # approved -> active -> PASS|FAIL|VOID | rejected). Batch A ships
        # only the DDL (see `_TABLES["theses"]` above) and this explicit
        # stub — the `theses`-materializes-state test in test_rebuild.py is
        # deliberately red until this lands.
        raise NotImplementedError(
            "P2 batch B — theses projection state-transition derivation "
            "(docs/handoff/SPRINT-P2-thesis-policy.md)"
        )
