"""Ledger.rebuild (DESIGN §6.1/§6.2, TD-4).

Projections are caches; events are truth. rebuild() must be idempotent,
restorative, and must never write the events table. Projection state is
observed via raw SQL on the db file — a test-harness action, not an import of
ledger internals (see tests/ASSUMPTIONS.md).
"""

import pytest


@pytest.fixture
def ledger_with_runs(ledger, make_event):
    """Two RunStarted events (distinct run_ids) + one unrelated event."""
    for run_id in ("run-aaa", "run-bbb"):
        ledger.append(
            make_event(
                type="RunStarted",
                run_id=run_id,
                payload={
                    "run_id": run_id,
                    "model": "test-model",
                    "framework": "pytest",
                    "prompt_sha256": "0" * 64,
                    "config_version": 1,
                },
            )
        )
    ledger.append(make_event(type="LessonRecorded", payload={"note": "noise", "salience": 1}))
    return ledger


def test_rebuild_is_idempotent(ledger_with_runs, read_model_snapshot) -> None:
    ledger_with_runs.rebuild()
    first = read_model_snapshot()
    assert "runs" in first, (
        f"read-model tables after rebuild: {sorted(first)} — expected a 'runs' projection "
        "derived from RunStarted events (§6.2 read models; naming is an ASSUMPTIONS.md item)"
    )
    assert len(first["runs"]) == 2, (
        f"runs projection has {len(first['runs'])} rows for 2 RunStarted events: the "
        "experiment registry (D15) must see exactly one row per run"
    )

    ledger_with_runs.rebuild()
    second = read_model_snapshot()
    assert second == first, (
        "second rebuild changed read-model state: rebuild must be idempotent (interface "
        "docstring) — drift between consecutive rebuilds means projections depend on "
        "something other than the event log"
    )


def test_rebuild_restores_corrupted_projection(
    ledger_with_runs, read_model_snapshot, raw_sql
) -> None:
    ledger_with_runs.rebuild()
    truth = read_model_snapshot()

    raw_sql("DELETE FROM runs")  # simulate a projection corrupted out-of-band

    ledger_with_runs.rebuild()
    assert read_model_snapshot() == truth, (
        "rebuild did not restore the runs projection from events: projections are "
        "disposable caches and the log is the only truth (§6.1) — anything less makes "
        "`tk ledger rebuild` a no-op lie"
    )


def test_rebuild_never_touches_events(ledger_with_runs, raw_sql) -> None:
    columns = "seq, event_id, ts_utc, type, actor, run_id, schema_ver, payload, prev_hash, hash"
    before = raw_sql(f"SELECT {columns} FROM events ORDER BY seq")

    ledger_with_runs.rebuild()

    after = raw_sql(f"SELECT {columns} FROM events ORDER BY seq")
    assert after == before, (
        "rebuild modified the events table: the log is append-only and sacred (TD-4, "
        "TD-22) — rebuild derives FROM it, never writes TO it"
    )
    assert ledger_with_runs.verify_chain().ok, "hash chain broken after rebuild (§6.2)"


# ---------------------------------------------------------------------------
# SPRINT P2 batch A: theses / pnl_daily / series / promotion_state (DESIGN
# §6.2 read-model list). DDL is real this batch; `theses`'s state-derivation
# `_apply` handling is a `NotImplementedError` stub (see
# `_projections.py`'s module docstring) — so the "materializes state
# correctly" test below is the batch's deliberately-red thesis-projection
# test, while the schema/idempotence/no-op tests are green infrastructure,
# same split as the payload-model tests vs. the thesis-verb tests.
# ---------------------------------------------------------------------------

_NEW_P2_TABLES = ("theses", "pnl_daily", "series", "promotion_state")


def test_p2_projection_tables_exist_after_rebuild(ledger, read_model_snapshot) -> None:
    ledger.rebuild()
    snapshot = read_model_snapshot()
    for table in _NEW_P2_TABLES:
        assert table in snapshot, (
            f"{table!r} missing from the read-model snapshot after rebuild() on a fresh "
            "ledger — DESIGN §6.2's read-model list requires theses/pnl_daily/series/"
            "promotion_state DDL to exist from birth (batch A pin), same as runs/config_versions"
        )


