"""Thesis lifecycle state machine — draft, illegal transitions, immutability,
and event-derived state (DESIGN §10.1, SPRINT P2 batch A story 1).

Status: `thesis.draft/submit/approve/reject` are still unconditional
`NotImplementedError` stubs this batch (batch dispatch: "Failing tests +
stubs only") — every test below that calls a thesis verb is RED for that
reason. Assertions describe the REAL behavior the P2 dev pass implements
next, exactly the same red-phase discipline as
`tests/unit/mae/test_size_position_verb.py` (P1C batch A) and
`tests/unit/thesis/test_grading_engine.py`.

Harness-action pattern (CTO addendum): P2 has no `review` verb and no
broker-activation pipeline yet, so `ReviewCompleted`/`ThesisActivated` are
appended directly through `default_ledger()` as test-harness actions —
exactly what P3's `review.verify_claim` / broker fill pipeline will emit for
real. This mirrors `tests/unit/ledger/test_rebuild.py`'s existing
harness-append pattern, just reached through the public `tradekit.ledger`
seam instead of the `ledger` fixture, because these tests exercise thesis
verbs that internally call `ledger.default_ledger()`.

TK_DATA_DIR isolation: the suite-wide autouse fixture in `tests/conftest.py`
points `default_ledger()` at this test's own `tmp_path` — no import of
`tradekit.ledger._db`/`_projections` needed here, `raw_sql`/`ledger_path`
(from `tests/conftest.py`) resolve to the SAME file because they share the
SAME `tmp_path` fixture instance within one test.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from ulid import ULID

from tradekit import thesis
from tradekit.contracts import EventFilter
from tradekit.ledger import default_ledger


def _events(event_type: str):
    return default_ledger().query(EventFilter(types=[event_type]))


def _thesis_events(event_type: str, thesis_id: str):
    return [e for e in _events(event_type) if e.payload.get("thesis_id") == thesis_id]


def _append(make_event, event_type: str, payload: dict[str, Any]) -> None:
    """Harness action: append an event exactly as a not-yet-built P2/P3
    producer would (ReviewCompleted, ThesisActivated) — or as this test
    forces an already-reached state (ThesisSubmitted) without going through
    the (still-stubbed) verb, to test a LATER verb's illegal-transition
    guard in isolation."""
    default_ledger().append(make_event(type=event_type, payload=payload))


# ---------------------------------------------------------------------------
# draft
# ---------------------------------------------------------------------------


def test_draft_valid_contract_returns_id_and_appends_thesis_drafted(thesis_kwargs) -> None:
    thesis_id = thesis.draft(thesis_kwargs)
    assert isinstance(thesis_id, str) and thesis_id, "draft() must return a nonempty thesis_id"

    events = _thesis_events("ThesisDrafted", thesis_id)
    assert len(events) == 1, (
        f"expected exactly one ThesisDrafted event for {thesis_id!r}, got {len(events)}"
    )
    assert events[0].payload["contract"]["account_ref"] == thesis_kwargs["account_ref"], (
        "ThesisDrafted payload must carry the full validated contract (contracts._event_"
        "payloads.ThesisDraftedPayload.contract), not just the thesis_id"
    )


def test_draft_invalid_contract_raises_validation_error_and_appends_nothing(thesis_kwargs) -> None:
    del thesis_kwargs["ev_block"]  # SME F5: EV block is mandatory
    before = len(_events("ThesisDrafted"))
    with pytest.raises(ValidationError):
        thesis.draft(thesis_kwargs)
    assert len(_events("ThesisDrafted")) == before, (
        "an invalid contract must die at pydantic validation BEFORE any ledger append — a "
        "half-drafted thesis with no ThesisDrafted event is a worse failure mode than a "
        "clean raise"
    )


def test_draft_with_supersedes_links_payload_to_the_old_thesis(thesis_kwargs) -> None:
    old_id = thesis.draft(dict(thesis_kwargs))

    new_kwargs = dict(thesis_kwargs)
    new_kwargs["thesis_id"] = str(ULID())
    new_kwargs["supersedes"] = old_id  # extra key: not one of ThesisContract's §5.1 fields
    new_id = thesis.draft(new_kwargs)

    new_events = _thesis_events("ThesisDrafted", new_id)
    assert len(new_events) == 1
    assert new_events[0].payload["supersedes"] == old_id, (
        "§10.1: 'amendments mean a new thesis superseding the old, event-linked' — the "
        "NEW thesis's ThesisDrafted payload must carry supersedes=<old_id> (ASSUMPTIONS, "
        "this batch: `supersedes` is an extra key in the contract dict, outside "
        "ThesisContract's own §5.1 field list, that draft() reads and threads into the "
        "event payload)"
    )


# ---------------------------------------------------------------------------
# illegal transitions
# ---------------------------------------------------------------------------


def test_submit_on_already_submitted_raises_illegal_transition_naming_current_state(
    thesis_kwargs, make_event
) -> None:
    thesis_id = thesis.draft(thesis_kwargs)
    _append(
        make_event,
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
    )

    with pytest.raises(thesis.IllegalTransition) as exc:
        thesis.submit(thesis_id)
    assert exc.value.current_state == "submitted"
    assert exc.value.verb == "submit"


def test_approve_on_draft_raises_illegal_transition(thesis_kwargs) -> None:
    thesis_id = thesis.draft(thesis_kwargs)
    with pytest.raises(thesis.IllegalTransition) as exc:
        thesis.approve(thesis_id)
    assert exc.value.current_state == "draft"


def test_approve_on_submitted_not_yet_reviewed_raises_illegal_transition(
    thesis_kwargs, make_event
) -> None:
    thesis_id = thesis.draft(thesis_kwargs)
    _append(
        make_event,
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
    )
    with pytest.raises(thesis.IllegalTransition) as exc:
        thesis.approve(thesis_id)
    assert exc.value.current_state == "submitted"


def test_approve_after_review_completed_emits_thesis_approved(thesis_kwargs, make_event) -> None:
    thesis_id = thesis.draft(thesis_kwargs)
    _append(
        make_event,
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
    )
    _append(
        make_event,
        "ReviewCompleted",
        {"thesis_id": thesis_id, "review_artifact_id": "rev-1", "passed": True},
    )

    thesis.approve(thesis_id)

    approved = _thesis_events("ThesisApproved", thesis_id)
    assert len(approved) == 1, "approve() from `reviewed` must append exactly one ThesisApproved"
    assert approved[0].payload["review_artifact_id"] == "rev-1"


def test_reject_with_why_emits_thesis_rejected_and_is_terminal(thesis_kwargs, make_event) -> None:
    thesis_id = thesis.draft(thesis_kwargs)
    _append(
        make_event,
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
    )
    _append(
        make_event,
        "ReviewCompleted",
        {"thesis_id": thesis_id, "review_artifact_id": "rev-1", "passed": False},
    )

    thesis.reject(thesis_id, "unresolved attack: sizing not from size_position")

    rejected = _thesis_events("ThesisRejected", thesis_id)
    assert len(rejected) == 1
    assert rejected[0].payload["why"] == "unresolved attack: sizing not from size_position"

    # Terminal: ANY verb call after reject must be illegal, not just approve.
    with pytest.raises(thesis.IllegalTransition) as exc:
        thesis.approve(thesis_id)
    assert exc.value.current_state == "rejected"

    with pytest.raises(thesis.IllegalTransition) as exc2:
        thesis.submit(thesis_id)
    assert exc2.value.current_state == "rejected"


def test_reject_on_approved_raises_illegal_transition(thesis_kwargs, make_event) -> None:
    # §10.1's diagram: `reject` branches ONLY from `reviewed`
    # ("reviewed ─┬─approve→ approved ... └─reject→ rejected"); there is no
    # `approved ─reject→` edge at all. Pinned here, not flagged as ambiguous
    # — the diagram is unambiguous on this point (ASSUMPTIONS, this batch).
    thesis_id = thesis.draft(thesis_kwargs)
    _append(
        make_event,
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
    )
    _append(
        make_event,
        "ReviewCompleted",
        {"thesis_id": thesis_id, "review_artifact_id": "rev-1", "passed": True},
    )
    _append(
        make_event,
        "ThesisApproved",
        {"thesis_id": thesis_id, "review_artifact_id": "rev-1"},
    )

    with pytest.raises(thesis.IllegalTransition) as exc:
        thesis.reject(thesis_id, "changed my mind")
    assert exc.value.current_state == "approved"


# ---------------------------------------------------------------------------
# immutability + event-derived state
# ---------------------------------------------------------------------------


def test_no_verb_mutates_the_drafted_contract_across_the_full_lifecycle(
    thesis_kwargs, make_event
) -> None:
    thesis_id = thesis.draft(thesis_kwargs)
    drafted_before = _thesis_events("ThesisDrafted", thesis_id)[0]

    _append(
        make_event,
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
    )
    _append(
        make_event,
        "ReviewCompleted",
        {"thesis_id": thesis_id, "review_artifact_id": "rev-1", "passed": True},
    )
    thesis.approve(thesis_id)
    _append(
        make_event,
        "ThesisActivated",
        {"thesis_id": thesis_id, "order_id": "ord-1", "ts_utc": "2026-01-05T00:00:00Z"},
    )

    drafted_after = _thesis_events("ThesisDrafted", thesis_id)[0]
    assert drafted_after == drafted_before, (
        "there is no 'edit' verb (§10.1: 'after submit, the contract is immutable... "
        "amendments mean a new thesis superseding the old') — the ORIGINAL ThesisDrafted "
        "event must stay byte-identical across the whole lifecycle"
    )


def test_review_completed_events_do_not_clobber_state_guarded_transitions(
    thesis_kwargs, make_event, raw_sql
) -> None:
    """CTO adjudication, P2 batch B (ASSUMPTIONS 73) — state derivation must
    be a GUARDED (state, event) -> state table, not an unguarded
    event -> state map. Two pins, both against an ACTIVE thesis:

    1. A `ReviewCompleted(kind="thesis_review")` event appended while the
       thesis is active does NOT change the derived state (the
       submitted -> reviewed edge only exists FROM `submitted`; an
       out-of-order lifecycle event must leave state unchanged, never
       corrupt it — projections must be total over any event history).
    2. A `ReviewCompleted(kind="void_signoff")` NEVER causes a transition at
       all, from any state — it is `thesis.void`'s reviewer sign-off
       ARTIFACT (§10.4 guard 2), not a lifecycle edge.

    EXPECTED RED against batch-A src: `_machine._STATE_BY_EVENT_TYPE` (and
    the `theses` projection's `_THESIS_STATE_BY_EVENT_TYPE`) map ANY
    ReviewCompleted to "reviewed" unconditionally — that unguarded map is
    the latent batch-A defect this test exposes; the batch-B dev pass fixes
    `_machine` + `_projections` together."""
    thesis_id = thesis.draft(thesis_kwargs)
    _append(
        make_event,
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
    )
    _append(
        make_event,
        "ReviewCompleted",
        {"thesis_id": thesis_id, "review_artifact_id": "rev-1", "passed": True},
    )
    thesis.approve(thesis_id)
    _append(
        make_event,
        "ThesisActivated",
        {"thesis_id": thesis_id, "order_id": "ord-1", "ts_utc": "2026-01-05T00:00:00Z"},
    )

    # Pin 1: an out-of-order thesis_review while ACTIVE must not move state.
    _append(
        make_event,
        "ReviewCompleted",
        {
            "thesis_id": thesis_id,
            "review_artifact_id": "rev-2",
            "passed": True,
            "kind": "thesis_review",
        },
    )
    # Pin 2: a void_signoff is a sign-off artifact, never a lifecycle edge.
    _append(
        make_event,
        "ReviewCompleted",
        {
            "thesis_id": thesis_id,
            "review_artifact_id": "voidrev-1",
            "passed": True,
            "kind": "void_signoff",
        },
    )

    # Live path: approve() must still see ACTIVE (and therefore refuse) —
    # under the unguarded batch-A map it would wrongly see "reviewed" and
    # SUCCEED, appending a bogus second ThesisApproved.
    with pytest.raises(thesis.IllegalTransition) as exc:
        thesis.approve(thesis_id)
    assert exc.value.current_state == "active", (
        "derived state must still be 'active' after out-of-order/sign-off "
        "ReviewCompleted events — an unguarded event->state map lets ANY stray "
        "lifecycle event clobber state (the batch-A defect, ASSUMPTIONS 73)"
    )

    # Projection path: the theses read model must agree (D15/TD-4).
    default_ledger().rebuild()
    rows = raw_sql("SELECT state FROM theses WHERE thesis_id = ?", thesis_id)
    assert len(rows) == 1
    assert rows[0][0] == "active"


def test_state_derived_via_projection_matches_the_live_illegal_transition_path(
    thesis_kwargs, make_event, raw_sql
) -> None:
    thesis_id = thesis.draft(thesis_kwargs)
    _append(
        make_event,
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
    )
    _append(
        make_event,
        "ReviewCompleted",
        {"thesis_id": thesis_id, "review_artifact_id": "rev-1", "passed": True},
    )
    thesis.approve(thesis_id)

    # Live path: an illegal verb call surfaces the CURRENT state, computed
    # from the event log at call time.
    with pytest.raises(thesis.IllegalTransition) as exc:
        thesis.approve(thesis_id)  # already approved
    live_state = exc.value.current_state

    # Projection path: same state, derived purely from `tk ledger rebuild`
    # replaying the SAME event log through the `theses` read model — DESIGN
    # §10.1: "State is DERIVED from events only".
    default_ledger().rebuild()
    rows = raw_sql("SELECT state FROM theses WHERE thesis_id = ?", thesis_id)
    assert len(rows) == 1
    assert rows[0][0] == live_state, (
        "the theses PROJECTION must agree with the LIVE (event-log-derived) path on "
        f"{thesis_id!r}'s state — a divergence here means state secretly lives somewhere "
        "other than the event log (D15/TD-4 violation)"
    )
