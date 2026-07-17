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

Batch-A scope: the DDL for all four tables is real (so `rebuild()`/
`ensure_tables()` are green infrastructure from birth, same as `runs`/
`config_versions`). `ThesisDrafted` gets minimal handling (inserts a
`state="draft"` row) — the pre-existing P0 done-gate replay test
(`tests/replay/test_p0_replay.py`) already appends a bare `ThesisDrafted`
event and calls `rebuild()`; that baseline test stays green. Every
STATE-TRANSITION past `draft` (`ThesisSubmitted` -> `ThesisApproved`/
`ThesisRejected`/`ThesisActivated`) is now implemented (SPRINT P2 batch A dev
pass) by UPDATEing the existing `theses` row for the event's `thesis_id` —
`ThesisGraded`'s outcome/pnl population lands with grade() in batch B.
`pnl_daily` (FillRecorded net-of-fees aggregation) and `series`/
`promotion_state` (batch D semantics) get NO `_apply` handling at all this
batch — an unhandled event type is silently skipped by `_apply`, same as the
existing `LessonRecorded`-is-noise pattern, so those three tables stay empty
and inert (which is exactly what "empty-ledger rebuild is a no-op" and
"tables exist after rebuild" require, with no red test attached to them
yet).
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

# GUARDED (from_state, event_type) -> to_state table for the "simple"
# one-shot lifecycle markers — each only fires from its single legal source
# state (DESIGN §10.1's diagram); an event whose current row-state doesn't
# match its `from_state` is a no-op (state stays unchanged). `ThesisDrafted`
# gets its own real handling below (a lone ThesisDrafted event with no
# follow-on lifecycle event is exactly what the pre-existing P0 done-gate
# replay test, `tests/replay/test_p0_replay.py`, exercises, and that
# baseline test must stay green). `ReviewCompleted` and `ThesisGraded` are
# NOT here — both need extra payload-driven logic (`kind` / `outcome`),
# handled directly in `_apply` (ASSUMPTIONS 73, P2 batch B — the guarded-
# transition fix; batch A's unguarded `event_type -> state` map let ANY
# out-of-order lifecycle event, e.g. a stray `ReviewCompleted` while
# `active`, clobber derived state — this table + the `_apply` branches below
# are the fix, mirroring `thesis._machine._next_state`'s live-path guard so
# the two stay in agreement, D15/TD-4).
_THESIS_TRANSITION_FROM: dict[str, tuple[str, str]] = {
    "ThesisSubmitted": ("draft", "submitted"),
    "ThesisApproved": ("reviewed", "approved"),
    "ThesisRejected": ("reviewed", "rejected"),
    "ThesisActivated": ("approved", "active"),
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
    elif event.type in _THESIS_TRANSITION_FROM:
        # DESIGN §10.1: submitted -> reviewed -> approved -> active (|
        # rejected, terminal) — GUARDED: only apply if the row's CURRENT
        # state matches this event's legal source state, else leave it
        # unchanged (ASSUMPTIONS 73). Total over any event history: an
        # absent row (no ThesisDrafted replayed yet — shouldn't happen in a
        # well-formed log, but projections must never crash) is also a
        # silent no-op.
        from_state, to_state = _THESIS_TRANSITION_FROM[event.type]
        thesis_id = payload.get("thesis_id")
        row = con.execute(
            "SELECT state FROM theses WHERE thesis_id = ?", (thesis_id,)
        ).fetchone()
        if row is not None and row[0] == from_state:
            con.execute("UPDATE theses SET state = ? WHERE thesis_id = ?", (to_state, thesis_id))
    elif event.type == "ReviewCompleted":
        # Two review artifacts share this event type (ASSUMPTIONS 73):
        # `kind="thesis_review"` is the ONLY lifecycle edge (submitted ->
        # reviewed, guarded same as above); `kind="void_signoff"` (default
        # missing -> "thesis_review" for pre-existing payloads) is a
        # sign-off ARTIFACT for `thesis.void`'s second guard and NEVER
        # transitions state, from any row-state.
        kind = payload.get("kind", "thesis_review")
        if kind == "thesis_review":
            thesis_id = payload.get("thesis_id")
            row = con.execute(
                "SELECT state FROM theses WHERE thesis_id = ?", (thesis_id,)
            ).fetchone()
            if row is not None and row[0] == "submitted":
                con.execute(
                    "UPDATE theses SET state = 'reviewed' WHERE thesis_id = ?", (thesis_id,)
                )
    elif event.type == "ThesisGraded":
        # SPRINT P2 batch B: `thesis.grade`/`thesis.void` populate
        # `outcome`/`measured`/`pnl_usd` fully, always appending this event
        # from `active` (their own `require_state` guards enforce that on
        # the live path). Guarded here too (ASSUMPTIONS 73) so a harness-
        # appended/out-of-order ThesisGraded can never clobber state from
        # any other row-state — still never raises either way.
        thesis_id = payload.get("thesis_id")
        outcome = payload.get("outcome")
        row = con.execute(
            "SELECT state FROM theses WHERE thesis_id = ?", (thesis_id,)
        ).fetchone()
        if row is not None and row[0] == "active":
            con.execute(
                "UPDATE theses SET state = ?, graded_outcome = ?, graded_ts = ? "
                "WHERE thesis_id = ?",
                (outcome, outcome, ts, thesis_id),
            )
