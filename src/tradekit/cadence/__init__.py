"""`tradekit.cadence` — T2's pure exit-trigger evaluation (SPEC-cadence.md
T2, "Exit TRIGGER evaluation", docs/specs/SPEC-cadence.md:98-104).

`exit_trigger` only decides WHEN to flatten an open position (stop/target/
horizon touch on the last CLOSED bar); it never decides HOW to close it —
that is `broker._pipeline.execute_exit`'s job. Pure: no I/O, no clock reads —
the caller supplies `now` (mirrors every other TD-17 "no real clock" seam
in this codebase).

Signature/tie-break per ASSUMPTIONS 177 (ratified): five keyword-only
params, Decimal prices, aware datetimes; stop wins a same-bar stop/target
tie (conservative, mirrors grading's own ambiguous-bar doctrine).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal


def exit_trigger(
    *,
    close: Decimal,
    stop_price: Decimal,
    target_price: Decimal,
    now: datetime,
    horizon_end: datetime,
) -> Literal["stop", "target", "horizon"] | None:
    """SPEC-cadence.md T2's three trigger conditions, evaluated in
    stop-first order so a degenerate bracket (stop==target==close) resolves
    to "stop" rather than "target": close<=stop_price -> "stop" (inclusive
    touch); else close>=target_price -> "target" (inclusive touch); else
    now>=horizon_end -> "horizon" (inclusive); else None (no trigger this
    bar)."""
    if close <= stop_price:
        return "stop"
    if close >= target_price:
        return "target"
    if now >= horizon_end:
        return "horizon"
    return None
