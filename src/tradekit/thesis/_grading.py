"""Pure grading arithmetic (DESIGN §10.2). No I/O, no ledger, no clock reads.

Resolution rules — every one resolves ambiguity AGAINST the agent (§15):
- Bars are evaluated in chronological order; only CLOSED bars count
  (ts_open + timeframe <= now) — the lookahead guard lives HERE so no
  caller can forget it.
- Within one bar, category priority is failure > invalidation > success.
  Stop-and-target in one bar is a FAIL (intrabar order is unknowable from
  OHLC); failure+invalidation is a FAIL (resolving to VOID would erase a
  loss from the stats — the §10.4 gaming vector).
- A predicate can only trigger on bars closing at or before its `by`
  deadline; a dead predicate never resurrects.
- Horizon expiry with nothing triggered = FAIL (SME F1), before the
  horizon = PENDING.
- MVP constraint (ASSUMPTIONS 24): all predicates in one thesis share one
  timeframe. Mixed timeframes raise — lift only with a design change.

Only MEASURABLE invalidations are evaluated here; structural ones go
through attestation + reviewer sign-off, never arithmetic (§10.4).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import TypeAdapter

from tradekit.contracts import (
    TIMEFRAME_SECONDS,
    Bar,
    CriteriaOutcome,
    InvalidationSpec,
    Predicate,
    quantize,
)

_PREDICATES: TypeAdapter[list[Predicate]] = TypeAdapter(list[Predicate])
_INVALIDATION: TypeAdapter[InvalidationSpec] = TypeAdapter(InvalidationSpec)

_Category = Literal["failure", "invalidation", "success"]
_PRIORITY: tuple[_Category, ...] = ("failure", "invalidation", "success")
_RESULT_FOR: dict[_Category, str] = {"failure": "FAIL", "invalidation": "VOID", "success": "PASS"}


def evaluate_criteria(
    *,
    bars: list[Bar],
    timeframe: str,
    tick_size: Decimal,
    success: list[Any],
    failure: list[Any],
    invalidation: Any | None,
    horizon_end: datetime,
    now: datetime,
) -> CriteriaOutcome:
    success_p = _PREDICATES.validate_python(success)
    failure_p = _PREDICATES.validate_python(failure)
    inval = _INVALIDATION.validate_python(invalidation) if invalidation is not None else None
    inval_p = [inval.predicate] if inval is not None and inval.kind == "measurable" else []

    duration = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    for p in (*success_p, *failure_p, *inval_p):
        tf = getattr(p, "timeframe", timeframe)  # time_expiry has none — inherits the thesis's
        if tf != timeframe:
            raise ValueError(
                f"predicate timeframe {tf!r} != thesis timeframe {timeframe!r}: "
                "one timeframe per thesis (ASSUMPTIONS 24)"
            )
    opens = [b.ts_open for b in bars]
    if opens != sorted(opens) or len(set(opens)) != len(opens):
        raise ValueError("bars must be strictly ascending by ts_open")

    groups: list[tuple[_Category, list[Predicate]]] = [
        ("failure", failure_p),
        ("invalidation", inval_p),
        ("success", success_p),
    ]
    evaluated: list[dict[str, Any]] = []

    for b in bars:
        close_time = b.ts_open + duration
        if close_time > now:
            break  # lookahead guard: this bar (and all later ones) is still open
        hit: dict[_Category, bool] = {}
        for category, preds in groups:
            for p in preds:
                if p.kind == "time_expiry":
                    if close_time < p.by:
                        continue  # deadline not reached yet
                elif close_time > p.by:
                    continue  # dead price predicate — never resurrects
                if _satisfied(p, b, tick_size):
                    hit[category] = True
                    evaluated.append(_record(p, category, b))
        if hit:
            winner = next(c for c in _PRIORITY if c in hit)
            return CriteriaOutcome(
                result=_RESULT_FOR[winner],  # type: ignore[arg-type]
                triggered=winner,
                trigger_ts=b.ts_open,
                ambiguous_bar=len(hit) > 1,
                evaluated=evaluated,
            )

    if now >= horizon_end:
        return CriteriaOutcome(result="FAIL", triggered="horizon_expiry", evaluated=evaluated)
    return CriteriaOutcome(result="PENDING", evaluated=evaluated)


def _satisfied(p: Predicate, b: Bar, tick: Decimal) -> bool:
    if p.kind == "time_expiry":
        return True  # deadline REACHED (close_time >= by, checked by the caller)
    value = quantize(p.value, tick)
    if p.kind == "price_touch":
        measured = quantize(b.high, tick) if p.cmp == "gte" else quantize(b.low, tick)
    else:  # price_close
        measured = quantize(b.close, tick)
    return measured >= value if p.cmp == "gte" else measured <= value


def _record(p: Predicate, category: str, b: Bar) -> dict[str, Any]:
    return {
        "category": category,
        "kind": p.kind,
        "cmp": getattr(p, "cmp", None),
        "value": str(getattr(p, "value", "")),
        "bar_ts_open": b.ts_open.isoformat(),
    }
