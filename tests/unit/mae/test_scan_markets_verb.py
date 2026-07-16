"""tests for `tradekit.mae._scanner.scan` — the full `scan_markets`
ORCHESTRATION (SPRINT-P1C batch C, story 4).

Why this file targets `_scanner.scan` and not `tradekit.mae.scan_markets`:
same rationale as batch B's `test_get_regime_verb.py` targeting
`_regime.compute_regime` (ASSUMPTIONS 48) — `tradekit.mae.scan_markets`
stays an unconditional `NotImplementedError` stub in `mae/__init__.py` THIS
batch (red-only; the dev pass wires the body to
`return _scanner.scan(asset_class, timeframes, filters, symbols,
regime_gate)`). `_scanner` has no dedicated public verb of its own yet, so
this file imports it directly — TEST-PATH EXCEPTION extending ASSUMPTIONS
44/48 (see `tests/ASSUMPTIONS.md`'s new P1C batch C entry).

Runtime bars are faked by monkeypatching
`"tradekit.mae._runtime.get_closed_bars"` by dotted STRING path (no import
statement, no exception needed — same house style as
`test_size_position_verb.py`/`test_get_regime_verb.py`). Regime is faked by
monkeypatching `"tradekit.mae._regime.compute_regime"` by dotted string
path, per the CTO pin that the scanner calls `_regime.compute_regime` via
module attribute specifically so this is possible. Clock is faked via
`"tradekit.mae._runtime._clock"`.

Status: `_scanner.scan` is a P1C batch C STUB — the `symbols is None`
universe-deferral check is REAL (implemented) validation, everything else
raises `NotImplementedError` unconditionally. Consequently:
  - `test_symbols_none_raises_value_error_naming_deferral` is GREEN already
    (pure input validation, no pipeline dependency) — see the module
    docstring's "account for new-but-green tests" instruction in the
    dispatch. Every other test below is RED with NotImplementedError, the
    expected red state for this batch.

=== Fixture-freeze provenance (derivation executed directly against
`tradekit.mae._indicators` in the session scratchpad, values cited below —
NOT from `_scanner` itself, which is a stub) ===

RSI-oversold fixture (20 daily closes, steadily falling 120.0 -> 101.0 by
1.0/day — pure-loss run, no gains at all):
    momentum.rsi(closes, period=14)[-1] == 0.0
    (every diff after the warmup is a loss, so avg_gain stays 0.0 and RSI
    pins to the avoid-division-by-zero convention `100.0 - 100.0/(1+RS)`
    with RS=0 -> RSI=0.0; the rsi() docstring's OTHER zero-guard, avg_loss==0
    -> RSI=100.0, does not apply here since this run is all losses, not all
    gains)
Reproduces exactly by construction (`[120.0 - i for i in range(20)]`) — no
external cross-check needed, the run is monotonic by design.

Volume-spike fixture (25 bars, volume=100.0 for the first 24, last bar
volume=1000.0 -- a 10x jump):
    volume.volume_ratio(volumes, period=20)[-1] == 1000.0 / 145.0
        = 6.896551724137931
    (SMA(20) of the trailing 20 volumes ending at the last bar: 19 bars of
    100.0 plus the spike bar's own 1000.0 -- wait, the SMA window is the
    TRAILING 20 volumes INCLUDING the current bar, i.e. indices 5..24 =
    19*100.0 + 1000.0 = 2900.0, /20 = 145.0; ratio = 1000.0/145.0 =
    6.896551724137931.)

BB-below-lower fixture (24 bars of `100.0 + random.uniform(-0.5, 0.5)` with
`random.seed(20260716)`, then a 25th bar dropping to close=80.0):
    volatility.bollinger(closes, period=20, k=2.0) at index 24:
        mid    = 99.00239611121395
        upper  = 107.73674474526149
        lower  = 90.26804747716642
    last close (80.0) < lower (90.26804747716642) -> "below_lower" filter
    hit. (`derive_p1c_batchC.py`, session scratchpad, never committed —
    values reproduced via `tradekit.mae._indicators.volatility.bollinger`
    directly at derivation time, same discipline as ASSUMPTIONS 42.)
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradekit.contracts import AssetRef, Bar, BarSeries
from tradekit.mae import _regime, _scanner


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
    closes: list[float], volumes: list[float] | None = None, *, symbol: str = "BTC/USD"
) -> BarSeries:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    vols = volumes if volumes is not None else [100.0] * len(closes)
    pairs = list(zip(closes, vols, strict=True))
    bars = [_bar(start + timedelta(days=i), c, v) for i, (c, v) in enumerate(pairs)]
    asset = AssetRef(symbol=symbol, venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))
    return BarSeries(asset=asset, timeframe="1d", bars=bars, source="fake-kraken")


# Oversold-RSI fixture: see module docstring derivation. last RSI(14) = 0.0.
_RSI_OVERSOLD_CLOSES = [120.0 - i for i in range(20)]

# Volume-spike fixture: see module docstring derivation. last volume_ratio
# = 6.896551724137931.
_VOLUME_SPIKE_VOLUMES = [100.0] * 24 + [1000.0]
_VOLUME_SPIKE_CLOSES = [100.0] * 25  # flat price, volume carries the signal

# BB below_lower fixture: see module docstring derivation.
random.seed(20260716)
_BB_BELOW_LOWER_CLOSES = [100.0 + random.uniform(-0.5, 0.5) for _ in range(24)] + [80.0]

# MEDIUM-1 review-fix fixtures (session-derived directly against
# `tradekit.mae._indicators`, same discipline as the fixtures above).

# rsi_min-overbought fixture: 20 daily closes, steadily RISING 100.0/day
# (pure-gain run, mirror image of the RSI-oversold fixture) ->
# momentum.rsi(closes, period=14)[-1] == 100.0 (avg_loss stays 0.0, the
# rsi() docstring's avg_loss==0 zero-guard -> RSI=100.0).
_RSI_OVERBOUGHT_CLOSES = [100.0 + i for i in range(20)]

# macd_signal fixtures: flat base then an accelerating move (a straight
# linear ramp settles the MACD histogram back toward 0 in steady state — an
# ACCELERATING move is needed to pin a nonzero-sign last histogram).
# Derived directly against `_indicators.momentum.macd`:
#   bullish: [100.0]*40 + [100.0 + i**1.3 for i in 1..20]
#     -> macd(closes).histogram[-1] == 2.632866287861548  (> 0)
#   bearish: [100.0]*40 + [100.0 - i**1.3 for i in 1..20]
#     -> macd(closes).histogram[-1] == -2.6328662878615496  (< 0)
_MACD_BULLISH_CLOSES = [100.0] * 40 + [100.0 + i**1.3 for i in range(1, 21)]
_MACD_BEARISH_CLOSES = [100.0] * 40 + [100.0 - i**1.3 for i in range(1, 21)]

# atr_percentile_min fixture: 40 bars with a MONOTONICALLY EXPANDING
# high-low range (rng = 0.5 + i*0.3) around a slowly-rising close, so the
# LAST bar's ATR(14) is also the window's own maximum. Derived directly
# against `_indicators.volatility.atr`:
#   highs[i] = price + rng/2, lows[i] = price - rng/2, price += 0.1 each bar
#   -> atr(highs, lows, closes, 14) has 27 non-None values (40 - 14 + 1),
#      last ATR == 8.58394409652438, and since ranges expand monotonically
#      the last ATR is the max of the window -> every other value is <=
#      it, so the <=-rank percentile is 27/27 * 100.0 == 100.0.
_ATR_EXPANDING_N = 40


def _atr_expanding_fixture() -> tuple[list[float], list[float], list[float]]:
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    price = 100.0
    for i in range(_ATR_EXPANDING_N):
        rng = 0.5 + i * 0.3
        highs.append(price + rng / 2)
        lows.append(price - rng / 2)
        closes.append(price)
        price += 0.1
    return highs, lows, closes


# bb_position above_upper fixture: same 24-bar seeded base as the
# below_lower fixture, but the 25th bar SPIKES UP to 130.0 instead of down.
# Derived directly against `_indicators.volatility.bollinger`:
#   upper = 114.58830165255151, lower = 88.4164905698764, close = 130.0
#   -> 130.0 > upper -> "above_upper".
random.seed(20260716)
_BB_ABOVE_UPPER_CLOSES = [100.0 + random.uniform(-0.5, 0.5) for _ in range(24)] + [130.0]

# bb_position inside fixture: 25 bars of small seeded noise, no spike at
# all. Derived directly against `_indicators.volatility.bollinger`:
#   upper = 100.66558544841018, lower = 99.44639883535416,
#   close = 100.4748162133211 -> strictly between the bands -> "inside".
random.seed(20260717)
_BB_INSIDE_CLOSES = [100.0 + random.uniform(-0.5, 0.5) for _ in range(25)]


def _install_bars_by_symbol(
    monkeypatch, series_by_symbol: dict[str, BarSeries]
) -> list[tuple[str, str, int]]:
    """Fakes `_runtime.get_closed_bars`, dispatching on `symbol`, and
    records every `(symbol, timeframe, lookback_days)` call."""
    calls: list[tuple[str, str, int]] = []

    def _fake_get_closed_bars(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
        calls.append((symbol, timeframe, lookback_days))
        return series_by_symbol[symbol]

    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_get_closed_bars)
    return calls


def _install_fixed_clock(monkeypatch, now: datetime) -> None:
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: now)


# ---------------------------------------------------------------------------
# symbols=None: the ONE real (non-stub) code path this batch — GREEN already.
# ---------------------------------------------------------------------------


def test_symbols_none_raises_value_error_naming_deferral() -> None:
    with pytest.raises(ValueError, match="full universe"):
        _scanner.scan(
            asset_class="crypto",
            timeframes=["1d"],
            filters={},
            symbols=None,
            regime_gate=False,
        )


# ---------------------------------------------------------------------------
# Everything below exercises the real pipeline -> RED this batch
# (NotImplementedError), the expected state. Assertions describe the REAL
# behavior the dev pass implements next, per the module docstring's pins.
# ---------------------------------------------------------------------------


def test_oversold_rsi_symbol_appears_in_matches(monkeypatch, tmp_path) -> None:
    series = _series(_RSI_OVERSOLD_CLOSES)
    _install_bars_by_symbol(monkeypatch, {"BTC/USD": series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    result = _scanner.scan(
        asset_class="crypto",
        timeframes=["1d"],
        filters={"rsi_max": 35},
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    matches = result["matches"]
    assert len(matches) == 1
    match = matches[0]
    assert match["symbol"] == "BTC/USD"
    assert match["timeframe"] == "1d"
    assert match["rsi"] == pytest.approx(0.0)
    assert "oversold" in match["signal_tags"]


def test_volume_spike_symbol_appears_in_matches(monkeypatch) -> None:
    series = _series(_VOLUME_SPIKE_CLOSES, _VOLUME_SPIKE_VOLUMES)
    _install_bars_by_symbol(monkeypatch, {"BTC/USD": series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    result = _scanner.scan(
        asset_class="crypto",
        timeframes=["1d"],
        filters={"volume_spike": 2.0},
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    matches = result["matches"]
    assert len(matches) == 1
    assert matches[0]["volume_ratio"] == pytest.approx(6.896551724137931)
    assert "volume_spike" in matches[0]["signal_tags"]


def test_bb_below_lower_symbol_appears_in_matches(monkeypatch) -> None:
    series = _series(_BB_BELOW_LOWER_CLOSES)
    _install_bars_by_symbol(monkeypatch, {"BTC/USD": series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    result = _scanner.scan(
        asset_class="crypto",
        timeframes=["1d"],
        filters={"bb_position": "below_lower"},
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    matches = result["matches"]
    assert len(matches) == 1
    assert "at_support" in matches[0]["signal_tags"]


def test_filter_and_composition_excludes_symbol_failing_one_filter(monkeypatch) -> None:
    """The RSI-oversold fixture's volumes are flat (no spike) — a symbol
    passing rsi_max but failing volume_spike must be excluded entirely
    (AND-composition, not OR)."""
    series = _series(_RSI_OVERSOLD_CLOSES)  # flat volume=100.0 throughout
    _install_bars_by_symbol(monkeypatch, {"BTC/USD": series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    result = _scanner.scan(
        asset_class="crypto",
        timeframes=["1d"],
        filters={"rsi_max": 35, "volume_spike": 2.0},
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    assert result["matches"] == []


def test_multi_symbol_scan_returns_per_symbol_results(monkeypatch) -> None:
    series_a = _series(_RSI_OVERSOLD_CLOSES, symbol="AAA/USD")
    series_b = _series(_RSI_OVERSOLD_CLOSES, symbol="BBB/USD")
    _install_bars_by_symbol(monkeypatch, {"AAA/USD": series_a, "BBB/USD": series_b})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    result = _scanner.scan(
        asset_class="crypto",
        timeframes=["1d"],
        filters={"rsi_max": 35},
        symbols=["AAA/USD", "BBB/USD"],
        regime_gate=False,
    )

    matched_symbols = {m["symbol"] for m in result["matches"]}
    assert matched_symbols == {"AAA/USD", "BBB/USD"}


def test_regime_gate_false_makes_zero_regime_calls(monkeypatch) -> None:
    series = _series(_RSI_OVERSOLD_CLOSES)
    _install_bars_by_symbol(monkeypatch, {"BTC/USD": series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    calls: list[tuple[str, int, int]] = []

    def _fake_compute_regime(symbol: str, lookback_days: int, n_states: int) -> dict[str, object]:
        calls.append((symbol, lookback_days, n_states))
        raise AssertionError("regime_gate=False must never call compute_regime")

    monkeypatch.setattr(_regime, "compute_regime", _fake_compute_regime)

    _scanner.scan(
        asset_class="crypto",
        timeframes=["1d"],
        filters={"rsi_max": 35},
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    assert calls == []


def test_regime_call_cached_once_per_symbol_across_timeframes(monkeypatch) -> None:
    """2 symbols x 2 timeframes with regime_gate=True -> exactly 2 recorded
    compute_regime calls (one per symbol, cached across timeframes) — the
    sprint's pinned "150 HMM loads" trap."""
    def _fake_get_closed_bars(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
        base = _series(_RSI_OVERSOLD_CLOSES, symbol=symbol)
        return base

    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_get_closed_bars)
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    calls: list[tuple[str, int, int]] = []

    def _fake_compute_regime(symbol: str, lookback_days: int, n_states: int) -> dict[str, object]:
        calls.append((symbol, lookback_days, n_states))
        return {
            "current_state": "low_vol_trend",
            "confidence": 0.9,
            "recommended_strategies": ["momentum", "breakout", "mean_reversion"],
        }

    monkeypatch.setattr(_regime, "compute_regime", _fake_compute_regime)

    _scanner.scan(
        asset_class="crypto",
        timeframes=["1d", "4h"],
        filters={"rsi_max": 35},
        symbols=["AAA/USD", "BBB/USD"],
        regime_gate=True,
    )

    called_symbols = [c[0] for c in calls]
    assert sorted(called_symbols) == ["AAA/USD", "BBB/USD"]
    assert len(calls) == 2, f"expected exactly 2 compute_regime calls, got {len(calls)}: {calls!r}"


