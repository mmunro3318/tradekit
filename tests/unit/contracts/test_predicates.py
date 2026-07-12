"""Predicate discriminated union (DESIGN §5.2).

Grading is "pure arithmetic" only if criteria are machine-checkable — a
predicate that validates with missing or contradictory fields is a free-text
criterion in disguise. Validation via TypeAdapter so the tests hold whether
`Predicate` is exported as a discriminated-union alias or a base model.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from tradekit.contracts import Predicate

PRED: TypeAdapter[Any] = TypeAdapter(Predicate)
BY = datetime(2026, 2, 15, tzinfo=UTC)


def _valid(kind: str) -> dict[str, Any]:
    d: dict[str, Any] = {"kind": kind, "by": BY}
    if kind != "time_expiry":
        d |= {"cmp": "gte", "value": "66000.00"}
    return d


@pytest.mark.parametrize("kind", ["price_touch", "price_close"])
@pytest.mark.parametrize("missing", ["cmp", "value"])
def test_price_kinds_require_cmp_and_value(kind: str, missing: str) -> None:
    # A price predicate without cmp/value cannot be evaluated against a bar —
    # silent acceptance would defer the crash to grade-sweep time (§5.2).
    data = _valid(kind)
    del data[missing]
    with pytest.raises(ValidationError):
        PRED.validate_python(data)


@pytest.mark.parametrize("forbidden", [{"cmp": "gte"}, {"value": "100"}])
def test_time_expiry_rejects_price_fields(forbidden: dict[str, Any]) -> None:
    # §5.2: "time_expiry uses `by` alone". Accepting a stray cmp/value means the
    # union isn't discriminated — a time predicate masquerading as a price check
    # would be silently ignored by the grader instead of rejected at authoring.
    with pytest.raises(ValidationError):
        PRED.validate_python(_valid("time_expiry") | forbidden)


@pytest.mark.parametrize("kind", ["price_touch", "price_close", "time_expiry"])
def test_by_deadline_required_everywhere(kind: str) -> None:
    # A predicate without a deadline never expires — grading loses its hard stop
    # and horizon_end enforcement becomes advisory (§5.2: `by` required).
    data = _valid(kind)
    del data["by"]
    with pytest.raises(ValidationError):
        PRED.validate_python(data)


def test_unknown_kind_rejected() -> None:
    with pytest.raises(ValidationError):
        PRED.validate_python({"kind": "price_vibes", "cmp": "gte", "value": "1", "by": BY})


def test_valid_price_touch_is_decimal_with_default_timeframe() -> None:
    p = PRED.validate_python(_valid("price_touch"))
    assert isinstance(p.value, Decimal), (
        f"value is {type(p.value).__name__}: predicate anchors are money — Decimal "
        "end-to-end or float noise re-enters exactly where quantize removed it (TD-3, TD-23)"
    )
    assert p.value == Decimal("66000.00")
    assert p.timeframe == "1h", (
        f"timeframe defaulted to {p.timeframe!r}: spec default is '1h' (§5.2) — a "
        "different default silently changes which bars grade a thesis"
    )
