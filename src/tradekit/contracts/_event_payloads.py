"""Typed per-event payload models (DESIGN §6.3, ASSUMPTIONS 10, SPRINT P2
batch A).

The P0 ledger envelope (`Event.payload`) stays a plain JSON `dict` — that
part of ASSUMPTIONS 10 is unchanged. What lands here are the PRODUCER-side
models for the thesis-lifecycle slice of the §6.3 taxonomy: a producing verb
constructs the typed model (so a typo'd or missing field dies at
construction time, not silently as an unqueryable dict), then persists it
via ``model_dump(mode="json")`` into the event envelope's ``payload`` dict.
Consumers (projections) read the DICT — they never import these models, per
the same ratified split (`_projections.py`'s docstring, ASSUMPTIONS 10).

House style, same as every other `contracts` model: frozen
(`StrictFrozenModel` — ``extra="forbid"`` so a stray/typo'd field dies here
rather than being silently dropped on the JSON round trip), `Decimal` for
every money/price field (accepts `Decimal`, `str`, or JSON number, per
pydantic's normal `Decimal` coercion), `AwareDatetime` for every timestamp
(naive datetimes are a `ValidationError`, TD-17/ASSUMPTIONS 20).

Scope note (this is the one contracts submodule this batch fully
IMPLEMENTS rather than stubs — batch dispatch: "contracts are cheap and
tests need to construct them"): semantics for the fields that only matter
once grading/void/policy land (`ThesisGradedPayload`'s `outcome`,
`GateViolationDetectedPayload`'s rule linkage) are filled in by batch B/C,
but the SHAPE is pinned now so producers in later batches don't reshape an
already-ledgered event type.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import AwareDatetime, Field

from tradekit.contracts._base import StrictFrozenModel


class ThesisDraftedPayload(StrictFrozenModel):
    """Producer: `thesis.draft`. `contract` is the full `ThesisContract`,
    `model_dump(mode="json")`'d — the payload carries the WHOLE contract so a
    reader never needs a second lookup to see what was drafted. `supersedes`
    links an amendment thesis to the one it replaces (§10.1: "amendments mean
    a new thesis superseding the old, event-linked") — `ThesisContract` itself
    has no `supersedes` field (§5.1's pinned field list), so this is where the
    link lives (ASSUMPTIONS, this batch)."""

    thesis_id: str
    contract: dict[str, Any]
    supersedes: str | None = None


class MarketSnapshotTakenPayload(StrictFrozenModel):
    """Producer: `thesis.submit` (CTO addendum, story-1 pins: "Snapshot
    (MVP): last CLOSED daily bar for the asset ... + regime state; payload
    carries snapshot_id, symbol, ts, last_close, source"). `thesis_id` is
    included so the event ITSELF carries the thesis<->snapshot linkage (the
    addendum: "the canonical linkage is the EVENT (thesis_id +
    snapshot_id)") without requiring a second query against the contract."""

    thesis_id: str
    snapshot_id: str
    symbol: str
    ts: AwareDatetime
    last_close: Decimal
    source: str


class SizingComputedPayload(StrictFrozenModel):
    """Producer: `thesis.submit`, calling `mae.size_position` (R-012 compares
    submitted order size against THIS event, verbatim — TD-11/F6). `sizing`
    is `mae.size_position`'s raw output dict, recorded AS-IS (mae's numerics
    are float per DESIGN §13 "float only inside mae._indicators/_metrics";
    re-typing them to Decimal here would silently diverge from what
    `size_position` actually returned, defeating the "verbatim" purity
    guarantee) — loose `dict[str, Any]` is deliberate, not a shortcut."""

    thesis_id: str
    symbol: str
    account_equity_usd: Decimal
    sizing: dict[str, Any]


class ThesisSubmittedPayload(StrictFrozenModel):
    """Producer: `thesis.submit` — the transition marker, LAST in the
    submit sequence (CTO addendum). Carries the quantized (tick-grid)
    resolved predicate values and the EV validation numbers, so a reader can
    audit "what did we actually validate against" without re-deriving it
    from the (immutable) contract's raw predicates."""

    thesis_id: str
    market_snapshot_id: str
    resolved_target_price: Decimal
    resolved_stop_price: Decimal
    resolved_success_criteria: list[dict[str, Any]]
    resolved_failure_criteria: list[dict[str, Any]]
    ev_stated_usd: Decimal
    ev_recomputed_usd: Decimal


class ReviewCompletedPayload(StrictFrozenModel):
    """Producer: `tradekit.review` (P3) — P2 has no review verb; tests append
    this as a harness action to reach the `reviewed` state (CTO addendum).

    `kind` (CTO adjudication, P2 batch B — ASSUMPTIONS 73): one event type,
    two review artifacts. `"thesis_review"` (the default — additive, so every
    pre-existing payload keeps validating) is the pre-approval adversarial
    review that drives the draft->submitted->REVIEWED state transition.
    `"void_signoff"` is the reviewer sign-off artifact `thesis.void`'s second
    guard requires (§10.4) — it is NOT a lifecycle edge and must NEVER cause
    a state transition (state derivation is a GUARDED (state, event)->state
    table, not an unguarded event->state map — the batch-A unguarded map was
    a flagged defect, see ASSUMPTIONS 73)."""

    thesis_id: str
    review_artifact_id: str
    passed: bool
    kind: Literal["thesis_review", "void_signoff"] = "thesis_review"


class ThesisApprovedPayload(StrictFrozenModel):
    """Producer: `thesis.approve` (only legal from `reviewed`, §10.1)."""

    thesis_id: str
    review_artifact_id: str


class ThesisRejectedPayload(StrictFrozenModel):
    """Producer: `thesis.reject` — terminal (§10.1); `why` is mandatory and
    nonempty (an unreasoned rejection is unauditable, same spirit as
    `StructuralInvalidation.description`'s `min_length=1`, ASSUMPTIONS 8)."""

    thesis_id: str
    why: str = Field(min_length=1)


class ThesisActivatedPayload(StrictFrozenModel):
    """Producer: P3's broker pipeline, on the thesis's first Fill — P2 tests
    append this as a harness action to reach `active` for grading (CTO
    addendum, same shape as `ReviewCompleted`)."""

    thesis_id: str
    order_id: str
    ts_utc: AwareDatetime


class InvalidationAttestedPayload(StrictFrozenModel):
    """Producer: `thesis.void` (structural path only, §10.4 guard 2 — batch
    B implements the verb; the shape lands now). `kind` mirrors
    `InvalidationSpec.kind` (ASSUMPTIONS 4) so a reader can tell a structural
    attestation from a (rarer, auto-VOID-inside-grade) measurable one without
    cross-referencing the contract."""

    thesis_id: str
    kind: Literal["measurable", "structural"]
    attestation: str = Field(min_length=1)


class ThesisGradedPayload(StrictFrozenModel):
    """Producer: `thesis.grade` (batch B). Shape lands now so later batches
    never reshape an already-ledgered event type; `outcome`/`measured`/
    `ambiguous_bar`/`pnl_usd` semantics are batch B's job (§10.2/§10.3),
    mirroring `contracts.CriteriaOutcome` + `Grade`'s existing fields.

    `pnl_usd` is NULLABLE (CTO adjudication, P2 batch B — ASSUMPTIONS 71): a
    graded thesis with zero `FillRecorded` events has NO realized pnl, and
    `Decimal("0")` would fabricate a break-even datapoint that batch D's
    series-expectancy math would silently ingest. `None` means "no fills to
    account" (anti-fabrication); batch D must EXCLUDE None-pnl theses from
    expectancy, never coerce them to zero. Still a required field — a
    producer must say None explicitly, not forget the field."""

    thesis_id: str
    outcome: Literal["PASS", "FAIL", "VOID"]
    measured: list[dict[str, Any]] = Field(default_factory=list)
    ambiguous_bar: bool = False
    pnl_usd: Decimal | None
    graded_ts: AwareDatetime


class GateViolationDetectedPayload(StrictFrozenModel):
    """Producer: `policy.evaluate` (batch C) on any `deny` verdict — feeds
    R-015's void-rate audit and the promotion ladder's "process-compliant"
    definition (§7.2/§7.3). Shape lands now for the same forward-compat
    reason as `ThesisGradedPayload`."""

    rule_id: str
    account_ref: str
    thesis_id: str | None = None
    measured: str | None = None
    limit: str | None = None
    why: str = Field(min_length=1)


class HaltSetPayload(StrictFrozenModel):
    """Producer: `policy.halt` / an automatic reconcile-mismatch halt (§8.2
    step 7, R-001). `scope="all"` is the MVP default — per-account halts are
    an open extension, not pinned this batch."""

    reason: str = Field(min_length=1)
    scope: str = "all"
    set_by: str


class HaltClearedPayload(StrictFrozenModel):
    """Producer: `policy.resume`. `halt_event_id` links back to the
    `HaltSet` event being cleared, when known."""

    reason: str = Field(min_length=1)
    halt_event_id: str | None = None
    cleared_by: str


__all__ = [
    "GateViolationDetectedPayload",
    "HaltClearedPayload",
    "HaltSetPayload",
    "InvalidationAttestedPayload",
    "MarketSnapshotTakenPayload",
    "ReviewCompletedPayload",
    "SizingComputedPayload",
    "ThesisActivatedPayload",
    "ThesisApprovedPayload",
    "ThesisDraftedPayload",
    "ThesisGradedPayload",
    "ThesisRejectedPayload",
    "ThesisSubmittedPayload",
]