def test_neutral_regime_drops_all_strategy_tagged_signals(monkeypatch) -> None:
    """ASSUMPTIONS 53: state 'neutral' / empty recommended_strategies is
    no-recommendation -> the gate drops every strategy-tagged signal_tag
    for that symbol (here, 'oversold' -> mean_reversion, dropped since
    mean_reversion not in an empty recommended_strategies)."""
    series = _series(_RSI_OVERSOLD_CLOSES)
    _install_bars_by_symbol(monkeypatch, {"BTC/USD": series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    def _fake_compute_regime(symbol: str, lookback_days: int, n_states: int) -> dict[str, object]:
        return {"current_state": "neutral", "confidence": None, "recommended_strategies": []}

    monkeypatch.setattr(_regime, "compute_regime", _fake_compute_regime)

    result = _scanner.scan(
        asset_class="crypto",
        timeframes=["1d"],
        filters={"rsi_max": 35},
        symbols=["BTC/USD"],
        regime_gate=True,
    )

    matches = result["matches"]
    assert len(matches) == 1
    assert matches[0]["signal_tags"] == []


def test_insufficient_bars_symbol_skipped_with_warning(monkeypatch) -> None:
    """5 daily bars is far short of RSI(14)'s 15-bar minimum — the symbol
    must be SKIPPED (not crash, not silently pass) and a warnings entry
    names both the symbol and the reason."""
    short_series = _series([100.0, 101.0, 99.0, 102.0, 98.0])
    _install_bars_by_symbol(monkeypatch, {"BTC/USD": short_series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    result = _scanner.scan(
        asset_class="crypto",
        timeframes=["1d"],
        filters={"rsi_max": 35},
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    assert result["matches"] == []
    assert any("BTC/USD" in w for w in result["warnings"]), (
        f"expected a warnings entry naming the symbol, got {result['warnings']!r}"
    )


# ---------------------------------------------------------------------------
# MEDIUM-1 review fixes: pinning tests for the three scanner filter branches
# that had zero coverage (rsi_min, macd_signal, atr_percentile_min) plus the
# uncovered bb_position "above_upper"/"inside" branches. These are PINNING
# tests against a real (non-stub) src — they should PASS as-is; a failure
# here means the src itself has a defect, not the test.
# ---------------------------------------------------------------------------


def test_overbought_rsi_symbol_appears_in_matches(monkeypatch) -> None:
    series = _series(_RSI_OVERBOUGHT_CLOSES)
    _install_bars_by_symbol(monkeypatch, {"BTC/USD": series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    result = _scanner.scan(
        asset_class="crypto",
        timeframes=["1d"],
        filters={"rsi_min": 80},
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    matches = result["matches"]
    assert len(matches) == 1
    assert matches[0]["rsi"] == pytest.approx(100.0)
    assert "overbought" in matches[0]["signal_tags"]


def test_macd_signal_bullish_cross_symbol_appears_in_matches(monkeypatch) -> None:
    series = _series(_MACD_BULLISH_CLOSES)
    _install_bars_by_symbol(monkeypatch, {"BTC/USD": series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    result = _scanner.scan(
        asset_class="crypto",
        timeframes=["1d"],
        filters={"macd_signal": "bullish_cross"},
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    matches = result["matches"]
    assert len(matches) == 1
    assert matches[0]["macd_hist"] == pytest.approx(2.632866287861548)
    assert "macd_bullish" in matches[0]["signal_tags"]


def test_macd_signal_bearish_cross_symbol_appears_in_matches(monkeypatch) -> None:
    series = _series(_MACD_BEARISH_CLOSES)
    _install_bars_by_symbol(monkeypatch, {"BTC/USD": series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    result = _scanner.scan(
        asset_class="crypto",
        timeframes=["1d"],
        filters={"macd_signal": "bearish_cross"},
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    matches = result["matches"]
    assert len(matches) == 1
    assert matches[0]["macd_hist"] == pytest.approx(-2.6328662878615496)
    assert "macd_bearish" in matches[0]["signal_tags"]


def test_macd_signal_unknown_value_matches_nothing(monkeypatch) -> None:
    """`macd_signal` values other than "bullish_cross"/"bearish_cross" must
    hit the unknown-value guard -> no match (not a crash, not a pass)."""
    series = _series(_MACD_BULLISH_CLOSES)
    _install_bars_by_symbol(monkeypatch, {"BTC/USD": series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    result = _scanner.scan(
        asset_class="crypto",
        timeframes=["1d"],
        filters={"macd_signal": "sideways"},
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    assert result["matches"] == []


def test_atr_percentile_min_symbol_appears_in_matches(monkeypatch) -> None:
    highs, lows, closes = _atr_expanding_fixture()
    # The shared `_series` helper always derives high/low as close +/- 0.3,
    # which can't produce an expanding-range fixture, so build bars
    # directly here with the derived expanding highs/lows.
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars = [
        Bar(
            ts_open=start + timedelta(days=i),
            open=Decimal(str(c)),
            high=Decimal(str(h)),
            low=Decimal(str(low_)),
            close=Decimal(str(c)),
            volume=Decimal("100.0"),
        )
        for i, (c, h, low_) in enumerate(zip(closes, highs, lows, strict=True))
    ]
    asset = AssetRef(
        symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01")
    )
    series = BarSeries(asset=asset, timeframe="1d", bars=bars, source="fake-kraken")
    _install_bars_by_symbol(monkeypatch, {"BTC/USD": series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    result = _scanner.scan(
        asset_class="crypto",
        timeframes=["1d"],
        filters={"atr_percentile_min": 90},
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    matches = result["matches"]
    assert len(matches) == 1
    assert matches[0]["atr"] == pytest.approx(8.58394409652438)
    assert "high_volatility" in matches[0]["signal_tags"]


def test_bb_above_upper_symbol_appears_in_matches(monkeypatch) -> None:
    series = _series(_BB_ABOVE_UPPER_CLOSES)
    _install_bars_by_symbol(monkeypatch, {"BTC/USD": series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    result = _scanner.scan(
        asset_class="crypto",
        timeframes=["1d"],
        filters={"bb_position": "above_upper"},
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    matches = result["matches"]
    assert len(matches) == 1
    assert "at_resistance" in matches[0]["signal_tags"]


def test_bb_inside_symbol_appears_in_matches(monkeypatch) -> None:
    series = _series(_BB_INSIDE_CLOSES)
    _install_bars_by_symbol(monkeypatch, {"BTC/USD": series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    result = _scanner.scan(
        asset_class="crypto",
        timeframes=["1d"],
        filters={"bb_position": "inside"},
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    matches = result["matches"]
    assert len(matches) == 1
    assert "bb_inside" in matches[0]["signal_tags"]


def test_symbols_none_message_names_deferral_not_notimplementederror() -> None:
    """Duplicate-intent sanity check: the symbols=None guard must raise
    ValueError specifically, never let NotImplementedError leak through it
    (it is checked BEFORE the stub's unconditional raise)."""
    with pytest.raises(ValueError):
        _scanner.scan(
            asset_class="equity",
            timeframes=["1h", "4h", "1d"],
            filters={"rsi_max": 35},
            symbols=None,
            regime_gate=True,
        )
