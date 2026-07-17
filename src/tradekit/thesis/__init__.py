"""tradekit.thesis — thesis lifecycle + grading (DESIGN §10, TD-9).

Deep interface: six verbs, per the §4.2 pins. The grading ARITHMETIC
(_grading.py) is pre-built and fully tested; P2 wires it into grade() along
with the event-sourced state machine — see
docs/handoff/SPRINT-P2-thesis-policy.md.
"""

from __future__ import annotations

from typing import Any


class IllegalTransition(Exception):
    """Raised by any thesis verb invoked from a state that doesn't permit it
    (DESIGN §10.1). Additive public surface — same shape as
    `contracts._event_payloads` widening `contracts`' interface (ASSUMPTIONS,
    SPRINT P2 batch A): `thesis`'s interface IS its verbs plus the typed
    error they can raise, so exporting this is not a DESIGN §1 violation.

    ``current_state`` names the state the thesis was actually in (as derived
    from the `theses` projection / event log — DESIGN §10.1: "Illegal
    transitions raise IllegalTransition naming current state"); ``verb`` is
    the verb name that was rejected.
    """

    def __init__(self, current_state: str, verb: str) -> None:
        super().__init__(f"cannot {verb!r} a thesis in state {current_state!r}")
        self.current_state = current_state
        self.verb = verb


def draft(contract: dict[str, Any]) -> str:
    """Validate a ThesisContract and ledger ThesisDrafted; returns thesis_id."""
    raise NotImplementedError("P2 — docs/handoff/SPRINT-P2-thesis-policy.md")


def submit(thesis_id: str) -> None:
    """Snapshot market, record sizing, resolve+quantize predicates, validate EV."""
    raise NotImplementedError("P2 — docs/handoff/SPRINT-P2-thesis-policy.md")


def approve(thesis_id: str) -> None:
    raise NotImplementedError("P2 — docs/handoff/SPRINT-P2-thesis-policy.md")


def reject(thesis_id: str, why: str) -> None:
    raise NotImplementedError("P2 — docs/handoff/SPRINT-P2-thesis-policy.md")


def grade(thesis_id: str) -> dict[str, Any]:
    """Arithmetic grading vs market data; wraps _grading.evaluate_criteria."""
    raise NotImplementedError("P2 — docs/handoff/SPRINT-P2-thesis-policy.md")


def void(thesis_id: str, attestation: str) -> None:
    """Structural invalidation: needs attestation + reviewer sign-off (§10.4)."""
    raise NotImplementedError("P2 — docs/handoff/SPRINT-P2-thesis-policy.md")


__all__ = ["IllegalTransition", "approve", "draft", "grade", "reject", "submit", "void"]
