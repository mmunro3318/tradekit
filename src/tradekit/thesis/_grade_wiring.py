"""`thesis.grade`/`thesis.void` mechanics (DESIGN §10.2/§10.3/§10.4, SPRINT
P2 batch B, CTO addendum story-2 pins). Deliberately private, mirroring the
`_submit.py` split: this module does the bar-fetch/arithmetic/pnl work that
can fail, `tradekit.thesis.__init__` calls it and does the appending.

Sanctioned cross-module seam (unchanged from batch A / story-1 pins):
`thesis` may import `mae._runtime` and call `get_closed_bars`/`clock` ONLY,
via the `from tradekit.mae import _runtime as _mae_runtime` module-attribute
form so tests monkeypatching the dotted string path see the effect here.
`_grading.evaluate_criteria` (the FROZEN arithmetic core) is called, never
reimplemented (ASSUMPTIONS, Round-9 update to entry 23).
"""

from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal
from typing import Any

from tradekit.contracts import CriteriaOutcome, Event, EventFilter
from tradekit.ledger import Ledger
from tradekit.mae import _runtime as _mae_runtime
from tradekit.thesis import _grading


def predicate_timeframe(
    success: list[dict[str, Any]],
    failure: list[dict[str, Any]],
    invalidation: dict[str, Any] | None,
) -> str:
    """The one timeframe shared by every predicate on this thesis
    (ASSUMPTIONS 24) — `time_expiry` predicates carry no `timeframe` key of
    their own (they inherit the thesis's, per `_grading.py`'s own comment),
    so this searches price-carrying predicates first, falling back to a
    measurable invalidation's predicate."""
    for p in (*success, *failure):
        tf = p.get("timeframe")
        if tf:
            return str(tf)
    if invalidation is not None and invalidation.get("kind") == "measurable":
        tf = invalidation.get("predicate", {}).get("timeframe")
        if tf:
            return str(tf)
    raise ValueError("cannot determine a predicate timeframe for this thesis (ASSUMPTIONS 24)")


def lookback_days_covering(activation_ts: datetime, now: datetime) -> int:
    """`lookback_days` such that `get_closed_bars`'s fetched window (ending
    at `now`, `lookback_days` trailing) COVERS `activation_ts` — rounded UP
    (ceil) so a non-day-aligned activation timestamp is never clipped
    (ASSUMPTIONS 68, CTO ratification note)."""
    delta_days = (now - activation_ts).total_seconds() / 86400.0
    return max(math.ceil(delta_days), 0)


def evaluate(
    *,
    symbol: str,
    tick_size: Decimal,
    success: list[dict[str, Any]],
    failure: list[dict[str, Any]],
    invalidation: dict[str, Any] | None,
    horizon_end: datetime,
    activation_ts: datetime,
) -> CriteriaOutcome:
    """Fetch bars via the sanctioned seam and run the FROZEN core."""
    timeframe = predicate_timeframe(success, failure, invalidation)
    now = _mae_runtime.clock()
    lookback_days = lookback_days_covering(activation_ts, now)
    bar_series = _mae_runtime.get_closed_bars(symbol, timeframe, lookback_days)
    return _grading.evaluate_criteria(
        bars=bar_series.bars,
        timeframe=timeframe,
        tick_size=tick_size,
        success=success,
        failure=failure,
        invalidation=invalidation,
        horizon_end=horizon_end,
        now=now,
    )


def compute_pnl(ledger: Ledger, thesis_id: str, direction: str) -> Decimal | None:
    """Sigma signed fill notionals net of fees (§10.2/§10.3), Decimal
    end-to-end. `None` when there are zero `FillRecorded` events for this
    thesis — never a fabricated `Decimal("0")` break-even datapoint
    (ASSUMPTIONS 71, CTO override).

    Fill-ordering convention (ASSUMPTIONS 69, FLAGGED — `contracts.Fill`
    carries no `side` field): entry = earliest `payload.ts_utc`, exit =
    latest. Multi-fill partial exits are out of scope this batch — a
    single-fill thesis has entry == exit (zero gross, fees still deducted).
    """
    fills = [
        event
        for event in ledger.query(EventFilter(types=["FillRecorded"]))
        if event.payload.get("thesis_id") == thesis_id
    ]
    if not fills:
        return None

    def _fill_ts(event: Event) -> datetime:
        return datetime.fromisoformat(str(event.payload["ts_utc"]))

    fills.sort(key=_fill_ts)
    entry, exit_ = fills[0], fills[-1]
    entry_price = Decimal(str(entry.payload["price"]))
    exit_price = Decimal(str(exit_.payload["price"]))
    qty = Decimal(str(entry.payload["qty"]))
    fees = sum((Decimal(str(f.payload["fees_usd"])) for f in fills), start=Decimal("0"))

    if direction == "short":
        gross = (entry_price - exit_price) * qty
    else:  # "long" — the only pinned/tested case (ASSUMPTIONS 69)
        gross = (exit_price - entry_price) * qty
    return gross - fees
