"""tradekit.thesis — thesis lifecycle + grading (DESIGN §10, TD-9).

Deep interface: six verbs, per the §4.2 pins. The grading ARITHMETIC
(_grading.py) is pre-built and fully tested; P2 wires it into grade() along
with the event-sourced state machine — see
docs/handoff/SPRINT-P2-thesis-policy.md.

Batch A (this pass) implements draft/submit/approve/reject; grade/void stay
`NotImplementedError` stubs until batch B. State is DERIVED from the event
log on every call (never cached in a module variable — DESIGN §10.1,
`_machine.derive_state`); internals (state derivation/guards, submit's
snapshot/sizing/EV mechanics) live in `_machine.py`/`_submit.py` per the
house deep-module style — this module stays thin verb bodies only.
"""

from __future__ import annotations

from typing import Any

from ulid import ULID

from tradekit.contracts import (
    Event,
    ThesisApprovedPayload,
    ThesisContract,
    ThesisDraftedPayload,
    ThesisRejectedPayload,
)
from tradekit.ledger import Ledger, default_ledger
from tradekit.mae import _runtime as _mae_runtime
from tradekit.thesis import _machine, _submit
from tradekit.thesis._machine import IllegalTransition

# 'agent:<model>' | 'mike' | 'system:<job>' — every event this module
# produces is a machine-derived transition, not an LLM or human action.
_ACTOR = "system:thesis"


def _append(ledger: Ledger, event_type: str, payload: dict[str, Any]) -> str:
    event = Event(
        event_id=str(ULID()),
        ts_utc=_mae_runtime.clock(),
        type=event_type,  # type: ignore[arg-type]  # narrowed by callers below
        actor=_ACTOR,
        run_id=None,
        schema_ver=1,
        payload=payload,
    )
    return ledger.append(event)


def draft(contract: dict[str, Any]) -> str:
    """Validate a ThesisContract and ledger ThesisDrafted; returns thesis_id.

    `contract` may carry an extra `supersedes` key (not one of
    `ThesisContract`'s §5.1 fields) linking this draft to the thesis it
    amends (ASSUMPTIONS, SPRINT P2 batch A — ratified as temporary/permanent
    per the batch's dev-pass note). It is popped BEFORE `ThesisContract`
    validation so an invalid contract still dies at pydantic validation,
    before any ledger append.
    """
    contract_kwargs = dict(contract)
    supersedes = contract_kwargs.pop("supersedes", None)
    thesis_contract = ThesisContract(**contract_kwargs)

    payload = ThesisDraftedPayload(
        thesis_id=thesis_contract.thesis_id,
        contract=thesis_contract.model_dump(mode="json"),
        supersedes=supersedes,
    )
    ledger = default_ledger()
    _append(ledger, "ThesisDrafted", payload.model_dump(mode="json"))
    return thesis_contract.thesis_id


def submit(thesis_id: str) -> None:
    """Snapshot market, record sizing, resolve+quantize predicates, validate
    EV — legal only from `draft` (DESIGN §10.1). Validates EVERYTHING first
    (`_submit.build_submit_payloads`), then appends, IN ORDER,
    MarketSnapshotTaken -> SizingComputed -> ThesisSubmitted (the transition
    marker LAST — ASSUMPTIONS 65)."""
    ledger = default_ledger()
    _machine.require_state(ledger, thesis_id, frozenset({"draft"}), "submit")
    drafted = _machine.latest_payload(ledger, thesis_id, "ThesisDrafted")
    if drafted is None:  # pragma: no cover — require_state already proved draft exists
        raise ValueError(f"no ThesisDrafted event found for thesis_id={thesis_id!r}")

    snapshot_payload, sizing_payload, submitted_payload = _submit.build_submit_payloads(
        thesis_id, drafted["contract"]
    )
    _append(ledger, "MarketSnapshotTaken", snapshot_payload.model_dump(mode="json"))
    _append(ledger, "SizingComputed", sizing_payload.model_dump(mode="json"))
    _append(ledger, "ThesisSubmitted", submitted_payload.model_dump(mode="json"))


def approve(thesis_id: str) -> None:
    """Legal only from `reviewed` (DESIGN §10.1) — appends ThesisApproved,
    carrying forward the `ReviewCompleted` event's `review_artifact_id`."""
    ledger = default_ledger()
    _machine.require_state(ledger, thesis_id, frozenset({"reviewed"}), "approve")
    review = _machine.latest_payload(ledger, thesis_id, "ReviewCompleted")
    if review is None:  # pragma: no cover — require_state already proved reviewed exists
        raise ValueError(f"no ReviewCompleted event found for thesis_id={thesis_id!r}")

    payload = ThesisApprovedPayload(
        thesis_id=thesis_id, review_artifact_id=str(review["review_artifact_id"])
    )
    _append(ledger, "ThesisApproved", payload.model_dump(mode="json"))


def reject(thesis_id: str, why: str) -> None:
    """Legal only from `reviewed` (§10.1's diagram has no `approved -reject->`
    edge — ASSUMPTIONS 64) — terminal; appends ThesisRejected."""
    ledger = default_ledger()
    _machine.require_state(ledger, thesis_id, frozenset({"reviewed"}), "reject")

    payload = ThesisRejectedPayload(thesis_id=thesis_id, why=why)
    _append(ledger, "ThesisRejected", payload.model_dump(mode="json"))


def grade(thesis_id: str) -> dict[str, Any]:
    """Arithmetic grading vs market data; wraps _grading.evaluate_criteria."""
    raise NotImplementedError("P2 batch B — docs/handoff/SPRINT-P2-thesis-policy.md")


def void(thesis_id: str, attestation: str) -> None:
    """Structural invalidation: needs attestation + reviewer sign-off (§10.4)."""
    raise NotImplementedError("P2 batch B — docs/handoff/SPRINT-P2-thesis-policy.md")


__all__ = ["IllegalTransition", "approve", "draft", "grade", "reject", "submit", "void"]
