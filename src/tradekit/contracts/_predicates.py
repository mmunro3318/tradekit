"""Predicate DSL + invalidation variants (DESIGN §5.2, TD-9).

Discriminated unions on ``kind`` (ASSUMPTIONS 3-5). Grading is pure
arithmetic only if every criterion is machine-checkable; a predicate that
validates with missing or contradictory fields is free text in disguise.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from tradekit.contracts._base import StrictFrozenModel


class _PricePredicate(StrictFrozenModel):
    cmp: Literal["gte", "lte"]
    value: Decimal  # absolute price, resolved at submit time — never a percent (§5.2)
    timeframe: str = "1h"  # bar granularity used for evaluation; spec default (§5.2)
    by: datetime  # deadline (usually horizon_end); grading's hard stop


class PriceTouch(_PricePredicate):
    kind: Literal["price_touch"]


class PriceClose(_PricePredicate):
    kind: Literal["price_close"]


class TimeExpiry(StrictFrozenModel):
    # `by` alone (§5.2); extra="forbid" on the base rejects stray cmp/value.
    kind: Literal["time_expiry"]
    by: datetime


Predicate = Annotated[PriceTouch | PriceClose | TimeExpiry, Field(discriminator="kind")]


class MeasurableInvalidation(StrictFrozenModel):
    kind: Literal["measurable"]
    predicate: Predicate  # auto-evaluated by the grader — zero discretion (§10.4 guard 1)


class StructuralInvalidation(StrictFrozenModel):
    kind: Literal["structural"]
    description: str = Field(min_length=1)  # empty = unauditable escape hatch
    requires_attestation: Literal[True] = True  # VOID anti-gaming guard (§5.2, §10.4)


InvalidationSpec = Annotated[
    MeasurableInvalidation | StructuralInvalidation, Field(discriminator="kind")
]
