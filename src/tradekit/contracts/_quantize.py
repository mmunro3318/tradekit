"""Tick-size quantization boundary (DESIGN §13, TD-23, G2)."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal


def quantize(value: float | Decimal | str, tick_size: Decimal) -> Decimal:
    """Snap ``value`` onto the tick *grid*; result carries the tick's exponent.

    Grid, not exponent: ticks like 0.05, 0.5, or 5 (real Kraken pairs) are not
    powers of ten, so we round value/tick to an integer step count and scale
    back — ``value.quantize(tick)`` alone would only match decimal places and
    let off-grid prices through (reviewer D1).

    Floats convert via ``repr`` — the shortest string that round-trips — so
    ``10.049999999999999`` stays a hair under 10.05 rather than picking up the
    full binary expansion, then one rounding lands it ON the tick (G2).
    ROUND_HALF_EVEN is pinned (ASSUMPTIONS 1): banker's rounding is bias-free
    over many grades and platform-independent.
    """
    if isinstance(value, float):
        value = Decimal(repr(value))
    elif isinstance(value, str):
        value = Decimal(value)
    steps = (value / tick_size).to_integral_value(rounding=ROUND_HALF_EVEN)
    return (steps * tick_size).quantize(tick_size, rounding=ROUND_HALF_EVEN)
