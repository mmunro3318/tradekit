"""tests for `tradekit.mae.scan_confluence` — the multi-timeframe confluence
verb (T-MTF-2, docs/design/MTF-SCAN.md "New verb (one, deep)" section).

RED stage: `scan_confluence` does not exist anywhere yet (not even a stub) —
`from tradekit.mae import scan_confluence` fails at COLLECTION with
ImportError. That is the expected red state for this whole file (per the
T-MTF-2 dispatch: "ImportError/AttributeError acceptable at module level").

Seams (same house style as `test_scan_markets_verb.py`, which this file
mirrors): bars faked by monkeypatching
`"tradekit.mae._runtime.get_closed_bars"` by dotted STRING path; regime
faked by monkeypatching the `_regime` module's `compute_regime` attribute
(`monkeypatch.setattr(_regime, "compute_regime", ...)`) since the pinned
contract requires the scanner to call it via module attribute so tests can
intercept it; clock faked via `"tradekit.mae._runtime._clock"`. No new
seams — MTF-SCAN.md's determinism pin forbids inventing one.

Every test below imports the PUBLIC verb `tradekit.mae.scan_confluence`
(not a private `_scanner` helper) because MTF-SCAN.md pins this as a NEW
public verb from day one (unlike `scan_markets`'s historical
stub-then-fill batch split) — there is no test-path exception precedent to
invoke here since nothing about scan_confluence is stubbed first.

Tests never assert on `_evaluate_symbol_timeframe` or any other private
helper — its REUSE is an implementer constraint verified in review, not by
these tests (dispatch pin).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from tradekit.contracts import AssetRef, Bar, BarSeries
from tradekit.mae import _regime, scan_confluence
from tradekit.mae._data.errors import ProviderRequestError
from tradekit.mae._data.limits import TIMEFRAME_MAX_LOOKBACK_DAYS


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
    timeframe: str = "1h",
) -> BarSeries:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    vols = volumes if volumes is not None else [100.0] * len(closes)
    pairs = list(zip(closes, vols, strict=True))
    bars = [_bar(start + timedelta(hours=i), c, v) for i, (c, v) in enumerate(pairs)]
    asset = AssetRef(symbol=symbol, venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))
    return BarSeries(asset=asset, timeframe=timeframe, bars=bars, source="fake-kraken")


def _install_fixed_clock(monkeypatch, now: datetime) -> None:
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: now)


def _neutral_regime(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """A no-op regime: empty `recommended_strategies` families never match,
    so `_apply_regime_gate` (per `_scanner.py`) drops every family-mapped
    tag. Used wherever a test wants regime pruning to have zero effect on
    tags that carry no strategy family (e.g. `bb_inside`)."""
    return {"current_state": "neutral", "confidence": None, "recommended_strategies": []}


def _permissive_regime(**_: Any) -> dict[str, Any]:
    """Recommends every family the scanner's `_TAG_STRATEGY` mapping uses
    (momentum, breakout, mean_reversion) — nothing gets pruned."""
    return {
        "current_state": "low_vol_trend",
        "confidence": 0.9,
        "recommended_strategies": ["momentum", "breakout", "mean_reversion"],
    }


# Falling-closes fixture: RSI(14) pins to 0.0 by construction (pure-loss
# run, same derivation as test_scan_markets_verb.py's _RSI_OVERSOLD_CLOSES)
# -> "oversold" tag fires for any rsi_max >= 0.0.
_RSI_OVERSOLD_CLOSES = [120.0 - i for i in range(20)]

# Rising-closes fixture: RSI(14) pins to 100.0 (pure-gain run) -> fails any
# rsi_max filter outright (last_rsi > rsi_max), so _evaluate_symbol_timeframe
# returns match=None for this leg (killed_by="rsi", 0 signal_tags survive).
_RSI_HOT_CLOSES = [100.0 + i for i in range(20)]

# Volume-spike fixture (unchanged derivation from test_scan_markets_verb.py):
# volume_ratio(20)[-1] == 1000.0/145.0 == 6.896551724137931 >= any
# volume_spike threshold <= 6.0 used below.
_VOLUME_SPIKE_VOLUMES = [100.0] * 24 + [1000.0]
_VOLUME_SPIKE_CLOSES = [100.0] * 25

# Small-seeded-noise fixture (identical seed/derivation to
# test_scan_markets_verb.py's _BB_INSIDE_CLOSES): bollinger(20, 2.0) at the
# last bar keeps the close strictly between the bands -> "inside" ->
# "bb_inside" tag (no strategy-family affiliation, always survives regime
# pruning). RSI(14) on this near-flat noisy series sits near 50, comfortably
# under any rsi_max >= 90 used below, so an "oversold" tag also fires.
random.seed(20260717)
_BB_INSIDE_CLOSES = [100.0 + random.uniform(-0.5, 0.5) for _ in range(25)]

# Too-short series: below RSI(14)'s 15-bar minimum -> _InsufficientBars.
_SHORT_CLOSES = [100.0, 101.0, 99.0, 102.0, 98.0]


def _install_bars_by_key(
    monkeypatch, series_by_key: dict[tuple[str, str], BarSeries]
) -> list[tuple[str, str, int]]:
    """Fakes `_runtime.get_closed_bars`, dispatching on `(symbol,
    timeframe)`, and records every `(symbol, timeframe, lookback_days)`
    call — the SEAM test below reads this list to pin per-leg lookback."""
    calls: list[tuple[str, str, int]] = []

    def _fake_get_closed_bars(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
        calls.append((symbol, timeframe, lookback_days))
        return series_by_key[(symbol, timeframe)]

    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_get_closed_bars)
    return calls


# ---------------------------------------------------------------------------
# 1. Two-leg AND: both legs pass -> match with per-timeframe legs breakdown.
#    BEHAVIOR (MTF-SCAN.md "New verb" semantics pin #1/#3).
# ---------------------------------------------------------------------------


def test_two_leg_and_symbol_passing_both_legs_appears_in_matches(monkeypatch) -> None:
    series_1h = _series(_RSI_OVERSOLD_CLOSES, symbol="BTC/USD", timeframe="1h")
    series_4h = _series(
        _VOLUME_SPIKE_CLOSES, _VOLUME_SPIKE_VOLUMES, symbol="BTC/USD", timeframe="4h"
    )
    _install_bars_by_key(monkeypatch, {("BTC/USD", "1h"): series_1h, ("BTC/USD", "4h"): series_4h})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    result = scan_confluence(
        asset_class="crypto",
        legs=[
            {"timeframe": "1h", "filters": {"rsi_max": 35}, "min_tags": 1},
            {"timeframe": "4h", "filters": {"volume_spike": 2.0}, "min_tags": 1},
        ],
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    matches = result["matches"]
    assert len(matches) == 1
    match = matches[0]
    assert match["symbol"] == "BTC/USD"
    assert match["confluence"] is True
    assert set(match["legs"].keys()) == {"1h", "4h"}
    assert "oversold" in match["legs"]["1h"]["signal_tags"]
    assert "volume_spike" in match["legs"]["4h"]["signal_tags"]
    assert isinstance(match["legs"]["1h"]["indicators"], dict)
    assert isinstance(match["legs"]["4h"]["indicators"], dict)


# ---------------------------------------------------------------------------
# 2. Two-leg AND: one leg fails outright -> symbol absent from matches AND a
#    warning in the EXACT pinned format
#    "<symbol>: leg <tf> failed (<n>/<min> tags)". BEHAVIOR.
#    ASSUMPTION-FLAG 1 (see tests/ASSUMPTIONS.md): MTF-SCAN.md's warning pin
#    reads as being about min_tags-after-regime-pruning specifically, but
#    never separately addresses a leg whose underlying filter check fails
#    outright (0 tags survive, same shape as a pruned-below-min leg). Best
#    reading here: an outright filter failure is n=0 tags survived, same
#    warning shape — CTO ratification needed if a different (e.g. distinct
#    wording for "filter failed" vs "pruned below min") taxonomy is wanted.
# ---------------------------------------------------------------------------


def test_two_leg_and_symbol_failing_one_leg_absent_with_pinned_warning_format(monkeypatch) -> None:
    series_1h = _series(_RSI_OVERSOLD_CLOSES, symbol="BTC/USD", timeframe="1h")
    series_4h = _series(_RSI_HOT_CLOSES, symbol="BTC/USD", timeframe="4h")
    _install_bars_by_key(monkeypatch, {("BTC/USD", "1h"): series_1h, ("BTC/USD", "4h"): series_4h})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    result = scan_confluence(
        asset_class="crypto",
        legs=[
            {"timeframe": "1h", "filters": {"rsi_max": 35}, "min_tags": 1},
            {"timeframe": "4h", "filters": {"rsi_max": 35}, "min_tags": 1},
        ],
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    assert result["matches"] == []
    assert "BTC/USD: leg 4h failed (0/1 tags)" in result["warnings"]


# ---------------------------------------------------------------------------
# 3. min_tags-after-pruning: raw tags meet min_tags, regime-pruned tags fall
#    below -> leg fails. BEHAVIOR (MTF-SCAN.md "Regime gate runs ONCE per
#    symbol ... min_tags is checked AFTER pruning").
# ---------------------------------------------------------------------------


def test_min_tags_checked_after_regime_pruning_leg_fails(monkeypatch) -> None:
    # rsi_max=99 always passes on this near-flat noisy series -> "oversold"
    # (family mean_reversion). bb_position="inside" always passes on the
    # same series -> "bb_inside" (no family, survives any prune). Raw tags
    # = ["oversold", "bb_inside"] = 2, meets min_tags=2 BEFORE pruning.
    series = _series(_BB_INSIDE_CLOSES, symbol="BTC/USD", timeframe="1h")
    _install_bars_by_key(monkeypatch, {("BTC/USD", "1h"): series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))
    monkeypatch.setattr(_regime, "compute_regime", _neutral_regime)

    result = scan_confluence(
        asset_class="crypto",
        legs=[
            {
                "timeframe": "1h",
                "filters": {"rsi_max": 99, "bb_position": "inside"},
                "min_tags": 2,
            }
        ],
        symbols=["BTC/USD"],
        regime_gate=True,
    )

    # _neutral_regime's empty recommended_strategies drops "oversold"
    # (mean_reversion family) but "bb_inside" (no family) survives -> 1
    # post-prune tag, below min_tags=2 -> leg fails -> symbol absent.
    assert result["matches"] == []
    assert "BTC/USD: leg 1h failed (1/2 tags)" in result["warnings"]


# ---------------------------------------------------------------------------
# 4. regime_gate=False -> no pruning applied, even where regime_gate=True
#    would have pruned the same raw tags below min_tags. BEHAVIOR.
# ---------------------------------------------------------------------------


def test_regime_gate_false_applies_no_pruning(monkeypatch) -> None:
    series = _series(_BB_INSIDE_CLOSES, symbol="BTC/USD", timeframe="1h")
    _install_bars_by_key(monkeypatch, {("BTC/USD", "1h"): series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    calls: list[Any] = []
    monkeypatch.setattr(
        _regime, "compute_regime", lambda *a, **k: calls.append((a, k)) or _neutral_regime()
    )

    result = scan_confluence(
        asset_class="crypto",
        legs=[
            {
                "timeframe": "1h",
                "filters": {"rsi_max": 99, "bb_position": "inside"},
                "min_tags": 2,
            }
        ],
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    assert calls == []
    matches = result["matches"]
    assert len(matches) == 1
    assert set(matches[0]["legs"]["1h"]["signal_tags"]) == {"oversold", "bb_inside"}


# ---------------------------------------------------------------------------
# 5. Insufficient bars on ONE leg's timeframe -> symbol dropped entirely
#    (not partially matched) + warning using the existing insufficient-bars
#    convention (`_InsufficientBars`'s message, per `_evaluate_symbol_
#    timeframe` reuse). BEHAVIOR.
# ---------------------------------------------------------------------------


def test_insufficient_bars_on_one_leg_drops_symbol_entirely(monkeypatch) -> None:
    good_1h = _series(_RSI_OVERSOLD_CLOSES, symbol="BTC/USD", timeframe="1h")
    short_4h = _series(_SHORT_CLOSES, symbol="BTC/USD", timeframe="4h")
    _install_bars_by_key(monkeypatch, {("BTC/USD", "1h"): good_1h, ("BTC/USD", "4h"): short_4h})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    result = scan_confluence(
        asset_class="crypto",
        legs=[
            {"timeframe": "1h", "filters": {"rsi_max": 35}, "min_tags": 1},
            {"timeframe": "4h", "filters": {"rsi_max": 35}, "min_tags": 1},
        ],
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    assert result["matches"] == []
    assert any(
        "BTC/USD 4h: insufficient bars for rsi_max" in w for w in result["warnings"]
    ), f"expected the existing insufficient-bars message, got {result['warnings']!r}"


# ---------------------------------------------------------------------------
# 6. Regime evaluated ONCE per symbol even across multiple legs. BEHAVIOR
#    (same "150 HMM loads" trap as scan()'s own cache pin, applied here).
# ---------------------------------------------------------------------------


def test_regime_evaluated_once_per_symbol_across_legs(monkeypatch) -> None:
    series_1h = _series(_RSI_OVERSOLD_CLOSES, symbol="BTC/USD", timeframe="1h")
    series_4h = _series(_RSI_OVERSOLD_CLOSES, symbol="BTC/USD", timeframe="4h")
    _install_bars_by_key(monkeypatch, {("BTC/USD", "1h"): series_1h, ("BTC/USD", "4h"): series_4h})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    calls: list[str] = []

    def _fake_compute_regime(symbol: str, lookback_days: int, n_states: int) -> dict[str, Any]:
        calls.append(symbol)
        return _permissive_regime()

    monkeypatch.setattr(_regime, "compute_regime", _fake_compute_regime)

    scan_confluence(
        asset_class="crypto",
        legs=[
            {"timeframe": "1h", "filters": {"rsi_max": 35}, "min_tags": 1},
            {"timeframe": "4h", "filters": {"rsi_max": 35}, "min_tags": 1},
        ],
        symbols=["BTC/USD"],
        regime_gate=True,
    )

    assert calls == ["BTC/USD"], f"expected exactly 1 compute_regime call, got {calls!r}"


# ---------------------------------------------------------------------------
# 7. Unknown filter value (closed vocabulary, TICKET-001 doctrine, same as
#    scan_markets) -> loud ValueError BEFORE any bar fetch. CONTRACT.
# ---------------------------------------------------------------------------


def test_unknown_filter_value_raises_before_any_bar_fetch(monkeypatch) -> None:
    calls = _install_bars_by_key(monkeypatch, {})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    with pytest.raises(ValueError, match="macd_signal"):
        scan_confluence(
            asset_class="crypto",
            legs=[
                {"timeframe": "1h", "filters": {"macd_signal": "sideways"}, "min_tags": 1},
            ],
            symbols=["BTC/USD"],
            regime_gate=False,
        )

    assert calls == [], "unknown filter value must be validated before any bar fetch"


# ---------------------------------------------------------------------------
# 8. Determinism/shape: empty symbol list -> matches=[] with no error, never
#    an exception. CONTRACT.
# ---------------------------------------------------------------------------


def test_empty_symbols_returns_empty_matches_never_an_error(monkeypatch) -> None:
    _install_bars_by_key(monkeypatch, {})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    result = scan_confluence(
        asset_class="crypto",
        legs=[{"timeframe": "1h", "filters": {"rsi_max": 35}, "min_tags": 1}],
        symbols=[],
        regime_gate=False,
    )

    assert result["matches"] == []
    assert result["warnings"] == []


# ---------------------------------------------------------------------------
# 9. Determinism: scan_ts comes from the clock seam, not wall time. CONTRACT.
# ---------------------------------------------------------------------------


def test_scan_ts_comes_from_clock_seam(monkeypatch) -> None:
    _install_bars_by_key(monkeypatch, {})
    fixed_now = datetime(2026, 7, 16, 12, 30, tzinfo=UTC)
    _install_fixed_clock(monkeypatch, fixed_now)

    result = scan_confluence(
        asset_class="crypto",
        legs=[{"timeframe": "1h", "filters": {"rsi_max": 35}, "min_tags": 1}],
        symbols=[],
        regime_gate=False,
    )

    assert result["scan_ts"] == fixed_now.isoformat()


# ---------------------------------------------------------------------------
# 10. ScanLeg with an unknown timeframe key (not in
#     TIMEFRAME_MAX_LOOKBACK_DAYS) -> loud ValueError, never a silent skip
#     (MTF-SCAN.md's Error map: "leg timeframe not in
#     TIMEFRAME_MAX_LOOKBACK_DAYS -> ValueError at scan_confluence entry
#     (caller bug, loud)" — pinned verbatim, not an ASSUMPTION). CONTRACT.
# ---------------------------------------------------------------------------


def test_unknown_leg_timeframe_raises_value_error_before_fetch(monkeypatch) -> None:
    assert "3m" not in TIMEFRAME_MAX_LOOKBACK_DAYS, "fixture must use a genuinely unknown timeframe"
    calls = _install_bars_by_key(monkeypatch, {})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    with pytest.raises(ValueError, match="3m"):
        scan_confluence(
            asset_class="crypto",
            legs=[{"timeframe": "3m", "filters": {}, "min_tags": 0}],
            symbols=["BTC/USD"],
            regime_gate=False,
        )

    assert calls == [], "unknown leg timeframe must be validated before any bar fetch"


# ---------------------------------------------------------------------------
# SEAM: per-leg lookback passed to get_closed_bars equals
# TIMEFRAME_MAX_LOOKBACK_DAYS[leg.timeframe] — the retention-honesty pin
# (MTF-SCAN.md "Test seams / plan" section).
# ---------------------------------------------------------------------------


def test_per_leg_lookback_matches_pinned_retention_table(monkeypatch) -> None:
    series_1h = _series(_RSI_OVERSOLD_CLOSES, symbol="BTC/USD", timeframe="1h")
    series_4h = _series(_RSI_OVERSOLD_CLOSES, symbol="BTC/USD", timeframe="4h")
    calls = _install_bars_by_key(
        monkeypatch, {("BTC/USD", "1h"): series_1h, ("BTC/USD", "4h"): series_4h}
    )
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    scan_confluence(
        asset_class="crypto",
        legs=[
            {"timeframe": "1h", "filters": {"rsi_max": 35}, "min_tags": 1},
            {"timeframe": "4h", "filters": {"rsi_max": 35}, "min_tags": 1},
        ],
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    lookback_by_tf = {tf: lookback for (_symbol, tf, lookback) in calls}
    assert lookback_by_tf["1h"] == TIMEFRAME_MAX_LOOKBACK_DAYS["1h"]
    assert lookback_by_tf["4h"] == TIMEFRAME_MAX_LOOKBACK_DAYS["4h"]


# ---------------------------------------------------------------------------
# 12. Provider error on one symbol's leg -> that symbol dropped with a
#     warning, never an exception out of the verb; another symbol passing
#     every leg is unaffected. BEHAVIOR (MTF-SCAN.md error map: "provider
#     error on any leg -> symbol dropped + warning (never an exception out
#     of the verb)").
# ---------------------------------------------------------------------------


def test_provider_error_on_one_leg_drops_only_that_symbol(monkeypatch) -> None:
    good_1h_a = _series(_RSI_OVERSOLD_CLOSES, symbol="BTC/USD", timeframe="1h")
    good_4h_a = _series(_RSI_OVERSOLD_CLOSES, symbol="BTC/USD", timeframe="4h")
    good_1h_b = _series(_RSI_OVERSOLD_CLOSES, symbol="ETH/USD", timeframe="1h")
    series_by_key = {
        ("BTC/USD", "1h"): good_1h_a,
        ("BTC/USD", "4h"): good_4h_a,
        ("ETH/USD", "1h"): good_1h_b,
    }

    def _fake_get_closed_bars(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
        if symbol == "ETH/USD" and timeframe == "4h":
            raise ProviderRequestError("boom")
        return series_by_key[(symbol, timeframe)]

    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_get_closed_bars)
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    result = scan_confluence(
        asset_class="crypto",
        legs=[
            {"timeframe": "1h", "filters": {"rsi_max": 35}, "min_tags": 1},
            {"timeframe": "4h", "filters": {"rsi_max": 35}, "min_tags": 1},
        ],
        symbols=["BTC/USD", "ETH/USD"],
        regime_gate=False,
    )

    matches = result["matches"]
    assert len(matches) == 1
    assert matches[0]["symbol"] == "BTC/USD"
    assert "ETH/USD: provider error on leg 4h (ProviderRequestError)" in result["warnings"]


# ---------------------------------------------------------------------------
# 13. Two legs sharing a timeframe -> loud ValueError naming the duplicated
#     timeframe, before any fetch (the return shape keys legs by timeframe,
#     duplicates are unrepresentable). CONTRACT.
# ---------------------------------------------------------------------------


def test_duplicate_leg_timeframes_raises_value_error_before_fetch(monkeypatch) -> None:
    calls = _install_bars_by_key(monkeypatch, {})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    with pytest.raises(ValueError, match="1h"):
        scan_confluence(
            asset_class="crypto",
            legs=[
                {"timeframe": "1h", "filters": {"rsi_max": 35}, "min_tags": 1},
                {"timeframe": "1h", "filters": {"volume_spike": 2.0}, "min_tags": 1},
            ],
            symbols=["BTC/USD"],
            regime_gate=False,
        )

    assert calls == [], "duplicate leg timeframe must be validated before any bar fetch"