def test_empty_ledger_rebuild_of_new_tables_is_a_noop(ledger, read_model_snapshot) -> None:
    ledger.rebuild()
    first = {table: read_model_snapshot()[table] for table in _NEW_P2_TABLES}
    assert all(rows == [] for rows in first.values()), (
        f"a fresh ledger with zero events must leave every new projection table empty: {first}"
    )

    ledger.rebuild()
    second = {table: read_model_snapshot()[table] for table in _NEW_P2_TABLES}
    assert second == first, (
        "rebuilding an empty ledger a second time changed the new projection tables — "
        "rebuild must be idempotent even (especially) on the no-op case"
    )


@pytest.fixture
def ledger_with_thesis_lifecycle(ledger, make_event):
    """One thesis walking draft -> submitted -> reviewed -> approved (§10.1),
    exactly the event sequence story 1's `thesis.approve` verb will someday
    append + harness-append (ReviewCompleted, CTO addendum). Payload shapes
    mirror the batch-A typed payload models' fields (contracts._event_payloads)
    but are plain dicts here — projections consume the DICT envelope, never
    the typed producer-side models (ASSUMPTIONS 10)."""
    thesis_id = "th-lifecycle-01"
    events = [
        (
            "ThesisDrafted",
            {
                "thesis_id": thesis_id,
                "contract": {"account_ref": "paper:alpha", "strategy_tag": "momo-breakout-v1"},
                "supersedes": None,
            },
        ),
        (
            "ThesisSubmitted",
            {
                "thesis_id": thesis_id,
                "market_snapshot_id": "snap-1",
                "resolved_target_price": "66000.00",
                "resolved_stop_price": "57000.00",
                "resolved_success_criteria": [],
                "resolved_failure_criteria": [],
                "ev_stated_usd": "0.81",
                "ev_recomputed_usd": "0.8125",
            },
        ),
        (
            "ReviewCompleted",
            {"thesis_id": thesis_id, "review_artifact_id": "rev-1", "passed": True},
        ),
        (
            "ThesisApproved",
            {"thesis_id": thesis_id, "review_artifact_id": "rev-1"},
        ),
    ]
    for event_type, payload in events:
        ledger.append(make_event(type=event_type, payload=payload))
    return ledger, thesis_id


def test_theses_projection_materializes_state_from_event_sequence(
    ledger_with_thesis_lifecycle, raw_sql
) -> None:
    ledger, thesis_id = ledger_with_thesis_lifecycle
    ledger.rebuild()
    rows = raw_sql("SELECT state FROM theses WHERE thesis_id = ?", thesis_id)
    assert len(rows) == 1
    assert rows[0][0] == "approved", (
        "the theses projection must materialize the FULL draft -> submitted -> "
        "reviewed -> approved event sequence to state == 'approved' (DESIGN §10.1)"
    )


# ---------------------------------------------------------------------------
# SPRINT P2 batch D: pnl_daily / series / promotion_state real population
# (DESIGN §6.2; CTO addendum story-4 pins). RED this batch — `_apply()` has
# no handling for `pnl_daily`'s ThesisGraded aggregation nor for `series`/
# `promotion_state`'s PromotionGranted/Confirmed/Demoted-driven rows yet
# (same "unhandled event type is silently skipped, table stays empty"
# behavior as batch A's own `series`/`promotion_state` no-op — see
# `_projections.py`'s module docstring); every assertion below describes
# the REAL population the dev pass wires next.
# ---------------------------------------------------------------------------

@pytest.fixture
def ledger_with_graded_theses(ledger, make_event):
    """Two theses for `paper:alpha`, graded on DIFFERENT UTC calendar days,
    plus one None-pnl grade (ASSUMPTIONS 71: excluded from any pnl SUM, same
    as it's excluded from series expectancy) — exercises pnl_daily's
    per-(account_ref, utc_date) aggregation and its None-pnl exclusion in one
    fixture."""
    from datetime import UTC, datetime

    day1 = datetime(2026, 1, 5, 10, 0, 0, tzinfo=UTC)
    day1_later = datetime(2026, 1, 5, 18, 0, 0, tzinfo=UTC)
    day2 = datetime(2026, 1, 6, 9, 0, 0, tzinfo=UTC)

    for thesis_id in ("th-pnl-1", "th-pnl-2", "th-pnl-3"):
        ledger.append(
            make_event(
                type="ThesisDrafted",
                payload={
                    "thesis_id": thesis_id,
                    "contract": {"account_ref": "paper:alpha"},
                    "supersedes": None,
                },
            )
        )
    ledger.append(
        make_event(
            type="ThesisGraded",
            ts=day1,
            payload={
                "thesis_id": "th-pnl-1",
                "outcome": "PASS",
                "measured": [],
                "ambiguous_bar": False,
                "pnl_usd": "12.50",
                "graded_ts": day1.isoformat(),
            },
        )
    )
    ledger.append(
        make_event(
            type="ThesisGraded",
            ts=day1_later,
            payload={
                "thesis_id": "th-pnl-2",
                "outcome": "FAIL",
                "measured": [],
                "ambiguous_bar": False,
                "pnl_usd": "-3.25",
                "graded_ts": day1_later.isoformat(),
            },
        )
    )
    ledger.append(
        make_event(
            type="ThesisGraded",
            ts=day2,
            payload={
                "thesis_id": "th-pnl-3",
                "outcome": "FAIL",
                "measured": [],
                "ambiguous_bar": False,
                "pnl_usd": None,
                "graded_ts": day2.isoformat(),
            },
        )
    )
    return ledger


