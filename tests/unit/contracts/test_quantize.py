"""quantize(value, tick_size) — the float→Decimal boundary (DESIGN §13, TD-23, G2).

Every float leaving MAE numerics crosses this function. If it mis-rounds by one
tick, a `gte`/`lte` grading predicate flips and a thesis grades wrong.
"""

from decimal import Decimal

from tradekit.contracts import quantize


def test_float_noise_cannot_flip_a_tick() -> None:
    got = quantize(10.049999999999999, Decimal("0.01"))
    assert got == Decimal("10.05"), (
        f"got {got!r}: float noise a hair under 10.05 must land ON the 10.05 tick, "
        "otherwise a gte grading predicate flips on representation error (G2, DESIGN §13)"
    )


def test_returns_decimal_at_tick_scale() -> None:
    got = quantize(10.049999999999999, Decimal("0.01"))
    assert isinstance(got, Decimal), (
        f"quantize returned {type(got).__name__}: money leaves the boundary as Decimal "
        "only (TD-3) — a float return re-introduces the noise quantize exists to kill"
    )
    assert got.as_tuple().exponent == -2, (
        f"result exponent {got.as_tuple().exponent}, expected -2: output must carry the "
        "tick's scale so predicate-vs-measured comparisons are like-for-like (§13)"
    )


def test_crypto_tick_four_decimals() -> None:
    got = quantize(2.3456999999999997, Decimal("0.0001"))
    assert got == Decimal("2.3457"), (
        f"got {got!r}: per-pair crypto ticks (AssetRef.tick_size, §13) must quantize as "
        "cleanly as equity pennies — 0.0001 grids are the common Kraken case"
    )


def test_idempotent_on_already_quantized_decimal() -> None:
    once = quantize(Decimal("10.05"), Decimal("0.01"))
    twice = quantize(once, Decimal("0.01"))
    assert once == Decimal("10.05") and twice == once, (
        f"{once!r} -> {twice!r}: re-quantizing an on-tick Decimal must be a no-op — "
        "predicates are quantized at submit and measured values at grading, same utility "
        "both sides (§13), so a second pass must never move the value"
    )


def test_midpoint_rounding_pinned_half_even() -> None:
    # PINNED CHOICE: ROUND_HALF_EVEN (banker's rounding) — bias-free over many
    # grades, matches IEEE-754 default. Recorded in tests/ASSUMPTIONS.md for CTO
    # ratification; if the implementation picks another mode, change it THERE
    # and update this pin in the same commit.
    lo = quantize(Decimal("10.045"), Decimal("0.01"))
    hi = quantize(Decimal("10.055"), Decimal("0.01"))
    assert lo == Decimal("10.04"), (
        f"quantize(10.045) -> {lo!r}: exact midpoint must round to the even neighbor "
        "10.04 (ROUND_HALF_EVEN pinned) — an unpinned mode makes grading platform-dependent"
    )
    assert hi == Decimal("10.06"), (
        f"quantize(10.055) -> {hi!r}: exact midpoint must round to the even neighbor "
        "10.06 (ROUND_HALF_EVEN pinned)"
    )
