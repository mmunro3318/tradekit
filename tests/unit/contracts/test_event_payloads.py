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
    Event,
    GateViolationDetectedPayload,
    HaltClearedPayload,
    HaltSetPayload,
    InvalidationAttestedPayload,
    MarketSnapshotTakenPayload,
    ReviewCompletedPayload,
    SizingComputedPayload,
    ThesisActivatedPayload,
    ThesisApprovedPayload,
    ThesisDraftedPayload,
    ThesisGradedPayload,
    ThesisRejectedPayload,
    ThesisSubmittedPayload,
)

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
}

_ALL_MODELS = list(_VALID_KWARGS)


@pytest.mark.parametrize("model_cls", _ALL_MODELS, ids=lambda m: m.__name__)
def test_constructs_from_valid_kwargs(model_cls) -> None:
    instance = model_cls(**_VALID_KWARGS[model_cls])
    assert isinstance(instance, model_cls)


@pytest.mark.parametrize("model_cls", _ALL_MODELS, ids=lambda m: m.__name__)
def test_is_frozen(model_cls) -> None:
    instance = model_cls(**_VALID_KWARGS[model_cls])
    first_field = next(iter(_VALID_KWARGS[model_cls]))
    with pytest.raises(ValidationError):
        setattr(instance, first_field, getattr(instance, first_field))
    # §5: "no in-place mutation ever" — pydantic's frozen=True raises on ANY
    # setattr, even a no-op reassignment of the field's current value.


@pytest.mark.parametrize("model_cls", _ALL_MODELS, ids=lambda m: m.__name__)
def test_extra_field_rejected(model_cls) -> None:
    with pytest.raises(ValidationError):
        model_cls(**_VALID_KWARGS[model_cls], unexpected_field="typo-dies-here")
    # extra="forbid" (StrictFrozenModel): a stray/typo'd field must die at
    # construction, not be silently dropped on the JSON round trip into the
    # ledger's payload dict (same rationale as ASSUMPTIONS 5's Predicate rule).


@pytest.mark.parametrize(
    ("model_cls", "required_field"),
    [
        (ThesisDraftedPayload, "thesis_id"),
        (ThesisDraftedPayload, "contract"),
        (MarketSnapshotTakenPayload, "snapshot_id"),
        (MarketSnapshotTakenPayload, "last_close"),
        (SizingComputedPayload, "sizing"),
        (SizingComputedPayload, "account_equity_usd"),
        (ThesisSubmittedPayload, "ev_recomputed_usd"),
        (ThesisSubmittedPayload, "market_snapshot_id"),
        (ReviewCompletedPayload, "review_artifact_id"),
        (ThesisApprovedPayload, "review_artifact_id"),
        (ThesisRejectedPayload, "why"),
        (ThesisActivatedPayload, "order_id"),
        (InvalidationAttestedPayload, "attestation"),
        (InvalidationAttestedPayload, "kind"),
        (ThesisGradedPayload, "pnl_usd"),
        (ThesisGradedPayload, "outcome"),
        (GateViolationDetectedPayload, "why"),
        (GateViolationDetectedPayload, "rule_id"),
        (HaltSetPayload, "set_by"),
        (HaltClearedPayload, "cleared_by"),
    ],
    ids=lambda v: v if isinstance(v, str) else v.__name__,
)
def test_required_field_missing_is_rejected(model_cls, required_field: str) -> None:
    kwargs = dict(_VALID_KWARGS[model_cls])
    del kwargs[required_field]
    with pytest.raises(ValidationError):
        model_cls(**kwargs)


@pytest.mark.parametrize(
    ("model_cls", "decimal_field"),
    [
        (MarketSnapshotTakenPayload, "last_close"),
        (SizingComputedPayload, "account_equity_usd"),
        (ThesisSubmittedPayload, "resolved_target_price"),
        (ThesisSubmittedPayload, "ev_stated_usd"),
        (ThesisGradedPayload, "pnl_usd"),
    ],
    ids=lambda v: v if isinstance(v, str) else v.__name__,
)
def test_decimal_field_coerces_from_string(model_cls, decimal_field: str) -> None:
    kwargs = dict(_VALID_KWARGS[model_cls])
    kwargs[decimal_field] = "123.45"
    instance = model_cls(**kwargs)
    value = getattr(instance, decimal_field)
    assert isinstance(value, Decimal) and value == Decimal("123.45"), (
        f"{model_cls.__name__}.{decimal_field} must be Decimal end-to-end (TD-3) — a "
        "float here corrupts money math downstream"
    )


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
