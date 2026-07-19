"""CONTRACT tests for `AdvisoryTicketAckedPayload` (SPEC-hud-ack pins,
docs/specs/SPEC-hud-ack.md "Interface pins").

House pattern precedent: `_event_payloads.py`'s other payload models are
`StrictFrozenModel` subclasses — frozen, `extra="forbid"`, `Decimal` fields
accept `Decimal`/`str`/JSON-number, `AwareDatetime` rejects naive
datetimes. These tests pin the SAME conventions for the new hud-ack payload
rather than re-deriving them, per docs/reviews test doctrine (CONTRACT tests
assert shape/validation, not behavior).

Field-shape pins taken verbatim from SPEC-hud-ack.md:
    verdict_preview_id: str
    action: Literal["confirmed", "failed"]
    thesis_id: str | None
    verdict_id: str | None
    pair: str
    side: Literal["buy", "sell"]
    limit_price: str      # Decimal-as-string, ticket snapshot
    quantity: str
    acked_at: AwareDatetime
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from tradekit.contracts import AdvisoryTicketAckedPayload

ACKED_AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

_BASE_KWARGS = {
    "verdict_preview_id": "verdict-preview-1",
    "action": "failed",
    "thesis_id": None,
    "verdict_id": None,
    "pair": "LINK/USD",
    "side": "buy",
    "limit_price": "8.30000",
    "quantity": "12",
    "acked_at": ACKED_AT,
}


class TestFailedActionAllowsNullThesisAndVerdictIds:
    def test_failed_payload_constructs_with_null_thesis_and_verdict_ids(self) -> None:
        """CONTRACT: action="failed" with thesis_id=None, verdict_id=None
        (the failed-ack pin: "thesis_id/verdict_id None") constructs
        successfully — these fields are Optional, not required-nonnull."""
        payload = AdvisoryTicketAckedPayload(**_BASE_KWARGS)
        assert payload.action == "failed"
        assert payload.thesis_id is None
        assert payload.verdict_id is None


class TestConfirmedActionAcceptsRealIds:
    def test_confirmed_payload_accepts_nonnull_thesis_and_verdict_ids(self) -> None:
        """CONTRACT: action="confirmed" + allow carries the BINDING
        thesis_id/verdict_id (SPEC: "verdict_id: the BINDING confirm-time
        verdict")."""
        kwargs = dict(_BASE_KWARGS)
        kwargs["action"] = "confirmed"
        kwargs["thesis_id"] = "thesis-abc"
        kwargs["verdict_id"] = "verdict-binding-1"
        payload = AdvisoryTicketAckedPayload(**kwargs)
        assert payload.thesis_id == "thesis-abc"
        assert payload.verdict_id == "verdict-binding-1"


class TestActionLiteralDomainRejectsOutsideValues:
    def test_action_outside_confirmed_or_failed_raises_validation_error(self) -> None:
        """CONTRACT: `action` is a closed Literal["confirmed", "failed"] —
        any other string (e.g. a veto value, which SPEC explicitly puts
        out of scope) must fail validation, not silently pass through."""
        kwargs = dict(_BASE_KWARGS)
        kwargs["action"] = "vetoed"
        with pytest.raises(ValidationError):
            AdvisoryTicketAckedPayload(**kwargs)


class TestSideLiteralDomainRejectsOutsideValues:
    def test_side_outside_buy_or_sell_raises_validation_error(self) -> None:
        """CONTRACT: `side` is Literal["buy", "sell"] — matches every other
        house side field (e.g. `OrderRequest.side`, `AdvisoryTicket.side`)."""
        kwargs = dict(_BASE_KWARGS)
        kwargs["side"] = "hold"
        with pytest.raises(ValidationError):
            AdvisoryTicketAckedPayload(**kwargs)


class TestDecimalSnapshotFieldsAcceptStringAndPreserveExactValue:
    def test_limit_price_and_quantity_are_decimal_typed_from_string_input(self) -> None:
        """CONTRACT: SPEC pins limit_price/quantity as "Decimal-as-string,
        ticket snapshot" — the field TYPE is Decimal (house convention,
        same as every other money field in `_event_payloads.py`); a string
        input round-trips to an exact Decimal, not a lossy float."""
        kwargs = dict(_BASE_KWARGS)
        kwargs["limit_price"] = "8.30001"
        kwargs["quantity"] = "12.5"
        payload = AdvisoryTicketAckedPayload(**kwargs)
        assert payload.limit_price == Decimal("8.30001")
        assert payload.quantity == Decimal("12.5")
        assert isinstance(payload.limit_price, Decimal)
        assert isinstance(payload.quantity, Decimal)


class TestAckedAtRequiresAwareDatetime:
    def test_naive_acked_at_raises_validation_error(self) -> None:
        """CONTRACT: `acked_at: AwareDatetime` — house rule (TD-17,
        ASSUMPTIONS 20): a naive datetime is a ValidationError, never
        silently interpreted as local/UTC."""
        kwargs = dict(_BASE_KWARGS)
        kwargs["acked_at"] = datetime(2026, 7, 20, 12, 0)  # naive
        with pytest.raises(ValidationError):
            AdvisoryTicketAckedPayload(**kwargs)


class TestPayloadIsFrozen:
    def test_mutating_a_field_after_construction_raises(self) -> None:
        """CONTRACT: house style — every `_event_payloads.py` model is
        frozen (StrictFrozenModel); a producer must construct a NEW
        instance rather than mutate a ledgered payload in place."""
        payload = AdvisoryTicketAckedPayload(**_BASE_KWARGS)
        with pytest.raises(ValidationError):
            payload.action = "confirmed"  # type: ignore[misc]


class TestExtraFieldsForbidden:
    def test_unknown_field_raises_validation_error(self) -> None:
        """CONTRACT: `extra="forbid"` (StrictFrozenModel) — a stray/typo'd
        field must die at construction, not silently vanish on the JSON
        round trip (same rationale as every other _event_payloads.py
        model's docstring)."""
        kwargs = dict(_BASE_KWARGS)
        kwargs["tp_price"] = "9.00000"  # not a pinned field
        with pytest.raises(ValidationError):
            AdvisoryTicketAckedPayload(**kwargs)
