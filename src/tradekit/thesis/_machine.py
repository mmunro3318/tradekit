"""State derivation + transition guards for `tradekit.thesis` (DESIGN §10.1).

Deliberately private: state is DERIVED from the event log at call time by
replaying a single thesis's own events (queried by `thesis_id`, in `seq`
order — `Ledger.query` already returns rows ordered that way) rather than
read from the `theses` projection. This is the "live path" the CTO addendum
requires to agree with the `theses` projection's own rebuild-time derivation
(`ledger._projections._apply`) — see
`tests/unit/thesis/test_lifecycle.py::
test_state_derived_via_projection_matches_the_live_illegal_transition_path`.

Every verb in `tradekit.thesis.__init__` calls `require_state` before doing
anything else observable (ASSUMPTIONS 65's validate-before-append pin).
"""

from __future__ import annotations

from typing import Any

from tradekit.contracts import Event, EventFilter
from tradekit.ledger import Ledger

# Event types that ever carry lifecycle-relevant information for a thesis
# (used to scope `thesis_events`'s ledger query). Kept flat/simple; the
# actual (state, event) -> state GUARD table lives in `_next_state` below —
# ASSUMPTIONS 73 (P2 batch B, CTO adjudication): batch A's unguarded
# event-type -> state map let ANY out-of-order lifecycle event (e.g. a stray
# `ReviewCompleted` appended while `active`) clobber derived state; that is
# the latent defect this batch fixes.
THESIS_EVENT_TYPES: tuple[str, ...] = (
    "ThesisDrafted",
    "ThesisSubmitted",
    "ReviewCompleted",
    "ThesisApproved",
    "ThesisRejected",
    "ThesisActivated",
    "ThesisGraded",
)

# (from_state, event_type) -> to_state, for the "simple" one-shot lifecycle
# markers — every one of these ONLY fires from its single legal source state
# (DESIGN §10.1's diagram); an event whose current state doesn't match its
# key is a no-op (state stays unchanged). `ReviewCompleted` and
# `ThesisGraded` are NOT here — both need extra payload-driven logic
# (`kind` / `outcome`), handled directly in `_next_state`.
_SIMPLE_TRANSITIONS: dict[tuple[str, str], str] = {
    ("draft", "ThesisSubmitted"): "submitted",
    ("reviewed", "ThesisApproved"): "approved",
    ("reviewed", "ThesisRejected"): "rejected",
    ("approved", "ThesisActivated"): "active",
}


def _next_state(current: str | None, event: Event) -> str | None:
    """One step of the GUARDED (state, event) -> state machine (ASSUMPTIONS
    73). Total: any event, from any current state (including `None` — no
    `ThesisDrafted` seen yet), either advances state along a legal edge or
    leaves it unchanged. Never raises — `derive_state` is the layer that
    turns "no state at all" into a `ValueError`."""
    event_type = event.type
    if event_type == "ThesisDrafted":
        return "draft"
    if event_type == "ReviewCompleted":
        kind = event.payload.get("kind", "thesis_review")
        if kind != "thesis_review":
            # A `void_signoff` sign-off artifact is NEVER a lifecycle edge,
            # from any state (ASSUMPTIONS 73 pin 2).
            return current
        return "reviewed" if current == "submitted" else current
    if event_type == "ThesisGraded":
        # `grade()`/`void()` only ever append this from `active` (their own
        # `require_state` guards already enforce that live-path); guard it
        # here too so a harness-appended/out-of-order ThesisGraded can never
        # clobber state from anywhere else.
        if current == "active":
            return str(event.payload.get("outcome", current))
        return current
    if current is not None:
        to_state = _SIMPLE_TRANSITIONS.get((current, event_type))
        if to_state is not None:
            return to_state
    return current


class IllegalTransition(Exception):
    """Raised by any thesis verb invoked from a state that doesn't permit it
    (DESIGN §10.1). Re-exported (unchanged shape) from `tradekit.thesis`.

    ``current_state`` names the state the thesis was actually in (as derived
    from the event log — DESIGN §10.1: "Illegal transitions raise
    IllegalTransition naming current state"); ``verb`` is the verb name that
    was rejected.
    """

    def __init__(self, current_state: str, verb: str) -> None:
        super().__init__(f"cannot {verb!r} a thesis in state {current_state!r}")
        self.current_state = current_state
        self.verb = verb


class VoidRefused(Exception):
    """Raised by `thesis.void` when a structural invalidation is attested
    but no reviewer sign-off (`ReviewCompleted(kind="void_signoff")`) exists
    yet for this thesis (DESIGN §10.4 guard 2). Re-exported (unchanged
    shape) from `tradekit.thesis` (ASSUMPTIONS 72 — additive surface).

    The `InvalidationAttested` event REMAINS ledgered when this is raised —
    that event IS the audit trail of a refused void, not a rolled-back
    attempt (CTO addendum, story-2 pins)."""

    def __init__(self, thesis_id: str, reason: str) -> None:
        super().__init__(f"void refused for thesis_id={thesis_id!r}: {reason}")
        self.thesis_id = thesis_id
        self.reason = reason


def thesis_events(ledger: Ledger, thesis_id: str) -> list[Event]:
    """This thesis's own lifecycle events, in seq (append) order."""
    events = ledger.query(EventFilter(types=list(THESIS_EVENT_TYPES)))
    return [event for event in events if event.payload.get("thesis_id") == thesis_id]


def derive_state(ledger: Ledger, thesis_id: str) -> str:
    """Replay `thesis_id`'s own events, through the GUARDED (state, event) ->
    state machine (`_next_state`), to the CURRENT state.

    Raises `ValueError` if no `ThesisDrafted` event exists for `thesis_id`
    (there is no such thesis — a caller bug, not an `IllegalTransition`: the
    latter requires a real current state to name).
    """
    state: str | None = None
    for event in thesis_events(ledger, thesis_id):
        state = _next_state(state, event)
    if state is None:
        raise ValueError(f"no ThesisDrafted event found for thesis_id={thesis_id!r}")
    return state


def require_state(
    ledger: Ledger, thesis_id: str, allowed: frozenset[str], verb: str
) -> str:
    """Derive the current state and raise `IllegalTransition(state, verb)`
    unless it is in `allowed`. Returns the state on success (callers that
    also need it, e.g. to fetch the latest payload of the state's own
    marker event, avoid a second derivation)."""
    state = derive_state(ledger, thesis_id)
    if state not in allowed:
        raise IllegalTransition(state, verb)
    return state


def latest_payload(ledger: Ledger, thesis_id: str, event_type: str) -> dict[str, Any] | None:
    """The payload of the most recent `event_type` event for `thesis_id`, or
    `None` if it has never occurred."""
    matches = [event for event in thesis_events(ledger, thesis_id) if event.type == event_type]
    return matches[-1].payload if matches else None
