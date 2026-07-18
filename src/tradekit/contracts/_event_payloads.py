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
    # `failure_mode` (SPRINT P3 batch D, additive+defaulted -- every P2/P3
    # pre-existing payload keeps validating): the "ReviewFailed-as-
    # ReviewCompleted" pin (sprint doc addendum, ASSUMPTIONS round-20) -- a
    # reviewer subprocess boundary failure (malformed JSON, timeout,
    # oversized output) or an auto-fail short-circuit is NEVER a crash and
    # NEVER a distinct event type; it is ReviewCompleted(passed=False,
    # failure_mode=...). None on a passed=True artifact, and on any
    # passed=False artifact whose failure came from the deterministic
    # rubric itself (unresolved attack >= threshold) rather than a
    # boundary/short-circuit failure -- failure_mode names WHY the reviewer
    # pipeline couldn't produce a scored exchange, not "the thesis failed
    # review" (that case is passed=False with failure_mode=None).
    failure_mode: (
        Literal[
            "auto_fail_ev_missing",
            "auto_fail_no_falsifiable_criteria",
            "auto_fail_size_mismatch",
            "malformed_output",
            "timeout",
            "output_too_large",
        ]
        | None
    ) = None


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


class ActionProposedPayload(StrictFrozenModel):
    """Producer: `policy.evaluate` (SPRINT P2 batch C) — appended BEFORE the
    pure core runs, so intent is on the record even if evaluation itself
    blows up (DESIGN §8.2 step 2: "intent recorded BEFORE evaluation").
    Mirrors `contracts.ProposedAction`'s fields verbatim; `order` is the
    nested `OrderRequest`, `model_dump(mode="json")`'d, when the action
    carries one (not every `kind` does)."""

    kind: str
    account_ref: str
    requested_by: str
    thesis_id: str | None = None
    order: dict[str, Any] | None = None


class VerdictIssuedPayload(StrictFrozenModel):
    """Producer: `policy.evaluate`, immediately after `ActionProposed`
    (DESIGN §8.2 step 3: "verdict recorded BEFORE broker call"). Mirrors
    `contracts.Verdict` plus the action linkage a bare `Verdict` doesn't
    carry (`account_ref`/`thesis_id`/`kind`) so a reader can find "what was
    this a verdict ON" without cross-referencing the preceding
    `ActionProposed` event by timestamp."""

    verdict_id: str
    kind: str
    account_ref: str
    thesis_id: str | None = None
    allow: bool
    rule_hits: list[dict[str, Any]] = Field(default_factory=list)
    policy_version_hash: str


class PolicyVersionLoadedPayload(StrictFrozenModel):
    """Producer: `policy.evaluate`/`policy.status` — appended the first time
    a given `policy_version_hash` is seen by this process (CTO addendum,
    "Ambient wiring"). `rule_ids` is sorted (the hash's own input order,
    ASSUMPTIONS-pinned) so the event is independently reproducible from the
    registry; `dials` is the canonical dial dump (`_dials.canonical_dump`)
    that, together with `rule_ids`, hashes to `policy_version_hash`."""

    policy_version_hash: str
    rule_ids: list[str]
    dials: dict[str, Any]


class PromotionGrantedPayload(StrictFrozenModel):
    """Producer: `policy.promotion_status()` (SPRINT P2 batch D, §7.3 T1->T2)
    — the READ verb that may append exactly this one event type when the
    machine-evaluated T1->T2 criteria are met AND no unconsumed
    `PromotionGranted` already exists for this `account_ref` (ASSUMPTIONS,
    batch D: "read-verb-that-writes", flagged for ratification — the
    alternative, a dedicated `evaluate_promotion` verb, would widen the
    six-verb policy surface the CTO addendum pins closed).

    `criteria` carries the per-conjunct pass/fail breakdown that earned the
    grant (3-of-4-clean / most-recent-clean / >=30 non-void / R-016 metrics
    gate) so the ledgered event is self-auditing without re-deriving the
    evaluation."""

    account_ref: str
    from_tier: Literal["T0", "T1"]
    to_tier: Literal["T1", "T2"]
    criteria: dict[str, Any]


