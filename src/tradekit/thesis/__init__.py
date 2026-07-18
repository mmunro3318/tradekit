"""tradekit.thesis — thesis lifecycle + grading (DESIGN §10, TD-9).

Deep interface: six verbs, per the §4.2 pins. The grading ARITHMETIC
(_grading.py) is pre-built and fully tested; P2 wires it into grade() along
with the event-sourced state machine — see
docs/handoff/SPRINT-P2-thesis-policy.md.

Batch A implemented draft/submit/approve/reject; batch B (this pass) wires
grade/void. State is DERIVED from the event log on every call (never cached
in a module variable — DESIGN §10.1, `_machine.derive_state`); internals
(state derivation/guards, submit's snapshot/sizing/EV mechanics, grade's
bar-fetch/pnl arithmetic) live in `_machine.py`/`_submit.py`/
`_grade_wiring.py` per the house deep-module style — this module stays thin
verb bodies only.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from ulid import ULID

from tradekit.contracts import (
    Event,
    EventFilter,
    InvalidationAttestedPayload,
    ThesisApprovedPayload,
    ThesisContract,
    ThesisDraftedPayload,
    ThesisGradedPayload,
    ThesisRejectedPayload,
)
from tradekit.ledger import Ledger, default_ledger
from tradekit.mae import _runtime as _mae_runtime
from tradekit.thesis import _grade_wiring, _machine, _submit
from tradekit.thesis._machine import IllegalTransition, VoidRefused

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
    """Arithmetic grading vs market data — legal only from `active` (CTO
    addendum story-2 pins: "active only"). Fetches bars via the sanctioned
    `mae._runtime` seam over [activation_ts, now] at the thesis's own
    predicate timeframe, calls the FROZEN `_grading.evaluate_criteria`
    (never reimplemented), computes pnl net of fees from `FillRecorded`
    events, and appends `ThesisGraded` carrying every predicate's measured
    value + bar refs (`outcome.evaluated`, verbatim) plus `ambiguous_bar`.

    Returns the just-appended `ThesisGraded` payload, `model_dump`'d
    (ASSUMPTIONS 67 — same convention as `draft()` returning the id it just
    minted: the ledgered event is the source of truth, the return value a
    convenience mirror of it)."""
    ledger = default_ledger()
    _machine.require_state(ledger, thesis_id, frozenset({"active"}), "grade")
    drafted = _machine.latest_payload(ledger, thesis_id, "ThesisDrafted")
    if drafted is None:  # pragma: no cover — require_state already proved active exists
        raise ValueError(f"no ThesisDrafted event found for thesis_id={thesis_id!r}")
    activated = _machine.latest_payload(ledger, thesis_id, "ThesisActivated")
    if activated is None:  # pragma: no cover — require_state already proved active
        raise ValueError(f"no ThesisActivated event found for thesis_id={thesis_id!r}")

    contract = drafted["contract"]
    asset = contract["asset"]
    symbol = str(asset["symbol"])
    tick_size = Decimal(str(asset["tick_size"]))
    activation_ts = datetime.fromisoformat(str(activated["ts_utc"]))
    horizon_end = datetime.fromisoformat(str(contract["horizon_end"]))

    outcome = _grade_wiring.evaluate(
        symbol=symbol,
        tick_size=tick_size,
        success=contract["success_criteria"],
        failure=contract["failure_criteria"],
        invalidation=contract["invalidation"],
        horizon_end=horizon_end,
        activation_ts=activation_ts,
    )
    result = outcome.result
    if result == "PENDING":
        raise ValueError(
            f"thesis_id={thesis_id!r} is not yet gradeable — still PENDING "
            "(horizon not reached, no predicate triggered)"
        )

    pnl = _grade_wiring.compute_pnl(ledger, thesis_id, str(contract["direction"]))
    payload = ThesisGradedPayload(
        thesis_id=thesis_id,
        outcome=result,
        measured=outcome.evaluated,
        ambiguous_bar=outcome.ambiguous_bar,
        pnl_usd=pnl,
        graded_ts=_mae_runtime.clock(),
    )
    _append(ledger, "ThesisGraded", payload.model_dump(mode="json"))
    return payload.model_dump(mode="json")


def void(thesis_id: str, attestation: str) -> None:
    """Discretionary structural-invalidation path (§10.4 guard 2) — legal
    only from `approved`/`active`. Measurable invalidations are rejected
    immediately with ZERO appends (they auto-VOID inside `grade()` with zero
    discretion — this is not that path). Sequence for a structural
    invalidation: append `InvalidationAttested` FIRST, then check for an
    existing reviewer sign-off (`ReviewCompleted(kind="void_signoff")`) for
    this thesis — absent -> raise `VoidRefused` (the attestation event
    REMAINS, the audit trail of a refused void); present -> append
    `ThesisGraded(VOID)`."""
    ledger = default_ledger()
    _machine.require_state(ledger, thesis_id, frozenset({"approved", "active"}), "void")
    drafted = _machine.latest_payload(ledger, thesis_id, "ThesisDrafted")
    if drafted is None:  # pragma: no cover — require_state already proved a real thesis
        raise ValueError(f"no ThesisDrafted event found for thesis_id={thesis_id!r}")
    contract = drafted["contract"]
    invalidation = contract["invalidation"]
    kind = invalidation["kind"]
    if kind != "structural":
        raise VoidRefused(
            thesis_id,
            f"invalidation kind={kind!r} is not structural — measurable invalidations "
            "auto-VOID inside grade() with zero discretion, never through void()",
        )

    attested_payload = InvalidationAttestedPayload(
        thesis_id=thesis_id, kind="structural", attestation=attestation
    )
    _append(ledger, "InvalidationAttested", attested_payload.model_dump(mode="json"))

    if not _has_void_signoff(ledger, thesis_id):
        raise VoidRefused(
            thesis_id,
            "no reviewer sign-off (ReviewCompleted kind='void_signoff') found for this "
            "thesis — the attestation above stands as the audit trail of this refusal",
        )

    graded_payload = ThesisGradedPayload(
        thesis_id=thesis_id,
        outcome="VOID",
        measured=[],
        ambiguous_bar=False,
        pnl_usd=_grade_wiring.compute_pnl(ledger, thesis_id, str(contract["direction"])),
        graded_ts=_mae_runtime.clock(),
    )
    _append(ledger, "ThesisGraded", graded_payload.model_dump(mode="json"))


def _has_void_signoff(ledger: Ledger, thesis_id: str) -> bool:
    """A PASSING `ReviewCompleted(kind="void_signoff", passed=True)` event
    exists for `thesis_id` (§10.4 guard 2's reviewer sign-off artifact —
    CTO adjudication, ASSUMPTIONS 73). `passed` MUST be checked here (SPRINT
    P3 batch D fix): `review.verify_claim`'s real pipeline (ASSUMPTIONS
    round-20) ledgers a `ReviewCompleted(kind="void_signoff")` event on a
    FAILED sign-off too (`passed=False` — the same "artifact vs
    pointer-event" shape as a pass, per DESIGN §12.1), so a passed-blind
    existence check would let a rubric-failed or boundary-failed sign-off
    satisfy this guard — `tests/unit/review/test_verify_claim.py::
    test_verify_claim_void_signoff_fail_leaves_thesis_void_still_refused`
    pins that a failed sign-off must leave `void()` refused."""
    return any(
        event.payload.get("thesis_id") == thesis_id
        and event.payload.get("kind") == "void_signoff"
        and event.payload.get("passed") is True
        for event in ledger.query(EventFilter(types=["ReviewCompleted"]))
    )


__all__ = [
    "IllegalTransition",
    "VoidRefused",
    "approve",
    "draft",
    "grade",
    "reject",
    "submit",
    "void",
]
