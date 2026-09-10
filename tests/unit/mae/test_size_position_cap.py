"""RED (SPEC-sizing-cap batch RED-A, T1): `mae.size_position`'s two new
keyword-only inputs (P1) — `price` (replaces `current_price` everywhere it
feeds `atr_position`) and `max_position_usd` (an exact-arithmetic clip, audit
trail preserved on `atr_position_size_usd`/`kelly_position_size_usd`).

Status: neither kwarg exists on the current tree's `size_position` signature
— every AC-1/3/4/5/6a call below currently fails with `TypeError: ...
unexpected keyword argument`. AC-2 fails on the missing `max_position_usd`
output key (today's dict has no such key). AC-6b's price=0 case also fails
with the same TypeError (the kwarg itself is unsupported yet, so the pinned
ValueError from `_sizing.atr_position` is never reached this batch).

Fixtures (SPEC §3, verbatim): F-TIGHT / F-WIDE, 30 flat daily bars each.
Both use `open=close=100` on every bar, so True Range never has a gap term
(`|high-prev_close|`/`|low-prev_close|` both collapse to `high-low` since
`prev_close == 100` always sits inside `[low, high]`) — TR[i] = high-low on
every bar. Wilder ATR(14)'s seed is the simple average of the first 14 TR
values (== the constant TR itself), and the recurrence
`atr[i] = (atr[i-1]*13 + TR[i])/14` holds a constant input at its own value
forever (verified against `volatility.atr`'s own docstring in
`src/tradekit/mae/_indicators/volatility.py` and the identical derivation
already relied on by `test_size_position_verb.py`) — so ATR(14) is EXACTLY
`high - low` for both fixtures, not merely approximately so. No ASSUMPTIONS
flag needed for the ATR smoothing question the dispatch prompt raised.

Seam: `tradekit.mae._runtime.get_daily_bars` by dotted STRING path (same
convention as `test_size_position_verb.py` — no import of `_runtime`, so no
ASSUMPTIONS internal-import exception needed).

AC-4 fixture correction (CTO adjudication 2026-09-10, ASSUMPTIONS 182.8):
the spec's first draft listed price=3 and price=0.00007 as clip boundaries,
but F-TIGHT's uncapped size is `1.25 * price` (units=risk_usd/stop_distance
=5/4=1.25 is PRICE-INDEPENDENT), so at those prices the cap never binds and
the clip — conditional by AC-5 and P1's own trigger text — must not fire.
The boundary cases below therefore use prices where the cap genuinely
binds: 266.00 and 300 under F-TIGHT, and 0.00007 under F-MICRO (a fixture
whose ATR is tiny enough that 1.25e6 units are recommended, $87.50 > $50).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradekit.contracts import AssetRef, Bar, BarSeries
from tradekit.mae import size_position

_SYMBOL = "ETH/USD"


def _bars(*, high: Decimal, low: Decimal, n: int = 30) -> BarSeries:
    start = datetime(2026, 6, 1, tzinfo=UTC)
    bars = [
        Bar(
            ts_open=start + timedelta(days=i),
            open=Decimal("100"),
            high=high,
            low=low,
            close=Decimal("100"),
            volume=Decimal("1000"),
        )
        for i in range(n)
    ]
    asset = AssetRef(
        symbol=_SYMBOL, venue="kraken", asset_class="crypto", tick_size=Decimal("0.01")
    )
    return BarSeries(asset=asset, timeframe="1d", bars=bars, source="fake-kraken")


def _f_tight_bars(symbol: str, lookback_days: int) -> BarSeries:
    """F-TIGHT (SPEC §3): high=101/low=99 -> ATR(14)=2 exactly,
    stop_distance = 2*2.0 = 4. At equity=500/risk_pct=0.01: risk_usd=5,
    atr_units=5/4=1.25 (price-independent) -> atr_size_usd=1.25*price."""
    return _bars(high=Decimal("101"), low=Decimal("99"))


def _f_wide_bars(symbol: str, lookback_days: int) -> BarSeries:
    """F-WIDE (SPEC §3): high=110/low=90 -> ATR(14)=20 exactly,
    stop_distance = 20*2.0 = 40. At equity=500/risk_pct=0.01: risk_usd=5,
    atr_units=5/40=0.125 (price-independent) -> atr_size_usd=0.125*price."""
    return _bars(high=Decimal("110"), low=Decimal("90"))


def _f_micro_bars(symbol: str, lookback_days: int) -> BarSeries:
    """F-MICRO (AC-4 tiny-price boundary): a sub-cent asset — every bar
    open=close=0.00007, high=0.000071, low=0.000069 -> TR = 0.000002 on
    every bar (prev close inside [low, high], same argument as F-TIGHT), so
    ATR(14) ~= 2e-6 (float arithmetic on these magnitudes is not exact, but
    only the BINDING decision depends on it: stop_distance ~= 4e-6,
    atr_units ~= 5/4e-6 = 1.25e6, uncapped size ~= 1.25e6 * 0.00007 = $87.50
    > $50 -> the cap binds by a wide margin). The clipped units are then
    exact Decimal arithmetic, independent of the float ATR."""
    start = datetime(2026, 6, 1, tzinfo=UTC)
    bars = [
        Bar(
            ts_open=start + timedelta(days=i),
            open=Decimal("0.00007"),
            high=Decimal("0.000071"),
            low=Decimal("0.000069"),
            close=Decimal("0.00007"),
            volume=Decimal("1000000"),
        )
        for i in range(30)
    ]
    asset = AssetRef(
        symbol=_SYMBOL, venue="kraken", asset_class="crypto", tick_size=Decimal("0.0000001")
    )
    return BarSeries(asset=asset, timeframe="1d", bars=bars, source="fake-kraken")


# ---------------------------------------------------------------------------
# AC-1 — price override replaces current_price everywhere it feeds sizing
# ---------------------------------------------------------------------------


def test_ac1_price_override_replaces_current_price_in_stop_and_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CONTRACT (AC-1, P1): explicit `price=` replaces `current_price`
    everywhere it feeds `atr_position` (stop_pct, recommended_size_usd,
    recommended_units); `max_position_usd` stays None (no clip). F-WIDE at
    price=105 — hand math, independent of the code under test: ATR=20,
    stop_distance=40, stop_pct=40/105; risk_usd=500*0.01=5,
    atr_units=5/40=0.125 (price-independent); atr_size_usd=0.125*105=13.125."""
    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", _f_wide_bars)

    result = size_position(_SYMBOL, Decimal("500"), price=Decimal("105"))

    assert result["current_price"] == 105.0
    assert result["stop_pct"] == pytest.approx(40 / 105)
    assert result["recommended_units"] == pytest.approx(0.125)
    assert result["recommended_size_usd"] == pytest.approx(13.125)
    assert result["max_position_usd"] is None
    assert "capped_by_max_position" not in result["warnings"]


