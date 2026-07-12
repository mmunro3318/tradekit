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
