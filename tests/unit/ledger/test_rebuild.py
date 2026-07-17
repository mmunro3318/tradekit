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