# ---------------------------------------------------------------------------
# AC-2 — no price given: today's behavior, byte-identical, plus the one new
# key. Uses F-WIDE (not test_size_position_verb.py's ATR=2/price=100
# fixture) so this is not a duplicate of that file's cases.
# ---------------------------------------------------------------------------


def test_ac2_no_price_is_a_regression_pin_plus_the_new_echoed_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CONTRACT (AC-2, P1 regression pin): calling WITHOUT `price` must
    match today's last-closed-daily-close basis exactly AND gain exactly
    one new `max_position_usd: None` key. F-WIDE at its own natural close
    (100, every bar closes at 100): ATR=20, stop_distance=40, risk_usd=5,
    atr_units=5/40=0.125 (hand math) -> atr_size_usd=0.125*100=12.5."""
    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", _f_wide_bars)

    result = size_position(_SYMBOL, Decimal("500"))

    assert result["current_price"] == pytest.approx(100.0)
    assert result["atr_position_size_usd"] == pytest.approx(12.5)
    assert result["recommended_size_usd"] == pytest.approx(12.5)
    assert result["recommended_units"] == pytest.approx(0.125)
    assert result["max_position_usd"] is None, "no cap passed -> the echoed cap is None"


# ---------------------------------------------------------------------------
# AC-3 — cap binds: clip engages, audit-trail values stay uncapped
# ---------------------------------------------------------------------------


def test_ac3_cap_binds_clips_units_and_size_audit_trail_stays_uncapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CONTRACT (AC-3, P1 clip): F-TIGHT at price=100 -> uncapped atr size
    is 1.25 units * $100 = $125 (SPEC §3's own pinned F-TIGHT number),
    which exceeds max_position_usd=$50 -> clip engages: units =
    floor8dp(50/100) = 0.5, size = 0.5*100 = $50.0 exactly (hand math).
    `atr_position_size_usd` (the audit trail) keeps its UNCAPPED $125;
    `warnings` carries `capped_by_max_position`."""
    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", _f_tight_bars)

    result = size_position(
        _SYMBOL, Decimal("500"), price=Decimal("100"), max_position_usd=Decimal("50")
    )

    assert result["recommended_units"] == 0.5
    assert result["recommended_size_usd"] == 50.0
    assert result["atr_position_size_usd"] == pytest.approx(125.0)
    assert result["max_position_usd"] == 50.0
    assert "capped_by_max_position" in result["warnings"]


