"""Typed thesis-lifecycle event payload models (DESIGN §6.3, ASSUMPTIONS 10,
SPRINT P2 batch A — `contracts._event_payloads`).

Table-driven: one entry per new payload model, exercised for construction,
frozen-ness, `extra="forbid"`, and (where applicable) required-field/
Decimal-coercion/naive-datetime pins — rather than 13 near-identical files
(batch dispatch: "table-driven/parametrized, not 13 copy-pasted files").

These models are REAL (not stubs) per the batch dispatch: "contracts are
cheap and tests need to construct them" — every test in this file should be
GREEN from the moment `_event_payloads.py` lands, unlike the thesis-verb
tests in `tests/unit/thesis/`, which stay red until the P2 dev pass.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError
from ulid import ULID

from tradekit.contracts import (
    DemotedPayload,
    Event,
    GateViolationDetectedPayload,
    HaltClearedPayload,
    HaltSetPayload,
    InvalidationAttestedPayload,
    MarketSnapshotTakenPayload,
    PromotionConfirmedPayload,
    PromotionGrantedPayload,
    ReviewCompletedPayload,
    SizingComputedPayload,
    ThesisActivatedPayload,
    ThesisApprovedPayload,
    ThesisDraftedPayload,
    ThesisGradedPayload,
    ThesisRejectedPayload,
    ThesisSubmittedPayload,
)
from tradekit.contracts._base import StrictFrozenModel  # noqa: TID251 — base pin

T0 = datetime(2026, 1, 1, tzinfo=UTC)

# One representative, fully-valid kwargs dict per model — the fixture every
# other test in this file mutates from.
_VALID_KWARGS: dict[type, dict] = {
    ThesisDraftedPayload: dict(
        thesis_id="th-1", contract={"account_ref": "paper:alpha"}, supersedes=None
    ),
    MarketSnapshotTakenPayload: dict(
        thesis_id="th-1",
        snapshot_id="snap-1",
        symbol="BTC/USD",
        ts=T0,
        last_close=Decimal("100.00"),
        source="kraken",
    ),
    SizingComputedPayload: dict(
        thesis_id="th-1",
        symbol="BTC/USD",
        account_equity_usd=Decimal("500"),
        sizing={"recommended_size_usd": 125.0, "warnings": []},
    ),
    ThesisSubmittedPayload: dict(
        thesis_id="th-1",
        market_snapshot_id="snap-1",
        resolved_target_price=Decimal("66000.00"),
        resolved_stop_price=Decimal("57000.00"),
        resolved_success_criteria=[{"kind": "price_touch", "value": "66000.00"}],
        resolved_failure_criteria=[{"kind": "price_close", "value": "57000.00"}],
        ev_stated_usd=Decimal("0.81"),
        ev_recomputed_usd=Decimal("0.8125"),
    ),
    ReviewCompletedPayload: dict(thesis_id="th-1", review_artifact_id="rev-1", passed=True),
    ThesisApprovedPayload: dict(thesis_id="th-1", review_artifact_id="rev-1"),
    ThesisRejectedPayload: dict(
        thesis_id="th-1", why="unresolved attack: sizing not from size_position"
    ),
    ThesisActivatedPayload: dict(thesis_id="th-1", order_id="ord-1", ts_utc=T0),
    InvalidationAttestedPayload: dict(
        thesis_id="th-1", kind="structural", attestation="FOMC surprised hawkish"
    ),
    ThesisGradedPayload: dict(
        thesis_id="th-1",
        outcome="PASS",
        measured=[{"kind": "price_touch", "value": "66000.00"}],
        ambiguous_bar=False,
        pnl_usd=Decimal("12.34"),
        graded_ts=T0,
    ),
    GateViolationDetectedPayload: dict(
        rule_id="R-008",
        account_ref="paper:alpha",
        thesis_id="th-1",
        measured="5.00",
        limit="10.00",
        why="below min notional",
    ),
    HaltSetPayload: dict(reason="reconcile mismatch", scope="all", set_by="system:reconcile"),
    HaltClearedPayload: dict(
        reason="mismatch resolved", halt_event_id="evt-1", cleared_by="mike"
    ),
    # SPRINT P2 batch D (§7.3 promotion machine).
    PromotionGrantedPayload: dict(
        account_ref="paper:alpha",
        from_tier="T1",
        to_tier="T2",
        criteria={"three_of_last_four_clean": True},
    ),
    PromotionConfirmedPayload: dict(
        account_ref="paper:alpha",
        to_tier="T2",
        granted_event_id="evt-grant-1",
        live_sequence_remaining=3,
        confirmed_by="mike",
    ),
    DemotedPayload: dict(
        account_ref="paper:alpha",
        from_tier="T2",
        to_tier="T1",
        trigger="gate_violation",
        detail="evt-violation-1",
    ),
}

_ALL_MODELS = list(_VALID_KWARGS)


@pytest.mark.parametrize("model_cls", _ALL_MODELS, ids=lambda m: m.__name__)
def test_constructs_from_valid_kwargs(model_cls) -> None:
    instance = model_cls(**_VALID_KWARGS[model_cls])
    assert isinstance(instance, model_cls)


def test_every_payload_model_is_strict_frozen() -> None:
    """Collapses the former frozen/extra-forbid/required-field/decimal-coercion
    parametrize sweeps (~85 cases) into one inheritance pin: every payload
    model in this file gets `frozen=True` + `extra="forbid"` (plus pydantic's
    own required-field and Decimal-coercion machinery) FOR FREE from
    `StrictFrozenModel` — pydantic itself already guarantees that behavior for
    any subclass, so re-testing it per-model is pure padding
    (test-audit-2026-07-18.md garbage-removal item 1). Custom validators
    (naive-datetime rejection, enum pins, nullable-not-optional pnl_usd, the
    producer round trip, etc.) stay as their own dedicated tests below."""
    for model_cls in _ALL_MODELS:
        assert issubclass(model_cls, StrictFrozenModel), (
            f"{model_cls.__name__} must inherit StrictFrozenModel (frozen=True, "
            "extra='forbid') so it gets the shared mutation/extra-field/required-"
            "field discipline pydantic enforces for the whole hierarchy"
        )


def test_strict_frozen_model_base_rejects_mutation_and_extra_fields() -> None:
    """`StrictFrozenModel` itself isn't exercised by any other test in the
    suite — pin its two load-bearing `ConfigDict` flags once, directly,
    rather than at every subclass (test-audit-2026-07-18.md item 1)."""

    class _Probe(StrictFrozenModel):
        value: int

    probe = _Probe(value=1)
    with pytest.raises(ValidationError):
        probe.value = 2  # frozen=True: no in-place mutation ever (§5)
    with pytest.raises(ValidationError):
        _Probe(value=1, unexpected_field="typo-dies-here")  # extra="forbid"


@pytest.mark.parametrize(
    ("model_cls", "dt_field"),
    [
        (MarketSnapshotTakenPayload, "ts"),
        (ThesisActivatedPayload, "ts_utc"),
        (ThesisGradedPayload, "graded_ts"),
    ],
    ids=lambda v: v if isinstance(v, str) else v.__name__,
)
def test_naive_datetime_rejected(model_cls, dt_field: str) -> None:
    kwargs = dict(_VALID_KWARGS[model_cls])
    kwargs[dt_field] = datetime(2026, 1, 1)  # naive — no tzinfo
    with pytest.raises(ValidationError):
        model_cls(**kwargs)
    # TD-17/ASSUMPTIONS 20: a naive datetime is machine-local guesswork, never
    # silently accepted as UTC.


def test_thesis_rejected_why_must_be_nonempty() -> None:
    with pytest.raises(ValidationError):
        ThesisRejectedPayload(thesis_id="th-1", why="")
    # An unreasoned rejection is unauditable — same spirit as
    # StructuralInvalidation.description's min_length=1 (ASSUMPTIONS 8).


def test_thesis_graded_outcome_restricted_to_enum() -> None:
    with pytest.raises(ValidationError):
        ThesisGradedPayload(
            thesis_id="th-1", outcome="MAYBE", pnl_usd=Decimal("0"), graded_ts=T0
        )


def test_thesis_graded_pnl_usd_accepts_none() -> None:
    """CTO adjudication (P2 batch B, ASSUMPTIONS 71): pnl_usd is NULLABLE —
    a graded thesis with zero FillRecorded events has NO realized pnl, and
    Decimal("0") would fabricate a break-even datapoint into batch D's
    series-expectancy math. None means "no fills to account"."""
    payload = ThesisGradedPayload(
        thesis_id="th-1", outcome="FAIL", pnl_usd=None, graded_ts=T0
    )
    assert payload.pnl_usd is None
    # And it survives the ASSUMPTIONS-10 producer round trip as None, not 0.
    reconstructed = ThesisGradedPayload.model_validate(payload.model_dump(mode="json"))
    assert reconstructed.pnl_usd is None


def test_thesis_graded_pnl_usd_still_required_even_though_nullable() -> None:
    # None must be said EXPLICITLY — a producer that forgets the field
    # entirely dies at construction (nullable != optional).
    with pytest.raises(ValidationError):
        ThesisGradedPayload(thesis_id="th-1", outcome="FAIL", graded_ts=T0)


def test_review_completed_kind_defaults_to_thesis_review() -> None:
    """CTO adjudication (P2 batch B, ASSUMPTIONS 73): `kind` is ADDITIVE and
    DEFAULTED — every pre-existing ReviewCompleted payload (no kind key)
    keeps validating as an ordinary pre-approval thesis review."""
    payload = ReviewCompletedPayload(**_VALID_KWARGS[ReviewCompletedPayload])
    assert payload.kind == "thesis_review"


def test_review_completed_kind_accepts_void_signoff_and_rejects_junk() -> None:
    signoff = ReviewCompletedPayload(
        thesis_id="th-1", review_artifact_id="voidrev-1", passed=True, kind="void_signoff"
    )
    assert signoff.kind == "void_signoff"
    with pytest.raises(ValidationError):
        ReviewCompletedPayload(
            thesis_id="th-1", review_artifact_id="rev-1", passed=True, kind="vibes"
        )


def test_invalidation_attested_kind_restricted_to_enum() -> None:
    with pytest.raises(ValidationError):
        InvalidationAttestedPayload(thesis_id="th-1", kind="vibes", attestation="nope")


def test_promotion_granted_tier_literals_restricted() -> None:
    with pytest.raises(ValidationError):
        PromotionGrantedPayload(
            account_ref="paper:alpha", from_tier="T2", to_tier="T2", criteria={}
        )
    with pytest.raises(ValidationError):
        PromotionGrantedPayload(
            account_ref="paper:alpha", from_tier="T1", to_tier="T0", criteria={}
        )


def test_promotion_confirmed_live_sequence_remaining_defaults_to_three() -> None:
    kwargs = dict(_VALID_KWARGS[PromotionConfirmedPayload])
    del kwargs["live_sequence_remaining"]
    payload = PromotionConfirmedPayload(**kwargs)
    assert payload.live_sequence_remaining == 3, (
        "§7.3/R-011: a fresh live-trade budget is always 3 at confirmation"
    )


def test_demoted_trigger_restricted_to_enum() -> None:
    with pytest.raises(ValidationError):
        DemotedPayload(
            account_ref="paper:alpha",
            from_tier="T2",
            to_tier="T1",
            trigger="mike_felt_like_it",
            detail="n/a",
        )


def test_producer_round_trip_pattern_thesis_submitted() -> None:
    """Pins ASSUMPTIONS 10's ratified producer pattern for a representative
    payload: validate through the typed model, `model_dump(mode="json")`
    into the ledger `Event.payload` dict, then reconstruct the SAME typed
    model back out of that dict. Lossless round trip end-to-end, including
    through the Event envelope's OWN JSON round trip (ledger stores canonical
    JSON, §6.2)."""
    payload_model = ThesisSubmittedPayload(**_VALID_KWARGS[ThesisSubmittedPayload])

    envelope_payload = payload_model.model_dump(mode="json")
    event = Event(
        event_id=str(ULID()),
        ts_utc=T0,
        type="ThesisSubmitted",
        actor="agent:test",
        run_id=None,
        schema_ver=1,
        payload=envelope_payload,
    )
    # Event itself round-trips through JSON (ledger storage boundary).
    event_back = Event.model_validate_json(event.model_dump_json())

    reconstructed = ThesisSubmittedPayload.model_validate(event_back.payload)
    assert reconstructed == payload_model, (
        "producer pattern (validate -> model_dump(mode='json') -> dict envelope -> "
        "reconstruct) must be lossless — this is the ASSUMPTIONS-10 ratified contract "
        "every P2/P3 producer relies on"
    )
