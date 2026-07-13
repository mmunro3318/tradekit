"""Ledger.append + verify_chain (DESIGN §6.2, TD-4, TD-16, TD-20).

The tamper tests are the G-review fix made executable: the hash preimage covers
prev_hash + ALL other columns — nothing editable outside the chain.
"""

import re

import pytest

from tradekit.contracts import EventFilter
from tradekit.ledger import Ledger

# Crockford base32, 26 chars, no I/L/O/U.
ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def _find(ledger, event_id):
    matches = [e for e in ledger.query(EventFilter()) if e.event_id == event_id]
    assert len(matches) == 1, f"expected exactly one event {event_id!r}, found {len(matches)}"
    return matches[0]


def test_append_returns_ulid_string(ledger, make_event) -> None:
    event_id = ledger.append(make_event())
    assert isinstance(event_id, str) and ULID_RE.fullmatch(event_id), (
        f"append returned {event_id!r}: event ids are ULIDs — sortable, collision-free "
        "(DESIGN §3) — and every downstream reference (thesis links, snapshots) assumes it"
    )


def test_append_is_durable_across_instances(ledger, ledger_path, make_event) -> None:
    event_id = ledger.append(make_event(payload={"note": "durability probe", "salience": 1}))
    reopened = Ledger(ledger_path)  # fresh handle, no shared in-process state
    ids = [e.event_id for e in reopened.query(EventFilter())]
    assert event_id in ids, (
        "event vanished on reopen: append must commit durably to the db file, not buffer "
        "in the instance — the events table is the source of truth (§6, ledger docstring)"
    )


def test_verify_chain_ok_after_appends(ledger, make_event) -> None:
    for i in range(3):
        ledger.append(make_event(payload={"note": f"event {i}", "salience": 1}))
    report = ledger.verify_chain()
    assert report.ok, (
        f"untampered 3-event chain reported broken (first_bad_seq="
        f"{report.first_bad_seq}): a false positive here poisons every snapshot and "
        "D4 verification that starts with verify_chain (§6.2)"
    )


@pytest.mark.parametrize(
    ("column", "new_value"),
    [
        # EVERY column, per the test's own claim (§6.2 all-columns preimage;
        # reviewer gap 2 — two columns let a partial preimage pass silently).
        ("actor", "mallory"),
        ("payload", '{"tampered": true}'),
        ("ts_utc", "2030-01-01T00:00:00.000000+00:00"),
        ("type", "HaltCleared"),
        ("run_id", "mallory-run"),
        ("schema_ver", "999"),
    ],
)
def test_tampering_any_column_breaks_chain(
    ledger, ledger_path, make_event, raw_sql, column, new_value
) -> None:
    for i in range(3):
        ledger.append(make_event(payload={"note": f"event {i}", "salience": 1}))
    raw_sql(f"UPDATE events SET {column} = ? WHERE seq = 2", new_value)

    report = Ledger(ledger_path).verify_chain()
    assert not report.ok, (
        f"chain verified OK after tampering column {column!r}: the hash preimage must "
        "cover ALL columns, not just payload — a payload-only preimage lets an attacker "
        "rewrite actor/run_id/type invisibly (§6.2, G-review fix)"
    )
    assert report.first_bad_seq == 2, (
        f"first_bad_seq={report.first_bad_seq}, expected 2: the audit surface must "
        "localize the break to the first tampered row (verify_chain docstring)"
    )


def test_append_rejects_non_json_native_payload(ledger, make_event) -> None:
    from decimal import Decimal

    with pytest.raises(TypeError):
        ledger.append(make_event(payload={"price": Decimal("1.00")}))
    # Silent str-coercion would make the queried event differ from what the
    # producer held in memory — the source of truth must reject what it cannot
    # represent losslessly (reviewer D4, ASSUMPTIONS 10/21).


def test_verify_chain_on_empty_ledger(ledger) -> None:
    report = ledger.verify_chain()
    assert report.ok, (
        "empty ledger must verify clean — verify_chain is step 1 of `tk report snapshot` "
        "(§6.2) and a fresh install must not start life 'tampered'"
    )
    assert report.first_bad_seq is None


def test_second_instance_on_same_file_appends_fine(ledger, ledger_path, make_event) -> None:
    first = ledger.append(make_event(payload={"note": "writer one", "salience": 1}))
    second_ledger = Ledger(ledger_path)
    second = second_ledger.append(make_event(payload={"note": "writer two", "salience": 1}))

    ids = {e.event_id for e in ledger.query(EventFilter())}
    assert {first, second} <= ids, (
        "an event from one of two concurrent handles was lost: multi-process CLI topology "
        "means multiple Ledger instances on one file is the NORMAL case (TD-16 WAL + "
        "busy_timeout), not an error"
    )
    assert ledger.verify_chain().ok, (
        "hash chain broke across two instances: prev_hash linkage must survive "
        "interleaved writers (TD-16)"
    )


def test_run_id_stamped_from_env(ledger, make_event, monkeypatch) -> None:
    monkeypatch.setenv("TK_RUN_ID", "run-env-01")
    event_id = ledger.append(make_event(run_id=None))
    found = _find(ledger, event_id)
    assert found.run_id == "run-env-01", (
        f"persisted run_id={found.run_id!r}: TK_RUN_ID must stamp unstamped events at "
        "append or the experiment registry loses attribution for the whole session "
        "(TD-20, D15)"
    )


def test_explicit_run_id_beats_env(ledger, make_event, monkeypatch) -> None:
    monkeypatch.setenv("TK_RUN_ID", "run-env-01")
    event_id = ledger.append(make_event(run_id="run-explicit"))
    found = _find(ledger, event_id)
    assert found.run_id == "run-explicit", (
        f"persisted run_id={found.run_id!r}: append stamps from env ONLY when the event "
        "carries no run_id (append docstring) — overwriting an explicit id corrupts "
        "cross-run comparisons"
    )