# ---------------------------------------------------------------------------
# AC-4 — exact-arithmetic boundary (GOLDEN): 266.00 and 300 under F-TIGHT,
# 0.00007 under F-MICRO — the three prices where the cap genuinely binds
# (ASSUMPTIONS 182.8; the first draft's price=3/0.00007-under-F-TIGHT
# boundaries were retired because the cap never binds there, see module
# docstring).
# ---------------------------------------------------------------------------


def test_ac4_price_266_boundary_clip_exact_8dp_never_exceeds_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GOLDEN (AC-4, F-TIGHT/equity=500/risk=1%, price=266.00): uncapped
    atr size = 1.25 units (price-independent, per AC-3's own $125-at-$100
    pin) * $266.00 = $332.50, which exceeds the $50 cap either way this
    gets read, so the clip unambiguously engages here.

    Independent derivation of the clipped units (never computed by calling
    the code under test): max_position_usd/price = 50/266 = 25/133. Long
    division: 25*10^10 // 133 = 1_879_699_248 remainder 16 (133 *
    1_879_699_248 = 249_999_999_984, + 16 = 25_000_000_000 = 25*10^9...
    carrying the extra factor of 10 gives 0.1879699248... to 10dp), so the
    ROUND_DOWN 8dp truncation is 0.18796992 (digits 1,8,7,9,6,9,9,2).
    Cross-check: 0.18796992 * 266 = 0.18796992*(270-4) =
    50.7518784 - 0.75187968 = 49.99999872 <= 50, confirming truncation
    (not rounding) direction."""
    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", _f_tight_bars)
    price = Decimal("266.00")

    result = size_position(
        _SYMBOL, Decimal("500"), price=price, max_position_usd=Decimal("50")
    )

    units = Decimal(str(result["recommended_units"]))
    assert units == Decimal("0.18796992")
    assert units * price <= Decimal("50")
    assert "capped_by_max_position" in result["warnings"]


def test_ac4_price_300_boundary_clip_is_a_non_terminating_quotient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GOLDEN (AC-4 sub-case, price=300, F-TIGHT): uncapped size is
    1.25*300 = $375 > $50, so the cap binds. 50/300 = 1/6 = 0.1666...,
    non-terminating; ROUND_DOWN to 8dp is 0.16666666 (a float-then-round
    implementation would give 0.16666667 and overshoot: 0.16666667*300 =
    50.000001 > 50). Cross-check: 0.16666666*300 = 49.999998 <= 50."""
    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", _f_tight_bars)
    price = Decimal("300")

    result = size_position(
        _SYMBOL, Decimal("500"), price=price, max_position_usd=Decimal("50")
    )

    units = Decimal(str(result["recommended_units"]))
    assert units == Decimal("0.16666666")
    assert units * price <= Decimal("50")
    assert "capped_by_max_position" in result["warnings"]


