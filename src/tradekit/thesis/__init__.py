"""tradekit.thesis — thesis lifecycle + grading (DESIGN §10, TD-9).

Deep interface: six verbs, per the §4.2 pins. The grading ARITHMETIC
(_grading.py) is pre-built and fully tested; P2 wires it into grade() along
with the event-sourced state machine — see
docs/handoff/SPRINT-P2-thesis-policy.md.
"""

from __future__ import annotations

from typing import Any


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


__all__ = ["approve", "draft", "grade", "reject", "submit", "void"]