def test_pnl_daily_aggregates_thesis_graded_pnl_by_account_and_utc_date(
    ledger_with_graded_theses, raw_sql
) -> None:
    ledger_with_graded_theses.rebuild()
    rows = raw_sql(
        "SELECT account_ref, utc_date, realized_pnl FROM pnl_daily ORDER BY utc_date"
    )
    assert rows == [
        ("paper:alpha", "2026-01-05", "9.25"),
        ("paper:alpha", "2026-01-06", "0"),
    ], (
        f"got {rows}: day 1 sums the two same-day grades (12.50 + -3.25 = 9.25, "
        "P2 convention: realized pnl lands at GRADE time, not FillRecorded time — "
        "FLAGGED, a P3 broker refinement); day 2's lone grade is None-pnl, excluded "
        "from the sum (ASSUMPTIONS 71) — the row still exists at 0, not absent, because "
        "a graded day with zero MEASURED pnl is a real fact worth a row, distinct from "
        "a day with no grading at all (no row)"
    )


def test_pnl_daily_rebuild_is_idempotent(ledger_with_graded_theses, read_model_snapshot) -> None:
    ledger_with_graded_theses.rebuild()
    first = read_model_snapshot()["pnl_daily"]
    ledger_with_graded_theses.rebuild()
    second = read_model_snapshot()["pnl_daily"]
    assert second == first


@pytest.fixture
def ledger_with_one_clean_series(ledger, make_event):
    """Ten graded non-void theses for `paper:alpha`, spanning series_index 0
    under the `series_epoch` dial default (2026-01-01T00:00:00Z) — the exact
    CLEAN fixture from `tests/unit/policy/test_series.py`
    (`test_series_stats_clean_ten_graded_positive_expectancy_low_mdd`):
    pnls 5.874, -2.10, 1.00, then seven 0.00 — expectancy 0.4774, mdd_pct
    ~0.415%, zero gate violations -> complete AND clean."""
    from datetime import UTC, datetime, timedelta

    start = datetime(2026, 1, 1, tzinfo=UTC)
    pnls = ["5.874", "-2.10", "1.00", "0", "0", "0", "0", "0", "0", "0"]
    for i, pnl in enumerate(pnls):
        thesis_id = f"th-clean-series-{i}"
        ts = start + timedelta(days=i)
        ledger.append(
            make_event(
                type="ThesisDrafted",
                ts=start,
                payload={
                    "thesis_id": thesis_id,
                    "contract": {"account_ref": "paper:alpha"},
                    "supersedes": None,
                },
            )
        )
        ledger.append(
            make_event(
                type="ThesisGraded",
                ts=ts,
                payload={
                    "thesis_id": thesis_id,
                    "outcome": "PASS",
                    "measured": [],
                    "ambiguous_bar": False,
                    "pnl_usd": pnl,
                    "graded_ts": ts.isoformat(),
                },
            )
        )
    return ledger


def test_series_projection_materializes_a_complete_clean_series_row(
    ledger_with_one_clean_series, raw_sql
) -> None:
    """The `series` projection table materializes per-series rows for
    CLI/report reads (CTO addendum story-4 pins: 'the series projection
    table materializes per-series rows on rebuild ... a SeriesClosed event
    is NOT emitted in P2' — no producer event; the row is derived the SAME
    way `policy._series.series_stats` derives it at read time, both from
    ThesisGraded/GateViolationDetected directly)."""
    ledger_with_one_clean_series.rebuild()
    rows = raw_sql(
        "SELECT account_ref, series_index, complete, clean FROM series "
        "WHERE account_ref = 'paper:alpha' AND series_index = 0"
    )
    assert len(rows) == 1, (
        f"expected exactly one series row for (paper:alpha, 0), got {rows} — the "
        "projection must derive series membership from ThesisGraded's own graded_ts "
        "via series_index(), the same arithmetic as policy._series.series_index"
    )
    assert rows[0][2] == 1, "complete: 10 graded non-void, window closed by rebuild time"
    assert rows[0][3] == 1, "clean: expectancy 0.4774 > 0, mdd ~0.415% < 15%, 0 violations"