def test_ac4_price_0_00007_boundary_clip_at_a_sub_cent_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GOLDEN (AC-4 sub-case, price=0.00007, F-MICRO): the cap binds (see
    `_f_micro_bars`: ~$87.50 uncapped). 50/0.00007 = 714285.714285714...,
    ROUND_DOWN to 8dp = 714285.71428571. Cross-check: 714285.71428571 *
    0.00007 = 49.99999999999997 <= 50. A float division would carry
    714285.7142857143 and, quantized by the caller, could land on
    ...71428572 and overshoot by 7e-13 — enough for R-005's `<=` to deny."""
    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", _f_micro_bars)
    price = Decimal("0.00007")

    result = size_position(
        _SYMBOL, Decimal("500"), price=price, max_position_usd=Decimal("50")
    )

    units = Decimal(str(result["recommended_units"]))
    assert units == Decimal("714285.71428571")
    assert units * price <= Decimal("50")
    assert "capped_by_max_position" in result["warnings"]


# ---------------------------------------------------------------------------
# AC-5 — cap present but NOT binding: values unchanged, no warning. This is
# the test that PROVES the clip is conditional (see ASSUMPTIONS-FLAG 1).
# ---------------------------------------------------------------------------


def test_ac5_cap_present_but_not_binding_leaves_values_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CONTRACT (AC-5): F-WIDE at price=105 with max_position_usd=50
    present but NOT binding (uncapped $13.125 < $50, AC-1's own hand math)
    -> output matches AC-1's uncapped values exactly except the echoed
    `max_position_usd` key; no `capped_by_max_position` warning."""
    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", _f_wide_bars)

    result = size_position(
        _SYMBOL, Decimal("500"), price=Decimal("105"), max_position_usd=Decimal("50")
    )

    assert result["current_price"] == 105.0
    assert result["recommended_units"] == pytest.approx(0.125)
    assert result["recommended_size_usd"] == pytest.approx(13.125)
    assert result["max_position_usd"] == 50.0
    assert "capped_by_max_position" not in result["warnings"]


# ---------------------------------------------------------------------------
# AC-6a/AC-6b — validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_cap", [Decimal("0"), Decimal("-1")])
def test_ac6a_non_positive_max_position_usd_raises_value_error(
    monkeypatch: pytest.MonkeyPatch, bad_cap: Decimal
) -> None:
    """CONTRACT (AC-6a): a non-positive `max_position_usd` is a caller bug
    (P1: "a non-positive cap sizes nothing and is a caller bug") ->
    `ValueError` whose message names the offending parameter."""
    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", _f_tight_bars)

    with pytest.raises(ValueError, match="max_position_usd"):
        size_position(
            _SYMBOL, Decimal("500"), price=Decimal("100"), max_position_usd=bad_cap
        )


def test_ac6b_non_positive_price_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CONTRACT (AC-6b): `price<=0` -> `ValueError` — the pre-existing
    `_sizing.atr_position` message (P1: "do not pre-check"; `price` simply
    flows into `atr_position(price=...)` unchanged)."""
    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", _f_tight_bars)

    with pytest.raises(ValueError):
        size_position(_SYMBOL, Decimal("500"), price=Decimal("0"))


# ---------------------------------------------------------------------------
# AC-20 — P7 (review round 24 F1, ASSUMPTIONS 182.10): `size_scale`, a
# strategy's own restricted-size fraction, applied AFTER the cap clip in
# exact Decimal arithmetic. The defect this fixes: `hud._build`/`thesis.
# _submit` used to multiply the ALREADY-RETURNED qty by
# `StrategyDef.size_scale` themselves, so the two call sites' own
# multiplications could drift (one applying it, one forgetting to) and the
# recorded `SizingComputed` notional never matched the scaled ticket ->
# every S4 draft (size_scale=0.5) died at binding on R-012. Moving the
# scale INSIDE `size_position` makes it the single source of truth for
# both call sites.
# ---------------------------------------------------------------------------


def test_ac20a_default_size_scale_is_a_byte_identical_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CONTRACT (AC-20a, P7 regression pin): omitting `size_scale` (default
    `Decimal("1")`) must match AC-1's own uncapped F-WIDE numbers exactly,
    plus the new echoed `size_scale: 1.0` key — every pre-existing caller
    (`strategy_key=""`/no claiming def) is unaffected."""
    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", _f_wide_bars)

    result = size_position(_SYMBOL, Decimal("500"), price=Decimal("105"))

    assert result["recommended_units"] == pytest.approx(0.125)
    assert result["recommended_size_usd"] == pytest.approx(13.125)
    assert result["size_scale"] == 1.0


def test_ac20b_size_scale_applies_after_the_cap_clip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CONTRACT (AC-20b, P7's own trigger case — mirrors S4's real
    `size_scale=Decimal("0.5")`): F-TIGHT at price=100 with
    `max_position_usd=50` clips to 0.5 units / $50.0 (AC-3's own pin)
    FIRST, THEN `size_scale=0.5` halves the CLIPPED values to 0.25 units /
    $25.0 — never 1.25*0.5=0.625 units (which would be scale-before-clip,
    the wrong order) and never re-deriving from the uncapped $125."""
    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", _f_tight_bars)

    result = size_position(
        _SYMBOL,
        Decimal("500"),
        price=Decimal("100"),
        max_position_usd=Decimal("50"),
        size_scale=Decimal("0.5"),
    )

    assert result["recommended_units"] == 0.25
    assert result["recommended_size_usd"] == 25.0
    assert result["atr_position_size_usd"] == pytest.approx(125.0), (
        "AC-20b: the audit trail stays the fully-uncapped, fully-unscaled value"
    )
    assert result["max_position_usd"] == 50.0
    assert result["size_scale"] == 0.5
    assert "capped_by_max_position" in result["warnings"]


def test_ac20c_size_scale_applies_even_when_the_cap_never_binds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CONTRACT (AC-20c): F-WIDE at price=105, NO cap passed at all —
    `size_scale=0.5` still halves the uncapped AC-1 numbers exactly
    (0.125 -> 0.0625 units, $13.125 -> $6.5625), proving the scale is
    unconditional (unlike the clip, which only fires when it binds)."""
    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", _f_wide_bars)

    result = size_position(
        _SYMBOL, Decimal("500"), price=Decimal("105"), size_scale=Decimal("0.5")
    )

    assert result["recommended_units"] == pytest.approx(0.0625)
    assert result["recommended_size_usd"] == pytest.approx(6.5625)
    assert result["max_position_usd"] is None
    assert result["size_scale"] == 0.5
    assert "capped_by_max_position" not in result["warnings"]


@pytest.mark.parametrize("bad_scale", [Decimal("0"), Decimal("-0.5"), Decimal("1.01")])
def test_ac20d_size_scale_outside_0_1_raises_value_error(
    monkeypatch: pytest.MonkeyPatch, bad_scale: Decimal
) -> None:
    """CONTRACT (AC-20d): `size_scale` must be `> 0` and `<= 1` — zero,
    negative, and >1 (an amplifier, never a caller's intent) are all caller
    bugs -> `ValueError` naming the offending parameter."""
    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", _f_tight_bars)

    with pytest.raises(ValueError, match="size_scale"):
        size_position(_SYMBOL, Decimal("500"), price=Decimal("100"), size_scale=bad_scale)


def test_ac20e_scaled_units_are_requantized_to_8dp_round_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CONTRACT (P7, review round 25 M12 killer): the scale step re-quantizes
    UNITS to 8dp ROUND_DOWN and derives the size from them. F-TIGHT, price
    105, cap 50: clip 50/105 -> 0.47619047; *0.5 = 0.238095235 (9dp) ->
    0.23809523; size = exactly 0.23809523 * 105 = 24.99999915. Scaling the
    float outputs without the quantize leaves 0.238095235 / 24.999999675 —
    an unexecutable 9dp unit count and a record that is no longer
    units * price."""
    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", _f_tight_bars)

    result = size_position(
        _SYMBOL,
        Decimal("500"),
        price=Decimal("105"),
        max_position_usd=Decimal("50"),
        size_scale=Decimal("0.5"),
    )

    assert result["recommended_units"] == 0.23809523
    assert result["recommended_size_usd"] == 24.99999915
