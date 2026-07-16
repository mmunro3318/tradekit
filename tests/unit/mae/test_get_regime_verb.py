"""tests for `tradekit.mae._regime.compute_regime` — the full get_regime
ORCHESTRATION (SPRINT-P1C batch B, story 2).

Why this file targets `_regime.compute_regime` and not `tradekit.mae.
get_regime`: unlike batch A's `size_position`/`get_correlation_matrix`
(already wired verbs by the time their "_verb" test files were written),
`get_regime` stays an unconditional `NotImplementedError` stub in
`mae/__init__.py` THIS batch (batch B is red-only — "no implementation").
The dev pass's entire job for the public verb is
`return _regime.compute_regime(symbol, lookback_days, n_states)` — so
`compute_regime` IS the verb body under test here, exercised exactly the
way the sprint doc's batch-A house style prescribes: bars faked via
`monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", ...)` by
dotted STRING path (no import statement, needs no ASSUMPTIONS exception —
same as `test_size_position_verb.py`/`test_correlation_verb.py`), "now" via
`monkeypatch.setattr("tradekit.mae._runtime._clock", ...)`, and the HMM
models directory via `monkeypatch.setattr(_regime, "_models_dir",
tmp_path)` (batch A `_cache_path` lesson, extended to HMM artifacts here —
`_regime` itself IS imported directly, per the TEST-PATH EXCEPTION this
batch adds to ASSUMPTIONS entry 44, same rationale as `test_regime.py`).

Status: `_regime.compute_regime` is a P1C batch B STUB (raises
`NotImplementedError` unconditionally) — every test below currently fails
with `NotImplementedError`, the expected red state for this batch.

=== Fixture-freeze provenance (derive_p1c_batchB.py, session scratchpad,
never committed) ===

Section 1b (EWMA override, 30-point planted-spike series): alpha=2/21,
first 29 returns are `random.seed(99); random.gauss(0.0, 0.004)` noise, the
30th (last) return is a planted spike of 0.25.
    i=0  r=-0.0022008907909624106  ewma_var=4.843920273743146e-06
    i=1  r=0.0015164733079139332   ewma_var=4.60161275182622e-06
    i=2  r=0.0013077091463801784   ewma_var=4.326230890845282e-06
    ...
    i=29 (last) r=0.25             ewma_var=0.005961450135982465
        -> ewma_vol = sqrt(0.005961450135982465) = 0.07721042763760906
This test does NOT hardcode that final ewma_vol into an assertion (per the
addendum: "derive threshold side from the fitted params programmatically in
the test... not hardcoded floats") — it reconstructs the same 30-return
series with the same seed and lets `compute_regime` (once implemented) do
its own EWMA arithmetic; the test only pins the INPUT construction and the
qualitative claim that a 0.25 one-day return trivially blows past any
sane fitted low-vol state's mean+3*std band.

Section 2 (rules-fallback grid, 45-bar fixtures, `_indicators.trend.adx`
used at DERIVATION time only, never inside this test):
  - trend fixture (steady +1.0/day, n=45): ADX(14) last value = 100.0,
    vol_pctile (latest realized-vol's <=-rank among the window) = 0.04
    -> grid picks ADX>=25 branch -> "low_vol_trend".
  - chop fixture (seed=7, small noise then a late 6-bar vol expansion,
    n=45): ADX(14) last value = 36.818569075393775, vol_pctile = 1.0
    -> grid's vol_pctile>0.8 branch wins FIRST (checked before ADX) ->
    "high_vol_chop", even though this fixture's ADX would ALSO clear the
    trend threshold — this is the deliberate priority-ordering trap.
  - neutral fixture (seed=55, flat random walk, n=45): ADX(14) last value
    = 10.271464515727867, vol_pctile = 0.56 -> neither branch fires ->
    `_regime._RULES_NEUTRAL_STATE`.
All three fixtures have only 45 bars (< 60), so `insufficient_history` is
ALSO always present in warnings alongside the grid-selected state.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradekit.contracts import AssetRef, Bar, BarSeries
from tradekit.mae import _regime

_ASSET = AssetRef(symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))


def _bar(ts_open: datetime, close: float) -> Bar:
    return Bar(
        ts_open=ts_open,
        open=Decimal(str(close)),
        high=Decimal(str(close + 0.3)),
        low=Decimal(str(close - 0.3)),
        close=Decimal(str(close)),
        volume=Decimal("1000"),
    )


def _bar_series_from_closes(closes: list[float], *, source: str = "fake-kraken") -> BarSeries:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars = [_bar(start + timedelta(days=i), c) for i, c in enumerate(closes)]
    return BarSeries(asset=_ASSET, timeframe="1d", bars=bars, source=source)


def _closes_from_returns(returns: list[float], start_price: float = 100.0) -> list[float]:
    closes = [start_price]
    for r in returns:
        closes.append(closes[-1] * math.exp(r))
    return closes


def _install_fixed_clock(monkeypatch, now: datetime) -> None:
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: now)


def _install_bars(monkeypatch, series: BarSeries) -> list[tuple[str, int]]:
    """Fakes `_runtime.get_daily_bars`, returning `series` unconditionally,
    and records every `(symbol, lookback_days)` call for the lookahead/
    plumbing assertions."""
    calls: list[tuple[str, int]] = []

    def _fake_get_daily_bars(symbol: str, lookback_days: int) -> BarSeries:
        calls.append((symbol, lookback_days))
        return series

    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", _fake_get_daily_bars)
    return calls


# ---------------------------------------------------------------------------
# Synthetic 2-state series: 60 calm days (sigma~0.005) then 60 wild days
# (sigma~0.04), pinned stdlib seed. Fit at n_states=2 -> wild segment's
# label maps to "high_vol_chop", calm to "low_vol_trend" (labels/transitions
# only, never fitted floats, per the fixture-freeze rule's HMM carve-out).
# ---------------------------------------------------------------------------


def test_two_state_synthetic_series_labels_wild_segment_high_vol_chop(
    monkeypatch, tmp_path
) -> None:
    random.seed(4242)
    calm_returns = [random.gauss(0.0, 0.005) for _ in range(60)]
    wild_returns = [random.gauss(0.0, 0.04) for _ in range(60)]
    closes = _closes_from_returns(calm_returns + wild_returns)
    series = _bar_series_from_closes(closes)

    monkeypatch.setattr(_regime, "_models_dir", tmp_path)
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))
    _install_bars(monkeypatch, series)

    result = _regime.compute_regime("BTC/USD", lookback_days=120, n_states=2)

    assert result["current_state"] == "high_vol_chop", (
        "the most-recent bars sit in the wild (high-variance) segment, so "
        "the DECODED current state must be the high-variance label"
    )
    assert result["method"] == "hmm"
    # canonical §3 output schema (docs/research/'Market Analysis Engine —
    # Comprehensive Design Document.md' §3 get_regime) — schema keys only,
    # per the standing "example numbers are untrusted" warning.
    expected_keys = {
        "symbol",
        "current_state",
        "state_index",
        "confidence",
        "state_metrics",
        "recommended_strategies",
        "avoid_strategies",
        "method",
        "warnings",
    }
    assert expected_keys <= result.keys()
    assert {"annualized_vol", "mean_return_daily", "avg_state_duration_days"} <= result[
        "state_metrics"
    ].keys()


# ---------------------------------------------------------------------------
# Persistence round-trip: first call fits+writes pkl+json into the tmp
# models dir; second call with the SAME clock loads WITHOUT refit.
# ---------------------------------------------------------------------------


def test_persistence_round_trip_second_call_does_not_refit(monkeypatch, tmp_path) -> None:
    random.seed(1010)
    returns = [random.gauss(0.0, 0.01) for _ in range(90)]
    closes = _closes_from_returns(returns)
    series = _bar_series_from_closes(closes)

    monkeypatch.setattr(_regime, "_models_dir", tmp_path)
    fixed_now = datetime(2026, 7, 16, tzinfo=UTC)
    _install_fixed_clock(monkeypatch, fixed_now)
    _install_bars(monkeypatch, series)

    first = _regime.compute_regime("BTC/USD", lookback_days=90, n_states=2)
    pkl_path, json_path = _regime._artifact_paths("BTC/USD", 90)
    assert pkl_path.exists()
    assert json_path.exists(), "first call must fit + persist an artifact"
    sidecar_mtime_after_first = json_path.stat().st_mtime
    sidecar_bytes_after_first = json_path.read_bytes()

    second = _regime.compute_regime("BTC/USD", lookback_days=90, n_states=2)

    assert json_path.stat().st_mtime == sidecar_mtime_after_first, (
        "second call at the SAME clock must NOT rewrite the sidecar — no refit"
    )
    assert json_path.read_bytes() == sidecar_bytes_after_first
    assert "refit" not in second.get("warnings", []), "no refit note on a cache-hit load"
    assert second["current_state"] == first["current_state"]
    assert second["method"] == first["method"]


# ---------------------------------------------------------------------------
# Staleness: advance the fake clock 8 days -> refit happens.
# ---------------------------------------------------------------------------


def test_staleness_eight_days_later_triggers_refit(monkeypatch, tmp_path) -> None:
    random.seed(2020)
    returns = [random.gauss(0.0, 0.01) for _ in range(90)]
    closes = _closes_from_returns(returns)
    series = _bar_series_from_closes(closes)

    monkeypatch.setattr(_regime, "_models_dir", tmp_path)
    first_now = datetime(2026, 7, 1, tzinfo=UTC)
    _install_fixed_clock(monkeypatch, first_now)
    _install_bars(monkeypatch, series)

    _regime.compute_regime("BTC/USD", lookback_days=90, n_states=2)
    _pkl_path, json_path = _regime._artifact_paths("BTC/USD", 90)
    mtime_after_first = json_path.stat().st_mtime

    # Advance the clock 8 days (> the 7-day staleness window) — same bars,
    # same symbol, same lookback.
    _install_fixed_clock(monkeypatch, first_now + timedelta(days=8))

    second = _regime.compute_regime("BTC/USD", lookback_days=90, n_states=2)

    assert json_path.stat().st_mtime != mtime_after_first, (
        "a sidecar fit_date older than 7 days vs _runtime.clock() must trigger a refit"
    )
    assert "refit" in second.get("warnings", []), (
        "staleness-triggered refits must be logged in the output's warnings/notes list"
    )


# ---------------------------------------------------------------------------
# Path validation: a symbol crafted to escape _models_dir is refused.
# ---------------------------------------------------------------------------


def test_compute_regime_rejects_path_escaping_symbol(monkeypatch, tmp_path) -> None:
    random.seed(3030)
    returns = [random.gauss(0.0, 0.01) for _ in range(90)]
    closes = _closes_from_returns(returns)
    series = _bar_series_from_closes(closes)

    monkeypatch.setattr(_regime, "_models_dir", tmp_path)
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))
    _install_bars(monkeypatch, series)

    with pytest.raises(ValueError):
        _regime.compute_regime("..\\..\\secrets", lookback_days=90, n_states=2)


# ---------------------------------------------------------------------------
# EWMA override (G3): a planted spike in the trailing 30 log-returns must
# push method="ewma_override", state="high_vol_chop", recommended_strategies
# empty — threshold side derived from the fitted artifact, not hardcoded.
# ---------------------------------------------------------------------------


def test_ewma_override_planted_spike_triggers(monkeypatch, tmp_path) -> None:
    random.seed(99)
    calm_returns = [random.gauss(0.0, 0.004) for _ in range(59)]
    planted_tail = [random.gauss(0.0, 0.004) for _ in range(29)] + [0.25]
    all_returns = calm_returns + planted_tail
    closes = _closes_from_returns(all_returns)
    series = _bar_series_from_closes(closes)

    monkeypatch.setattr(_regime, "_models_dir", tmp_path)
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))
    _install_bars(monkeypatch, series)

    result = _regime.compute_regime("BTC/USD", lookback_days=120, n_states=2)

    assert result["method"] == "ewma_override"
    assert result["current_state"] == "high_vol_chop"
    assert result["recommended_strategies"] == []


# ---------------------------------------------------------------------------
# Rules fallback: < 60 daily bars -> method="rules" + insufficient_history
# warning; grid-outcome fixtures (Section 2 in the module docstring).
# ---------------------------------------------------------------------------


def test_rules_fallback_forty_bars_insufficient_history(monkeypatch, tmp_path) -> None:
    closes = [100.0 + i for i in range(40)]
    series = _bar_series_from_closes(closes)

    monkeypatch.setattr(_regime, "_models_dir", tmp_path)
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))
    _install_bars(monkeypatch, series)

    result = _regime.compute_regime("BTC/USD", lookback_days=40, n_states=2)

    assert result["method"] == "rules"
    assert "insufficient_history" in result["warnings"]


def test_rules_fallback_grid_trend_fixture_low_vol_trend(monkeypatch, tmp_path) -> None:
    # derive_p1c_batchB.py Section 2a: steady +1.0/day, n=45 -> ADX(14)=100.0,
    # vol_pctile=0.04 -> grid's ADX>=25 branch -> "low_vol_trend".
    closes = [100.0 + 1.0 * i for i in range(45)]
    series = _bar_series_from_closes(closes)

    monkeypatch.setattr(_regime, "_models_dir", tmp_path)
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))
    _install_bars(monkeypatch, series)

    result = _regime.compute_regime("BTC/USD", lookback_days=45, n_states=2)

    assert result["current_state"] == "low_vol_trend"
    assert result["method"] == "rules"


def test_rules_fallback_grid_chop_fixture_high_vol_chop_wins_priority(
    monkeypatch, tmp_path
) -> None:
    # derive_p1c_batchB.py Section 2b: seed=7, small noise then a late
    # 6-bar vol expansion, n=45 -> ADX(14)=36.8 (would ALSO clear the trend
    # threshold) but vol_pctile=1.0 > 0.8 -> the grid's vol_pctile branch is
    # checked FIRST and wins -> "high_vol_chop". This is the priority-order
    # trap: an implementation that checks ADX before vol_pctile would fail
    # this test.
    random.seed(7)
    closes = [100.0]
    n = 45
    for i in range(n - 1):
        step = random.uniform(-0.3, 0.3) if i < n - 6 else random.uniform(-3.0, 3.0)
        closes.append(closes[-1] + step)
    series = _bar_series_from_closes(closes)

    monkeypatch.setattr(_regime, "_models_dir", tmp_path)
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))
    _install_bars(monkeypatch, series)

    result = _regime.compute_regime("BTC/USD", lookback_days=45, n_states=2)

    assert result["current_state"] == "high_vol_chop"
    assert result["method"] == "rules"


def test_rules_fallback_grid_neutral_fixture(monkeypatch, tmp_path) -> None:
    # derive_p1c_batchB.py Section 2c: seed=55, flat random walk, n=45 ->
    # ADX(14)=10.27 (< 25), vol_pctile=0.56 (<= 0.8) -> neither grid branch
    # fires -> `_regime._RULES_NEUTRAL_STATE` (asserted via the module
    # constant, not a hardcoded string — this bucket's exact name is a
    # flagged, CTO-unratified ambiguity, see tests/ASSUMPTIONS.md).
    random.seed(55)
    closes = [100.0]
    for _ in range(44):
        closes.append(closes[-1] + random.uniform(-0.5, 0.5))
    series = _bar_series_from_closes(closes)

    monkeypatch.setattr(_regime, "_models_dir", tmp_path)
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))
    _install_bars(monkeypatch, series)

    result = _regime.compute_regime("BTC/USD", lookback_days=45, n_states=2)

    assert result["current_state"] == _regime._RULES_NEUTRAL_STATE
    assert result["method"] == "rules"


# ---------------------------------------------------------------------------
# Non-convergence: force `_fit_hmm` to fail -> rules fallback + warning.
# ---------------------------------------------------------------------------


def test_hmm_non_convergence_falls_back_to_rules(monkeypatch, tmp_path) -> None:
    random.seed(4040)
    returns = [random.gauss(0.0, 0.01) for _ in range(90)]
    closes = _closes_from_returns(returns)
    series = _bar_series_from_closes(closes)

    monkeypatch.setattr(_regime, "_models_dir", tmp_path)
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))
    _install_bars(monkeypatch, series)

    def _non_converging_fit(features: list[tuple[float, float]], n_states: int) -> None:
        raise RuntimeError("hmmlearn non-convergence (simulated)")

    monkeypatch.setattr(_regime, "_fit_hmm", _non_converging_fit)

    result = _regime.compute_regime("BTC/USD", lookback_days=90, n_states=2)

    assert result["method"] == "rules", (
        "non-convergence must NEVER return a half-fit model's states"
    )
    assert "hmm_non_convergence" in result["warnings"]


# ---------------------------------------------------------------------------
# Lookahead / plumbing: compute_regime consumes whatever
# `_runtime.get_daily_bars` returns, passes lookback_days correctly, and
# NEVER calls a provider directly (it must not call `_runtime.provider_for`
# or import a provider itself — the only bar-fetch call is get_daily_bars).
# ---------------------------------------------------------------------------


def test_compute_regime_calls_get_daily_bars_once_with_correct_lookback(
    monkeypatch, tmp_path
) -> None:
    random.seed(5050)
    returns = [random.gauss(0.0, 0.01) for _ in range(90)]
    closes = _closes_from_returns(returns)
    series = _bar_series_from_closes(closes)

    monkeypatch.setattr(_regime, "_models_dir", tmp_path)
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))
    calls = _install_bars(monkeypatch, series)

    def _fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("compute_regime must never call provider_for directly")

    monkeypatch.setattr("tradekit.mae._runtime.provider_for", _fail_if_called)

    _regime.compute_regime("BTC/USD", lookback_days=77, n_states=2)

    assert calls == [("BTC/USD", 77)], (
        f"expected exactly one get_daily_bars('BTC/USD', 77) call, got {calls!r}"
    )