class PromotionConfirmedPayload(StrictFrozenModel):
    """Producer: `policy.confirm_promotion()` (Mike-only verb, §7.3, R-011).
    Consumes the unconsumed `PromotionGranted` named by `granted_event_id`;
    `live_sequence_remaining` is always `3` at confirmation (the fresh
    live-trade budget the sprint doc pins)."""

    account_ref: str
    to_tier: Literal["T2"]
    granted_event_id: str
    live_sequence_remaining: int = 3
    confirmed_by: str


class DemotedPayload(StrictFrozenModel):
    """Producer: `policy.promotion_status()` (SPRINT P2 batch D — CTO
    adjudication: the machine evaluates demotion triggers the SAME way it
    evaluates promotion, inside the one read-verb-that-writes, rather than a
    separate demotion verb; flagged for ratification, same class of call as
    `PromotionGrantedPayload`'s). §7.3 triggers: R-009 drawdown-breaker trip,
    a `GateViolationDetected` while T2, or a failed live grading — `trigger`
    names which one fired; `detail` carries the triggering event's own id/
    rule_id for audit linkage."""

    account_ref: str
    from_tier: Literal["T2"]
    to_tier: Literal["T1"]
    trigger: Literal["drawdown_breach", "gate_violation", "failed_live_grade"]
    detail: str


class ConfigChangedPayload(StrictFrozenModel):
    """Producer: `policy.evaluate`/`policy.status` — appended IN ADDITION to
    `PolicyVersionLoaded` when the freshly-computed hash differs from the
    last recorded one (CTO addendum: "a hash different from the last
    recorded one additionally appends ConfigChanged"). `previous_hash` is
    `None` only for the very first hash this ledger has ever seen (there is
    no prior config to have changed FROM — that case gets
    `PolicyVersionLoaded` alone, never a `ConfigChanged` with a fabricated
    predecessor)."""

    previous_hash: str | None
    new_hash: str
    dials: dict[str, Any]


class AccountCreatedPayload(StrictFrozenModel):
    """Producer: `tradekit.broker.create_paper_account` (SPRINT P3 batch A,
    TD-24). `config` is the full `AccountConfig`, `model_dump(mode="json")`'d
    — same "carry the whole contract so a reader never needs a second
    lookup" convention as `ThesisDraftedPayload.contract` above."""

    account_ref: str
    config: dict[str, Any]
    created_ts: AwareDatetime


class OrderSubmittedPayload(StrictFrozenModel):
    """Producer: a `BrokerPort.submit` adapter (SPRINT P3 batch B,
    `PaperBroker` first) — appended BEFORE any fill evaluation, so an
    order's own request shape is durably recorded and `order_status` can
    later re-derive a resting order's terms without the adapter holding any
    mutable state of its own (§8.3's "state from ledger events only"
    discipline, mirrors `_paper.py`'s module docstring). Mirrors
    `contracts.OrderRequest`'s fields, `asset` carried as
    `model_dump(mode="json")` (same "carry the whole nested contract, no
    second lookup" convention as `ThesisDraftedPayload.contract`), plus the
    `order_id` assigned at submission and the submission timestamp — the
    reference instant a later resting-limit evaluation compares bar
    `ts_open`s against (only bars closing AFTER this ts count, ASSUMPTIONS
    round-17 entry 110). Additive (batch B) — not in the SPRINT P3 batch A
    scope note; no prior producer/consumer to migrate."""

    order_id: str
    thesis_id: str
    account_ref: str
    asset: dict[str, Any]
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit", "stop", "stop_limit"]
    qty: Decimal
    limit_price: Decimal | None = None
    ts_utc: AwareDatetime


class OrderAckPayload(StrictFrozenModel):
    """Producer: a `BrokerPort.submit` adapter, immediately after
    `OrderSubmitted` (mirrors `contracts.OrderAck`'s fields verbatim; §8.2
    step 5's "OrderSubmitted/OrderAck" pairing). Additive (batch B).

    `thesis_id` (SPRINT P3 batch C dev-pass addition, ASSUMPTIONS
    round-18): every OTHER money-path event on the §8.2 ordering guarantee
    (`OrderSubmitted`/`FillRecorded`/`ThesisActivated`) carries `thesis_id`
    so a reader can filter "this thesis's own events" with one generic
    payload-key query (`test_pipeline.py`'s own `_thesis_events` helper,
    used by the ordering-guarantee test) — `OrderAck` was the one gap in
    that convention; closed here rather than special-cased away in a
    consumer."""

    order_id: str
    thesis_id: str
    status: Literal["accepted", "rejected"]
    ts_utc: AwareDatetime
    venue_order_id: str | None = None


