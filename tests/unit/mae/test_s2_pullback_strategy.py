"""tests for STRATEGY-PACK S2 (`s2_pullback`) — the `ema_above`/`rsi_band`
scan-vocabulary additions and the S2 `StrategyDef` registry entry
(docs/design/STRATEGY-PACK.md "Vocabulary additions" + "S2 —
Pullback-continuation"; tests/ASSUMPTIONS.md 172/173 govern the shared
`scan_confluence`/registry semantics this batch builds on).

RED stage: `ema_above`/`rsi_band` are not recognized by
`_scanner._precompute_indicators`/`_evaluate_symbol_timeframe` yet (they
are silently no-op filter keys today -- present in a `filters` dict but
never added to the `checks` list, so they contribute zero tags and are
never validated). `s2_pullback` does not exist in `_strategies.STRATEGIES`
yet. Every test below exercises PUBLIC surfaces only
(`tradekit.mae.scan_confluence`, `tradekit.mae.STRATEGIES`/
`STRATEGY_BY_KEY`) -- same house style/seams as
`test_scan_confluence_verb.py` and `test_strategies_registry.py`, which
this file mirrors (bars faked via `"tradekit.mae._runtime.get_closed_bars"`
string-path monkeypatch, clock via `"tradekit.mae._runtime._clock"`).

=== DOC-VS-DISPATCH DISCREPANCY (flag, not improvised) ===
STRATEGY-PACK.md's own S2 code sample (line ~47) writes
`"macd_signal": "bullish"` for the 4h leg. `"bullish"` is NOT a member of
`_scanner._MACD_ALLOWED` (`{"bullish_cross", "bearish_cross"}`,
`_vocab.MacdSignal`) -- passing it through `scan_confluence` raises
`ValueError` at the closed-vocabulary gate. This is the SAME typo pattern
already documented and resolved in `_scanner.py`'s own module docstring
for S1/canonical (`"macd_signal": "bullish_cross" | "bearish_cross" --
canonical's OWN value strings, NOT the sprint-doc addendum's
"bullish"/"bearish", which contradicts canonical"). The dispatch prompt's
PINNED block already carries the corrected `"bullish_cross"` value; this
suite follows the dispatch prompt (the only value that is actually valid
production vocabulary) and flags the doc's code sample as the stale
member, mirroring the S1 precedent -- not a new semantic choice.

=== ASSUMPTIONS ESCAPE HATCH ===
ASSUMPTION-FLAG S2-1 (rsi_band exact-boundary FAIL fixtures): the mission
pins RSI exactly 34.99/50.01 as leg-failing boundary cases. Hand-deriving
a bar fixture that lands Wilder RSI(14) at those exact two-decimal values
(as opposed to the exact-integer-ratio 35.00/50.00 FIRES cases below, which
admit a clean rational RS) requires a non-terminating-fraction gain/loss
split with no equally clean by-hand derivation. Reading adopted here (the
dispatch's own escape hatch: "if hitting an exact RSI boundary via bar
fixtures is impractical, test the band predicate ... with fixtures that
land clearly inside/outside"): the FAIL side is exercised with RSI values
UNAMBIGUOUSLY outside `[35, 50]` (0.0 and 100.0, both far outside either
edge, reusing the established pure-loss/pure-gain derivation shape from
`test_scan_confluence_verb.py`'s `_RSI_OVERSOLD_CLOSES`/`_RSI_HOT_CLOSES`),
while the FIRES side gets true from-spec hand-derived goldens at the exact
pinned edges (35.0, 50.0). CTO ratification needed if a literal 34.99/50.01
fixture is required rather than this reading.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradekit.contracts import AssetRef, Bar, BarSeries
from tradekit.mae import STRATEGIES, STRATEGY_BY_KEY, build_registry, scan_confluence


def _bar(ts_open: datetime, close: float, volume: float = 100.0) -> Bar:
    return Bar(
        ts_open=ts_open,
        open=Decimal(str(close)),
        high=Decimal(str(close + 0.3)),
        low=Decimal(str(close - 0.3)),
        close=Decimal(str(close)),
        volume=Decimal(str(volume)),
    )


def _series(
    closes: list[float],
    volumes: list[float] | None = None,
    *,
    symbol: str = "BTC/USD",
    timeframe: str = "4h",
) -> BarSeries:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    vols = volumes if volumes is not None else [100.0] * len(closes)
    pairs = list(zip(closes, vols, strict=True))
    bars = [_bar(start + timedelta(hours=i), c, v) for i, (c, v) in enumerate(pairs)]
    asset = AssetRef(symbol=symbol, venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))
    return BarSeries(asset=asset, timeframe=timeframe, bars=bars, source="fake-kraken")


def _install_fixed_clock(monkeypatch, now: datetime) -> None:
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: now)


def _install_bars_by_key(
    monkeypatch, series_by_key: dict[tuple[str, str], BarSeries]
) -> list[tuple[str, str, int]]:
    calls: list[tuple[str, str, int]] = []

    def _fake_get_closed_bars(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
        calls.append((symbol, timeframe, lookback_days))
        return series_by_key[(symbol, timeframe)]

    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_get_closed_bars)
    return calls


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# ema_above: flat 55-bar series -> EMA(50) == 100.0 everywhere it's non-None
# (seed = mean(100...100) = 100.0; recurrence preserves 100.0 forever on a
# constant series) AND last close == 100.0 -> close == EMA(50) EXACTLY.
# Pinned semantics: "last close > EMA(n)" is STRICT -> must NOT fire.
_EMA_EXACT_EQUAL_CLOSES = [100.0] * 55

# ema_above: 51-bar series, flat 100.0 for the first 50 (seeds EMA(50) at
# exactly 100.0), then one final bar at 101.0. EMA(50)[-1] =
# 101.0*k + 100.0*(1-k), k = 2/51 = 0.0392156862745098 ->
# EMA(50)[-1] = 100.0 + k = 100.0392156862745 < 101.0 -> close > EMA(50) ->
# fires (verified independently against trend.ema during fixture
# construction; the golden precision itself lives in
# test_ema_s2_golden.py, this fixture only needs the FIRES category).
_EMA_FIRES_CLOSES = [100.0] * 50 + [101.0]

# ema_above: 49 bars, below EMA(50)'s 50-bar minimum -> insufficient bars.
_EMA_SHORT_CLOSES = [100.0] * 49

# rsi_band GOLDEN (35.0 exact): 15 closes, 14 diffs = one +7 gain then
# thirteen -1 losses. Hand derivation (Wilder seed, `momentum.rsi`'s own
# pinned recurrence -- "avg_gain = mean(gain[1:period+1])"):
#   gains: [7, 0,0,0,0,0,0,0,0,0,0,0,0,0] (14 diffs) -> sum = 7
#   losses: [0, 1,1,1,1,1,1,1,1,1,1,1,1,1] (14 diffs) -> sum = 13
#   avg_gain = 7/14 = 0.5 ; avg_loss = 13/14 = 0.9285714285714286
#   RS = avg_gain/avg_loss = 0.5 / (13/14) = 0.5 * 14/13 = 7/13
#      = 0.5384615384615384
#   RSI = 100 - 100/(1+RS) = 100 - 100/(20/13) = 100 - 100*13/20
#       = 100 - 65 = 35.0 EXACTLY
_RSI_35_EXACT_CLOSES = [100, 107, 106, 105, 104, 103, 102, 101, 100, 99, 98, 97, 96, 95, 94]

# rsi_band GOLDEN (50.0 exact): 15 closes, 14 diffs alternating +1/-1
# (7 up, 7 down). Hand derivation:
#   avg_gain = 7*1/14 = 0.5 ; avg_loss = 7*1/14 = 0.5
#   RS = 0.5/0.5 = 1.0
#   RSI = 100 - 100/(1+1) = 100 - 50 = 50.0 EXACTLY
_RSI_50_EXACT_CLOSES = [
    100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100
]

# rsi_band FAILS, clearly below [35, 50]: pure-loss run -> RSI(14) == 0.0
# (same derivation shape as test_scan_confluence_verb.py's
# _RSI_OVERSOLD_CLOSES: avg_gain == 0.0 pins RSI to 0 via the rsi() "RS
# would divide by avg_loss, avg_gain==0 gives RS=0" arithmetic).
_RSI_ZERO_CLOSES = [120.0 - i for i in range(20)]

# rsi_band FAILS, clearly above [35, 50]: pure-gain run -> RSI(14) == 100.0
# (avg_loss == 0.0 pins RSI to 100.0 directly per rsi()'s own pinned
# special case; same derivation shape as test_scan_confluence_verb.py's
# _RSI_HOT_CLOSES).
_RSI_HOT_CLOSES = [100.0 + i for i in range(20)]

# S2 end-to-end 4h leg: same already-validated derivation as
# test_strategies_registry.py's _S1_MACD_BULLISH_CLOSES (flat base then an
# accelerating ramp) -- settles a bullish MACD histogram cross AND (60
# bars, comfortably >= EMA(50)'s 50-bar floor) ends with last close
# (149.129...) above EMA(50) (113.328... at that index, independently
# checked during fixture construction) -> both `trend_up` and
# `macd_bullish` tags fire.
_S2_4H_PASS_CLOSES = [100.0] * 40 + [100.0 + i**1.3 for i in range(1, 21)]


# ---------------------------------------------------------------------------
# 2. ema_above filter (BOUNDARY/BEHAVIOR): strict >, exact-equal does not
#    fire, insufficient-bars convention.
# ---------------------------------------------------------------------------


def test_ema_above_fires_trend_up_when_close_strictly_greater(monkeypatch) -> None:
    series = _series(_EMA_FIRES_CLOSES, symbol="BTC/USD", timeframe="4h")
    _install_bars_by_key(monkeypatch, {("BTC/USD", "4h"): series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 27, tzinfo=UTC))

    result = scan_confluence(
        asset_class="crypto",
        legs=[{"timeframe": "4h", "filters": {"ema_above": 50}, "min_tags": 1}],
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    matches = result["matches"]
    assert len(matches) == 1
    assert "trend_up" in matches[0]["legs"]["4h"]["signal_tags"]


def test_ema_above_does_not_fire_when_close_exactly_equals_ema(monkeypatch) -> None:
    # BOUNDARY PIN: "last close > EMA(n)" is strict; close == EMA(n) must
    # NOT fire. Leg fails (0 tags < min_tags=1) and the symbol is absent.
    # RED-PHASE NOTE (self-verify caveat, reported to CTO): this assertion
    # is VACUOUSLY true today -- `ema_above` isn't wired into `_scanner`
    # yet, so ANY input produces 0 tags for this leg, coincidentally
    # matching the correct-implementation "does not fire" outcome. It is
    # still a real regression guard once GREEN lands (a `>=` off-by-one
    # implementation would flip this to a match and fail it), kept as its
    # own test rather than dropped -- flagged here rather than silently
    # left to look like a genuine red failure.
    series = _series(_EMA_EXACT_EQUAL_CLOSES, symbol="BTC/USD", timeframe="4h")
    _install_bars_by_key(monkeypatch, {("BTC/USD", "4h"): series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 27, tzinfo=UTC))

    result = scan_confluence(
        asset_class="crypto",
        legs=[{"timeframe": "4h", "filters": {"ema_above": 50}, "min_tags": 1}],
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    assert result["matches"] == []
    assert "BTC/USD: leg 4h failed (0/1 tags)" in result["warnings"]


def test_ema_above_insufficient_bars_below_period_floor(monkeypatch) -> None:
    # PIN: "EMA(50) needs >= 50 closed 4h bars ... if bars < 50 the leg
    # fails with the standard insufficient-bars warning" -- same
    # convention/wording shape as every other filter's
    # "<symbol> <tf>: insufficient bars for <filter_name>" message
    # (`_precompute_indicators`'s existing pattern).
    series = _series(_EMA_SHORT_CLOSES, symbol="BTC/USD", timeframe="4h")
    _install_bars_by_key(monkeypatch, {("BTC/USD", "4h"): series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 27, tzinfo=UTC))

    result = scan_confluence(
        asset_class="crypto",
        legs=[{"timeframe": "4h", "filters": {"ema_above": 50}, "min_tags": 1}],
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    assert result["matches"] == []
    assert any(
        "BTC/USD 4h: insufficient bars for ema_above" in w for w in result["warnings"]
    ), f"expected the standard insufficient-bars message, got {result['warnings']!r}"


# ---------------------------------------------------------------------------
# 3. rsi_band filter: inclusive-both-ends boundary GOLDENs at 35.0/50.0,
#    clearly-outside FAILS (see ASSUMPTION-FLAG S2-1 above).
# ---------------------------------------------------------------------------


def test_rsi_band_fires_pullback_at_exact_lower_bound_35(monkeypatch) -> None:
    series = _series(
        [float(c) for c in _RSI_35_EXACT_CLOSES], symbol="BTC/USD", timeframe="1h"
    )
    _install_bars_by_key(monkeypatch, {("BTC/USD", "1h"): series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 27, tzinfo=UTC))

    result = scan_confluence(
        asset_class="crypto",
        legs=[{"timeframe": "1h", "filters": {"rsi_band": [35, 50]}, "min_tags": 1}],
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    matches = result["matches"]
    assert len(matches) == 1
    assert "pullback" in matches[0]["legs"]["1h"]["signal_tags"]


def test_rsi_band_fires_pullback_at_exact_upper_bound_50(monkeypatch) -> None:
    series = _series(
        [float(c) for c in _RSI_50_EXACT_CLOSES], symbol="BTC/USD", timeframe="1h"
    )
    _install_bars_by_key(monkeypatch, {("BTC/USD", "1h"): series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 27, tzinfo=UTC))

    result = scan_confluence(
        asset_class="crypto",
        legs=[{"timeframe": "1h", "filters": {"rsi_band": [35, 50]}, "min_tags": 1}],
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    matches = result["matches"]
    assert len(matches) == 1
    assert "pullback" in matches[0]["legs"]["1h"]["signal_tags"]


def test_rsi_band_fails_clearly_below_lower_bound(monkeypatch) -> None:
    # RED-PHASE NOTE: same vacuous-pass-at-red caveat as
    # test_ema_above_does_not_fire_when_close_exactly_equals_ema above --
    # `rsi_band` isn't wired in yet, so this "fails" outcome is currently
    # coincidental (0 tags either way), not yet a genuine proof of the
    # predicate. Still a real regression guard post-GREEN.
    series = _series(_RSI_ZERO_CLOSES, symbol="BTC/USD", timeframe="1h")
    _install_bars_by_key(monkeypatch, {("BTC/USD", "1h"): series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 27, tzinfo=UTC))

    result = scan_confluence(
        asset_class="crypto",
        legs=[{"timeframe": "1h", "filters": {"rsi_band": [35, 50]}, "min_tags": 1}],
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    assert result["matches"] == []
    assert "BTC/USD: leg 1h failed (0/1 tags)" in result["warnings"]


def test_rsi_band_fails_clearly_above_upper_bound(monkeypatch) -> None:
    # RED-PHASE NOTE: same vacuous-pass-at-red caveat as the lower-bound
    # test above.
    series = _series(_RSI_HOT_CLOSES, symbol="BTC/USD", timeframe="1h")
    _install_bars_by_key(monkeypatch, {("BTC/USD", "1h"): series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 27, tzinfo=UTC))

    result = scan_confluence(
        asset_class="crypto",
        legs=[{"timeframe": "1h", "filters": {"rsi_band": [35, 50]}, "min_tags": 1}],
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    assert result["matches"] == []
    assert "BTC/USD: leg 1h failed (0/1 tags)" in result["warnings"]


# ---------------------------------------------------------------------------
# 4. rsi_band validation: malformed values -> loud pre-fetch ValueError
#    (TICKET-001 closed-vocab doctrine, mirroring scan_confluence's existing
#    macd_signal/bb_position validation style: raised at the same "before
#    any bar fetch" gate, `pytest.raises` + an empty fake-fetch call list
#    proves the pre-fetch ordering, same idiom as
#    test_scan_confluence_verb.py's
#    test_unknown_filter_value_raises_before_any_bar_fetch).
# ---------------------------------------------------------------------------


def test_rsi_band_inverted_bounds_raises_before_fetch(monkeypatch) -> None:
    calls = _install_bars_by_key(monkeypatch, {})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 27, tzinfo=UTC))

    with pytest.raises(ValueError, match="rsi_band"):
        scan_confluence(
            asset_class="crypto",
            legs=[{"timeframe": "1h", "filters": {"rsi_band": [50, 35]}, "min_tags": 1}],
            symbols=["BTC/USD"],
            regime_gate=False,
        )

    assert calls == [], "inverted rsi_band bounds must be validated before any bar fetch"


def test_rsi_band_wrong_arity_raises_before_fetch(monkeypatch) -> None:
    calls = _install_bars_by_key(monkeypatch, {})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 27, tzinfo=UTC))

    with pytest.raises(ValueError, match="rsi_band"):
        scan_confluence(
            asset_class="crypto",
            legs=[{"timeframe": "1h", "filters": {"rsi_band": [35]}, "min_tags": 1}],
            symbols=["BTC/USD"],
            regime_gate=False,
        )

    assert calls == [], "wrong-arity rsi_band must be validated before any bar fetch"


def test_rsi_band_non_numeric_raises_before_fetch(monkeypatch) -> None:
    calls = _install_bars_by_key(monkeypatch, {})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 27, tzinfo=UTC))

    with pytest.raises(ValueError, match="rsi_band"):
        scan_confluence(
            asset_class="crypto",
            legs=[{"timeframe": "1h", "filters": {"rsi_band": ["a", "b"]}, "min_tags": 1}],
            symbols=["BTC/USD"],
            regime_gate=False,
        )

    assert calls == [], "non-numeric rsi_band must be validated before any bar fetch"


# ---------------------------------------------------------------------------
# 5. S2 registry def: field-for-field pin (STRATEGY-PACK.md verbatim, with
#    macd_signal corrected to "bullish_cross" per the doc-vs-dispatch
#    discrepancy flagged in the module docstring), registered AFTER S1.
# ---------------------------------------------------------------------------


def test_s2_strategy_def_field_for_field_pin() -> None:
    s2 = STRATEGY_BY_KEY["s2_pullback"]
    assert s2.key == "s2_pullback"
    assert s2.side == "buy"
    assert len(s2.legs) == 2

    leg_4h, leg_1h = s2.legs
    assert leg_4h["timeframe"] == "4h"
    assert leg_4h["filters"] == {"ema_above": 50, "macd_signal": "bullish_cross"}
    assert leg_4h["min_tags"] == 2

    assert leg_1h["timeframe"] == "1h"
    assert leg_1h["filters"] == {"rsi_band": [35, 50]}
    assert leg_1h["min_tags"] == 1

    assert s2.regime_families == ("momentum", "breakout")
    assert s2.size_scale == Decimal("1")
    assert s2.r_multiple_override is None
    assert s2.tag == "s2_pullback"
    # SPEC-cadence T1-AC-5 (supersedes 173.1's batch-scoped 7-field ruling):
    # S2 default horizon_hours 168 (7d) -- S2 has no time-stop restriction.
    assert s2.horizon_hours == 168


def test_s2_registered_after_s1_in_strategies_tuple() -> None:
    # PIN: "Registry order after this lands: S1, then S2 (S1's stricter
    # volume-confirmed signal outranks; first-match-wins)."
    keys = [s.key for s in STRATEGIES]
    # Prefix pin, not exact-tuple (CTO adjudication at S4 registration):
    # an exact-equality pin breaks every time a strategy is appended —
    # the fragile-exact-pin class from the round-13 lesson. S2's own pin
    # is only "S1 before S2".
    assert keys[:2] == ["s1_momentum", "s2_pullback"]


def test_strategy_by_key_contains_s2_and_matches_build_registry() -> None:
    registry = build_registry(STRATEGIES)
    assert registry["s2_pullback"] is STRATEGY_BY_KEY["s2_pullback"]
    assert STRATEGY_BY_KEY["s2_pullback"].key == "s2_pullback"


def test_s2_strategy_def_is_frozen_immutable() -> None:
    s2 = STRATEGY_BY_KEY["s2_pullback"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        s2.side = "sell"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 6. S2 end-to-end through scan_confluence: both legs pass -> match with
#    both legs' tags; 1h RSI hot -> fails leg 2 with the pinned warning.
# ---------------------------------------------------------------------------


def test_s2_end_to_end_both_legs_pass_yields_confluence_match(monkeypatch) -> None:
    series_4h = _series(_S2_4H_PASS_CLOSES, symbol="BTC/USD", timeframe="4h")
    series_1h = _series(
        [float(c) for c in _RSI_50_EXACT_CLOSES], symbol="BTC/USD", timeframe="1h"
    )
    _install_bars_by_key(
        monkeypatch, {("BTC/USD", "4h"): series_4h, ("BTC/USD", "1h"): series_1h}
    )
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 27, tzinfo=UTC))

    s2 = STRATEGY_BY_KEY["s2_pullback"]
    result = scan_confluence(
        asset_class="crypto",
        legs=list(s2.legs),
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    matches = result["matches"]
    assert len(matches) == 1
    match = matches[0]
    assert match["confluence"] is True
    assert set(match["legs"].keys()) == {"4h", "1h"}
    assert set(match["legs"]["4h"]["signal_tags"]) == {"trend_up", "macd_bullish"}
    assert "pullback" in match["legs"]["1h"]["signal_tags"]


def test_s2_end_to_end_hot_1h_rsi_fails_leg_two(monkeypatch) -> None:
    series_4h = _series(_S2_4H_PASS_CLOSES, symbol="BTC/USD", timeframe="4h")
    series_1h = _series(_RSI_HOT_CLOSES, symbol="BTC/USD", timeframe="1h")
    _install_bars_by_key(
        monkeypatch, {("BTC/USD", "4h"): series_4h, ("BTC/USD", "1h"): series_1h}
    )
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 27, tzinfo=UTC))

    s2 = STRATEGY_BY_KEY["s2_pullback"]
    result = scan_confluence(
        asset_class="crypto",
        legs=list(s2.legs),
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    assert result["matches"] == []
    assert "BTC/USD: leg 1h failed (0/1 tags)" in result["warnings"]


# ---------------------------------------------------------------------------
# 7. Regression: registering S2 must not break the registry's own
#    duplicate-key discipline (light contract check -- the full S1
#    regression surface is `tests/unit/mae/test_strategies_registry.py`
#    and `test_scan_confluence_verb.py`, both left untouched by this batch
#    and run as part of the full suite per the dispatch's self-verify step).
# ---------------------------------------------------------------------------


def test_build_registry_still_succeeds_with_s1_and_s2_present() -> None:
    registry = build_registry(STRATEGIES)
    # Superset pin (CTO adjudication at S4 registration) — see the
    # prefix-pin note above.
    assert {"s1_momentum", "s2_pullback"} <= set(registry.keys())
