"""P0 done-gate (ROADMAP): a scripted event sequence appends, the chain
verifies, and rebuild is idempotent. Seed of the ring-3 replay harness
(DESIGN §16): later phases extend the scenario; this shape stays.
"""

from datetime import UTC, datetime


def _script(make_event):
    """A plausible day-zero sequence touching several taxonomy groups."""
    t = lambda h, m=0: datetime(2026, 1, 5, h, m, tzinfo=UTC)  # noqa: E731
    return [
        make_event(
            type="RunStarted",
            ts=t(9),
            run_id="run-day0",
            payload={"run_id": "run-day0", "model": "fable-5", "framework": "claude-code"},
        ),
        make_event(
            type="PolicyVersionLoaded",
            ts=t(9, 1),
            payload={"policy_hash": "a" * 64},
        ),
        make_event(
            type="ConfigChanged",
            ts=t(9, 2),
            payload={"dial": "max_position_usd", "old": "20", "new": "25"},
        ),
        make_event(
            type="ThesisDrafted",
            ts=t(10),
            payload={"thesis_id": "T-day0-1", "strategy_tag": "momo-v1"},
        ),
        make_event(
            type="LessonRecorded",
            ts=t(16),
            payload={"note": "alpaca crypto taker fee dominates at $10 notional", "salience": 4},
        ),
    ]


def test_p0_done_gate_replay(ledger, make_event, read_model_snapshot) -> None:
    from tradekit.contracts import EventFilter

    for event in _script(make_event):
        ledger.append(event)

    report = ledger.verify_chain()
    assert report.ok, (
        f"done-gate scenario chain broke at seq {report.first_bad_seq}: five clean "
        "appends must verify — nothing downstream (D4 verification, snapshots) works "
        "if the happy path doesn't"
    )

    ledger.rebuild()
    first = read_model_snapshot()
    assert len(first["runs"]) == 1, (
        f"runs projection rows: {len(first['runs'])} — one RunStarted event means "
        "exactly one experiment-registry row (D15)"
    )

    ledger.rebuild()
    assert read_model_snapshot() == first, (
        "second rebuild diverged from the first: the P0 done-gate is 'rebuild is "
        "idempotent' (ROADMAP P0) — this failing means projections read state "
        "outside the event log"
    )

    assert len(ledger.query(EventFilter())) == 5, "replay must see all five scripted events"
    assert ledger.verify_chain().ok, "rebuild must never disturb the chain (append-only, TD-4)"