class FillRecordedPayload(StrictFrozenModel):
    """Producer: `broker._paper.PaperBroker.submit`/order-fill evaluation
    (SPRINT P3 batch B, §8.3) — and, later, `AlpacaBroker`/`ManualBroker`
    (§8.4). Replaces P2's harness convention (ASSUMPTIONS round-9 entries
    69/70: raw dicts shaped like `contracts.Fill`, no `side` field) with a
    typed, additive contract every real fill producer validates through.

    Superset of `contracts.Fill`'s field shape (`order_id`, `thesis_id`,
    `ts_utc`, `price`, `qty`, `fees_usd`, `quote_snapshot`) PLUS `side` —
    the field `Fill` never carried (ASSUMPTIONS 69's own flagged gap) and
    that this typed payload closes so a future entry/exit convention no
    longer has to infer direction from earliest/latest `ts_utc` alone —
    PLUS `account_ref` (CTO adjudication, Round-17 entry 107: first-class,
    required — multi-account attribution, TD-7/TD-24).
    `quote_snapshot` carries the bar this fill priced off (§8.3: "every
    paper fill auditable") — `ts_open`/`close`/`source` at minimum (batch B
    pin), a plain JSON object per the ASSUMPTIONS-10 pattern (heterogeneous
    across venues, never itself a nested typed model). `account_ref` is
    FIRST-CLASS and required (CTO adjudication, Round-17 entry 107
    override): multi-account attribution is TD-7's entire reason to exist,
    and an untyped side-channel dict key on a typed payload would defeat
    the model — producers carry it here, never as an extra merged key.

    Compatibility note (ASSUMPTIONS round-17, this batch): `thesis.
    _grade_wiring.compute_pnl` reads `FillRecorded` payloads as plain
    dicts via `event.payload.get(...)` / `event.payload["..."]` — it never
    imports or validates through a payload model (ASSUMPTIONS 10's
    consumer-reads-the-dict split) and never touches `side` or
    `quote_snapshot`. Every P2-harness-built fixture fill (this contract's
    OWN pre-existing field set, minus `side`/`quote_snapshot`) therefore
    still satisfies every field `compute_pnl` actually reads — no P2 test
    changes, no migration needed for that consumer. `side` stays unused by
    `compute_pnl`'s existing earliest/latest-`ts_utc` entry/exit convention
    this batch; wiring `side` into pnl attribution (replacing the
    ordering-based convention) is explicitly deferred, not attempted here."""

    order_id: str
    thesis_id: str
    account_ref: str
    ts_utc: AwareDatetime
    price: Decimal
    qty: Decimal
    fees_usd: Decimal
    side: Literal["buy", "sell"]
    quote_snapshot: dict[str, Any] = Field(default_factory=dict)
    # `symbol` (batch B dev-pass addition, CTO-adjudicated 2026-07-17):
    # `PaperBroker.positions()` needs a per-symbol key to derive Position
    # rows from FillRecorded history alone (no mutable broker state).
    # REQUIRED, no default — a defaulted symbol on a money payload is
    # silent fabrication (a producer that forgot it would write BTC/USD
    # fills); every producer, harness fixtures included, must name the
    # symbol explicitly.
    symbol: str


class ReconciliationRunPayload(StrictFrozenModel):
    """Producer: `broker.reconcile` / `broker._pipeline.reconcile` (SPRINT P3
    batch C, §8.2 step 7 / §15). Compares `BrokerPort.fills()` against this
    account's own `FillRecorded` ledger history; `result="ok"` when every
    broker fill has a matching ledger row (match key: `order_id` + `ts_utc`
    + `qty`, per the batch's own reconcile pin), `result="mismatch"` when
    ANY broker fill has no matching ledger row — an out-of-band trade §15's
    threat model exists to catch. `mismatches` carries one entry per
    unmatched broker fill (plain dict, `contracts.Fill`-shaped, same
    ASSUMPTIONS-10 heterogeneous-payload convention as `quote_snapshot`
    elsewhere) so the event is self-auditing without a second broker call.
    A mismatch run is ALWAYS immediately followed by a `HaltSet` event
    (automatic, §8.2 step 7) — that pairing is the caller's job
    (`broker.reconcile`), not this payload's; a clean run appends no halt."""

    account_ref: str
    result: Literal["ok", "mismatch"]
    broker_fill_count: int
    ledger_fill_count: int
    mismatches: list[dict[str, Any]] = Field(default_factory=list)
    ts_utc: AwareDatetime


