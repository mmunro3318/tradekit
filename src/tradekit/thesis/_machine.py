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

# One state per lifecycle-marker event type (DESIGN §10.1's diagram, minus
# `ThesisGraded`'s outcome-keyed terminal states — handled separately below).
_STATE_BY_EVENT_TYPE: dict[str, str] = {
    "ThesisDrafted": "draft",
    "ThesisSubmitted": "submitted",
    "ReviewCompleted": "reviewed",
    "ThesisApproved": "approved",
    "ThesisRejected": "rejected",
    "ThesisActivated": "active",
}

# `ThesisGraded` is intentionally excluded from `_STATE_BY_EVENT_TYPE`: batch
# A/B doesn't grade yet, but `derive_state` below still handles it defensively
# (via the event's own `outcome` field) so a later batch's grade() doesn't
# have to touch this module.
THESIS_EVENT_TYPES: tuple[str, ...] = (*_STATE_BY_EVENT_TYPE, "ThesisGraded")


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


def thesis_events(ledger: Ledger, thesis_id: str) -> list[Event]:
    """This thesis's own lifecycle events, in seq (append) order."""
    events = ledger.query(EventFilter(types=list(THESIS_EVENT_TYPES)))
    return [event for event in events if event.payload.get("thesis_id") == thesis_id]


def derive_state(ledger: Ledger, thesis_id: str) -> str:
    """Replay `thesis_id`'s own events to the CURRENT state.

    Raises `ValueError` if no `ThesisDrafted` event exists for `thesis_id`
    (there is no such thesis — a caller bug, not an `IllegalTransition`: the
    latter requires a real current state to name).
    """
    state: str | None = None
    for event in thesis_events(ledger, thesis_id):
        if event.type == "ThesisGraded":
            state = str(event.payload.get("outcome", "graded"))
        else:
            state = _STATE_BY_EVENT_TYPE[event.type]
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
