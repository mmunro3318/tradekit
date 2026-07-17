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

ASSUMPTIONS (review round-14 MEDIUM): the `series` projection's `complete`
flag is LOG-RELATIVE, not wall-clock-relative — `_materialize_series` derives
"now" as the MAX `ts_utc` across the whole event log, never
`datetime.now(UTC)`, so `complete = window_end <= now_for_completeness`. This
is a deliberate corollary of `rebuild()`'s own promise ("output depends on
the event log alone"): a disposable read-model cache can only know what its
source log knows, and two rebuilds of the same log run on two different
wall-clock days must produce byte-identical rows forever. `policy._series`
(seam-clocked via `policy._context.clock()`, injectable in tests) remains the
actual DECISION authority for anti-permissive policy checks (promotion
gates, etc.) — this projection exists for CLI/report reads only, and its
log-relative `complete` can legitimately read `False` for a window a
wall-clock-aware caller would consider closed, if the log itself has no
event past that window's end.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tradekit.contracts import Event
from tradekit.ledger._db import to_stored_ts

# SPRINT P2 batch D: `series`/`promotion_state` real population. `ledger`
# sits BELOW `policy` in the dependency graph (policy imports ledger, never
# the reverse — importing `tradekit.policy` here would be a genuine import
# cycle, `tradekit.policy/__init__.py` itself does `from tradekit.ledger
# import Ledger, default_ledger` at its own top), so `policy._series`'s
# arithmetic is INDEPENDENTLY re-derived here rather than imported —
# `_series.py`'s own module docstring names this explicitly ("the derivation
# here and the projection's population must agree byte-for-byte", ASSUMPTIONS
# 86). The epoch/equity constants below mirror `PolicyDials`'s own defaults
# (`series_epoch`/`paper_starting_equity_usd`); a `TK_CONFIG_PATH` override
# of those dials would NOT be reflected in this projection — a known,
# documented divergence risk (flagged, not fixed this batch: fixing it for
# real needs a shared leaf below both modules, a TD-register change).
_SERIES_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
_PAPER_STARTING_EQUITY_USD = Decimal("500")
_SERIES_WINDOW = timedelta(days=30)

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
    # SPRINT P3 batch A (TD-24): one row per `AccountCreated` event.
    "accounts": """
        CREATE TABLE IF NOT EXISTS accounts (
          account_ref     TEXT PRIMARY KEY,
          principal_usd   TEXT NOT NULL,
          config          TEXT NOT NULL,
          created_ts      TEXT NOT NULL
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
    materialized = list(events)
    for event in materialized:
        _apply(con, event)
    _materialize_series(con, materialized)
    _materialize_promotion_state(con, materialized)


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
        # LOW-2 (review round-14): two producers share this event type with
        # DIFFERENT payload shapes (ASSUMPTIONS 10's ratified split) — the P0
        # shape (`RunStarted`-adjacent config bumps) carries `config_version`;
        # `policy`'s own `ConfigChangedPayload` (`previous_hash`/`new_hash`/
        # `dials`) never does. Only insert when the key is actually PRESENT —
        # unconditionally inserting `payload.get("config_version")` produced
        # a NULL-junk row for every policy-shaped ConfigChanged event.
        if "config_version" in payload:
            con.execute(
                "INSERT INTO config_versions VALUES (?, ?, ?)",
                (payload.get("config_version"), ts, event.actor),
            )
    elif event.type == "AccountCreated":
        # SPRINT P3 batch A (TD-24): idempotent by account_ref (INSERT OR
        # REPLACE, same discipline as `runs`/`theses` above) — a
        # duplicate-account_ref append is refused at the producer
        # (`broker.create_paper_account`'s `AccountAlreadyExists`), so this
        # projection never actually SEES two AccountCreated events for the
        # same account_ref in a well-formed log, but rebuild must still be a
        # pure function of whatever the log contains.
        config = payload.get("config", {})
        con.execute(
            "INSERT OR REPLACE INTO accounts VALUES (?, ?, ?, ?)",
            (
                payload.get("account_ref"),
                str(config.get("principal_usd", "")),
                json.dumps(config, sort_keys=True),
                ts,
            ),
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
        # SPRINT P2 batch D: pnl_daily aggregation. P2 convention (FLAGGED,
        # matching test_rebuild.py's own docstring): realized pnl lands at
        # GRADE time, not FillRecorded time — a P3 broker refinement.
        # None-pnl theses are excluded from the SUM (ASSUMPTIONS 71) but a
        # graded day with zero measured pnl still gets a row at "0", distinct
        # from a day with no grading at all (no row).
        account_row = con.execute(
            "SELECT account_ref FROM theses WHERE thesis_id = ?", (thesis_id,)
        ).fetchone()
        if account_row is not None and account_row[0] is not None:
            account_ref = account_row[0]
            graded_ts = _parse_graded_ts(payload.get("graded_ts"), event.ts_utc)
            utc_date = graded_ts.astimezone(UTC).date().isoformat()
            pnl = payload.get("pnl_usd")
            pnl_dec = Decimal(str(pnl)) if pnl is not None else Decimal("0")
            existing = con.execute(
                "SELECT realized_pnl FROM pnl_daily WHERE account_ref = ? AND utc_date = ?",
                (account_ref, utc_date),
            ).fetchone()
            new_total = (Decimal(existing[0]) if existing is not None else Decimal("0")) + pnl_dec
            con.execute(
                "INSERT OR REPLACE INTO pnl_daily VALUES (?, ?, ?)",
                (account_ref, utc_date, str(new_total)),
            )


def _parse_graded_ts(raw: str | None, fallback: datetime) -> datetime:
    ts = datetime.fromisoformat(raw) if raw else fallback
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def _materialize_series(con: sqlite3.Connection, events: list[Event]) -> None:
    """Independently re-derive `policy._series.series_stats`'s own
    complete/clean arithmetic (module-top docstring explains why this is
    duplicated rather than imported) over every (account_ref, series_index)
    pair with any graded history, and upsert one `series` row each."""
    account_by_thesis: dict[str, str] = {}
    graded_events: list[Event] = []
    violations: list[Event] = []
    for event in events:
        if event.type == "ThesisDrafted":
            contract = event.payload.get("contract", {})
            account_ref = contract.get("account_ref")
            thesis_id = event.payload.get("thesis_id")
            if thesis_id is not None and account_ref is not None:
                account_by_thesis[thesis_id] = account_ref
        elif event.type == "ThesisGraded":
            graded_events.append(event)
        elif event.type == "GateViolationDetected":
            violations.append(event)

    per_account: dict[str, list[Event]] = {}
    for event in graded_events:
        thesis_id = event.payload.get("thesis_id")
        account_ref = account_by_thesis.get(thesis_id) if thesis_id is not None else None
        if account_ref is not None:
            per_account.setdefault(account_ref, []).append(event)

    def graded_ts(event: Event) -> datetime:
        return _parse_graded_ts(event.payload.get("graded_ts"), event.ts_utc)

    series_keys: set[tuple[str, int]] = set()
    for account_ref, acc_events in per_account.items():
        for event in acc_events:
            idx = (graded_ts(event) - _SERIES_EPOCH) // _SERIES_WINDOW
            series_keys.add((account_ref, idx))

    # Review round-14 MEDIUM: `complete` must be a pure function of the
    # event log, not wall-clock `datetime.now(UTC)` — rebuild()'s own
    # interface docstring promises "output depends on the event log alone",
    # and two rebuilds of the same log on two different days must agree
    # forever. A cached read model can only know what the log knows, so
    # "now" here is the MAX ts_utc across the whole event log (the latest
    # instant the log has any evidence of) — `complete` asks whether the
    # window's own end has been reached by that log-relative clock, not by
    # the wall clock the rebuild happens to run on. `policy._series`
    # (seam-clocked via `policy._context.clock()`, injectable in tests)
    # remains the actual decision authority for anti-permissive checks —
    # this projection is a read-only cache for CLI/report reads.
    now_for_completeness = max((event.ts_utc for event in events), default=_SERIES_EPOCH)
    for account_ref, series_idx in sorted(series_keys, key=lambda k: (k[0], k[1])):
        window_start = _SERIES_EPOCH + _SERIES_WINDOW * series_idx
        window_end = window_start + _SERIES_WINDOW

        in_window = sorted(
            (e for e in per_account[account_ref] if window_start <= graded_ts(e) < window_end),
            key=graded_ts,
        )
        graded_count = sum(1 for e in in_window if e.payload.get("outcome") in ("PASS", "FAIL"))
        non_void_pnls = [
            Decimal(str(e.payload.get("pnl_usd")))
            for e in in_window
            if e.payload.get("outcome") in ("PASS", "FAIL") and e.payload.get("pnl_usd") is not None
        ]
        expectancy = (
            sum(non_void_pnls, Decimal("0")) / len(non_void_pnls) if non_void_pnls else None
        )

        # Review round-14 HIGH: scope to THIS account's own graded theses
        # only (`per_account[account_ref]`, the same list `in_window` is
        # filtered from), not every account's `graded_events` — pooling let
        # a winning sibling's pre-window pnl inflate this account's base and
        # launder a dirty MDD into a falsely clean one (identical bug to,
        # and must be fixed identically alongside, `policy._series
        # .series_stats`'s own `equity_entering` derivation above it).
        equity_entering = _PAPER_STARTING_EQUITY_USD
        for event in per_account[account_ref]:
            if graded_ts(event) < window_start:
                pnl = event.payload.get("pnl_usd")
                if pnl is not None:
                    equity_entering += Decimal(str(pnl))

        equity = equity_entering
        peak = equity
        mdd_pct = 0.0
        for event in in_window:
            pnl = event.payload.get("pnl_usd")
            equity += Decimal(str(pnl)) if pnl is not None else Decimal("0")
            peak = max(peak, equity)
            if peak > 0:
                mdd_pct = max(mdd_pct, float((peak - equity) / peak))

        gate_violations = sum(
            1
            for e in violations
            if e.payload.get("account_ref") == account_ref
            and window_start <= e.ts_utc.astimezone(UTC) < window_end
        )

        complete = window_end <= now_for_completeness and graded_count >= 10
        clean = (
            complete
            and gate_violations == 0
            and expectancy is not None
            and expectancy > 0
            and mdd_pct < 0.15
        )

        con.execute(
            "INSERT OR REPLACE INTO series VALUES (?, ?, ?, ?, ?, ?)",
            (
                account_ref,
                series_idx,
                to_stored_ts(window_start),
                to_stored_ts(window_end),
                int(complete),
                int(clean),
            ),
        )


def _materialize_promotion_state(con: sqlite3.Connection, events: list[Event]) -> None:
    """Fold `PromotionConfirmed`/`Demoted` history per `account_ref` into the
    current tier — `PromotionGranted` alone never changes tier (it is an
    offer, not a state change; only `confirm_promotion()`'s
    `PromotionConfirmed` — or a later `Demoted` — moves the projection)."""
    state: dict[str, tuple[str, int | None, datetime]] = {}
    for event in events:
        if event.type == "PromotionConfirmed":
            account_ref = event.payload.get("account_ref")
            if account_ref is not None:
                state[account_ref] = (
                    event.payload.get("to_tier", "T2"),
                    event.payload.get("live_sequence_remaining"),
                    event.ts_utc,
                )
        elif event.type == "Demoted":
            account_ref = event.payload.get("account_ref")
            if account_ref is not None:
                state[account_ref] = (
                    event.payload.get("to_tier", "T1"),
                    None,
                    event.ts_utc,
                )

    for account_ref, (tier, live_remaining, updated_ts) in state.items():
        con.execute(
            "INSERT OR REPLACE INTO promotion_state VALUES (?, ?, ?, ?)",
            (account_ref, tier, live_remaining, to_stored_ts(updated_ts)),
        )
