"""Tick-size quantization boundary (DESIGN §13, TD-23, G2)."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal


def quantize(value: float | Decimal | str, tick_size: Decimal) -> Decimal:
    """Snap ``value`` onto the tick grid; result carries the tick's exponent.

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
    return value.quantize(tick_size, rounding=ROUND_HALF_EVEN)