class OrderCancelledPayload(StrictFrozenModel):
    """Producer: `broker.cancel_order` (SPRINT P3 batch C, additive fifth
    broker verb alongside TD-24's `create_paper_account` — cancel is not one
    of §4.2's original four pinned verbs, ratified the same "contracts are
    cheap, declarative additions don't widen the deep-module surface"
    class of call as `create_paper_account`). MVP semantics (pinned, no
    improvisation): only a RESTING order (`order_status(...).status ==
    "open"`) may be canceled — a `filled`/`canceled`/`rejected` order
    refuses (typed `OrderAlreadyFilled`/similar, `broker._pipeline`'s job to
    define) and this event is never appended for a refused cancel attempt."""

    order_id: str
    account_ref: str
    ts_utc: AwareDatetime
    reason: str | None = None


class SeriesClosedPayload(StrictFrozenModel):
    """Producer: `policy.promotion_status()` (SPRINT P3 batch E, §7.3 —
    ASSUMPTIONS round-21: the same "read-verb-that-writes" class of call as
    `PromotionGrantedPayload`/`DemotedPayload` above). Appended AT MOST ONCE
    per `(account_ref, series_index)` — emitted the first time
    `promotion_status()` observes `now > window_end` for a series that has
    no prior `SeriesClosed` event yet (P3 scope is EMISSION + idempotence
    only; no consumer re-derives the `series` projection from this event
    this sprint — `policy._series.series_stats` keeps deriving its stats
    directly from `ThesisGraded`/`GateViolationDetected` at read time, same
    as P2). Field values mirror `policy._series.SeriesStats` exactly, so a
    reader never needs a second lookup to know why the window closed the
    way it did."""

    account_ref: str
    series_index: int
    window_start: AwareDatetime
    window_end: AwareDatetime
    graded_count: int
    void_count: int
    gate_violations: int
    clean: bool


class LessonRecordedPayload(StrictFrozenModel):
    """Producer: `memory.record_lesson(note, salience)` (SPRINT P3 batch E,
    DESIGN §11/§4.2). A pointer event only — the research loop (D14) writes
    the distilled knowledge itself to `docs/wiki/`; this event exists so a
    lesson is replayable/queryable from the ledger like everything else
    (§11: "record_lesson ledgers a pointer event so lessons are replayable
    too"). `salience` is the 1(low)-5(high) integer `tk brief`'s truncation
    ordering reads (module docstring, `tradekit.memory._brief`)."""

    note: str = Field(min_length=1)
    salience: int = Field(ge=1, le=5)


__all__ = [
    "AccountCreatedPayload",
    "ActionProposedPayload",
    "ConfigChangedPayload",
    "DemotedPayload",
    "FillRecordedPayload",
    "GateViolationDetectedPayload",
    "HaltClearedPayload",
    "HaltSetPayload",
    "InvalidationAttestedPayload",
    "LessonRecordedPayload",
    "MarketSnapshotTakenPayload",
    "OrderAckPayload",
    "OrderCancelledPayload",
    "OrderSubmittedPayload",
    "PolicyVersionLoadedPayload",
    "PromotionConfirmedPayload",
    "PromotionGrantedPayload",
    "ReconciliationRunPayload",
    "ReviewCompletedPayload",
    "SeriesClosedPayload",
    "SizingComputedPayload",
    "ThesisActivatedPayload",
    "ThesisApprovedPayload",
    "ThesisDraftedPayload",
    "ThesisGradedPayload",
    "ThesisRejectedPayload",
    "ThesisSubmittedPayload",
    "VerdictIssuedPayload",
]