def test_promotion_state_projection_materializes_from_confirmed_event(
    ledger, make_event, raw_sql
) -> None:
    """`promotion_state` materializes from PromotionGranted/Confirmed/Demoted
    events (CTO addendum story-4 pins) — a bare harness-appended
    `PromotionConfirmed` must be enough to see `tier == 'T2'`,
    `live_sequence_remaining == 3` in the projection after rebuild (D15/
    TD-4: promotion state must survive ONLY via `tk ledger rebuild`, never a
    side table)."""
    ledger.append(
        make_event(
            type="PromotionGranted",
            payload={
                "account_ref": "paper:alpha",
                "from_tier": "T1",
                "to_tier": "T2",
                "criteria": {"three_of_last_four_clean": True},
            },
        )
    )
    ledger.append(
        make_event(
            type="PromotionConfirmed",
            payload={
                "account_ref": "paper:alpha",
                "to_tier": "T2",
                "granted_event_id": "evt-grant-1",
                "live_sequence_remaining": 3,
                "confirmed_by": "mike",
            },
        )
    )
    ledger.rebuild()
    rows = raw_sql(
        "SELECT account_ref, tier, live_sequence_remaining FROM promotion_state "
        "WHERE account_ref = 'paper:alpha'"
    )
    assert rows == [("paper:alpha", "T2", 3)]


def test_promotion_state_projection_reflects_demoted_event(ledger, make_event, raw_sql) -> None:
    for event_type, payload in [
        (
            "PromotionGranted",
            {
                "account_ref": "paper:alpha",
                "from_tier": "T1",
                "to_tier": "T2",
                "criteria": {},
            },
        ),
        (
            "PromotionConfirmed",
            {
                "account_ref": "paper:alpha",
                "to_tier": "T2",
                "granted_event_id": "evt-grant-1",
                "live_sequence_remaining": 3,
                "confirmed_by": "mike",
            },
        ),
        (
            "Demoted",
            {
                "account_ref": "paper:alpha",
                "from_tier": "T2",
                "to_tier": "T1",
                "trigger": "drawdown_breach",
                "detail": "R-009 trip",
            },
        ),
    ]:
        ledger.append(make_event(type=event_type, payload=payload))
    ledger.rebuild()
    rows = raw_sql(
        "SELECT account_ref, tier FROM promotion_state WHERE account_ref = 'paper:alpha'"
    )
    assert rows == [("paper:alpha", "T1")], "a Demoted event must roll the tier back to T1"


def test_promotion_state_and_series_projections_survive_rebuild_idempotently(
    ledger_with_one_clean_series, raw_sql
) -> None:
    ledger_with_one_clean_series.rebuild()
    first_series = raw_sql("SELECT * FROM series ORDER BY series_index")
    ledger_with_one_clean_series.rebuild()
    second_series = raw_sql("SELECT * FROM series ORDER BY series_index")
    assert second_series == first_series, (
        "a second rebuild of the SAME event log must reproduce byte-identical series "
        "rows — projections are disposable caches, the log is the only truth (§6.1)"
    )


def test_projection_series_constants_stay_synced_with_policy_dials_defaults() -> None:
    """Drift tripwire (P2 batch-D CTO gate): ledger/_projections.py re-derives
    the series arithmetic with its OWN constants because ledger must stay
    stdlib-only (no pydantic-settings import). If PolicyDials' defaults ever
    change (config.toml or _dials.py), this test forces the projection
    constants to be updated in the same commit — the narrow-but-real drift
    risk flagged by the batch-D dev report."""
    from tradekit.ledger import (
        _projections,  # noqa: TID251 — harness tripwire, reads constants only
    )
    from tradekit.policy._dials import PolicyDials

    dials = PolicyDials.load()
    assert _projections._SERIES_EPOCH == dials.series_epoch
    assert _projections._PAPER_STARTING_EQUITY_USD == dials.paper_starting_equity_usd
