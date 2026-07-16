"""tradekit.mae — Market Analysis Engine (DESIGN §9, TD-12).

Deep interface: exactly the six canonical verbs. Data providers, indicators,
regime models, and metric math are private implementation.

Status: compute_strategy_metrics is COMPLETE (pure, offline — TD-14/G1 math
in _metrics.py). The other five verbs are pinned signatures awaiting the P1
data layer; each stub names its handoff sprint doc.
"""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal
from typing import Any

from tradekit.contracts import StrategyMetrics, TradeRecord
from tradekit.mae import _correlation, _metrics, _regime, _runtime, _sizing
from tradekit.mae._indicators import volatility


def scan_markets(
    asset_class: str,
    timeframes: list[str],
    filters: dict[str, Any],
    symbols: list[str] | None = None,
    regime_gate: bool = True,
) -> dict[str, Any]:
    """Screen a universe for setups matching TA filters (canonical §3)."""
    raise NotImplementedError("P1 — docs/handoff/SPRINT-P1C-regime-scanner-sizing.md")


def get_regime(symbol: str, lookback_days: int = 90, n_states: int = 3) -> dict[str, Any]:
    """HMM regime classification + EWMA 3-sigma override (TD-13, G3).

    P1C batch B design pins (dev pass wires this body to
    `tradekit.mae._regime.compute_regime(symbol, lookback_days, n_states)` —
    see that module's docstring for the full fit/persist/staleness/override/
    rules-fallback contract; internals never re-exported here per DESIGN §1):

    - Output carries canonical §3's `get_regime` keys — `symbol`,
      `current_state` (`"low_vol_trend" | "high_vol_chop" | "breakdown"`),
      `state_index`, `confidence`, `state_metrics` (`annualized_vol`,
      `mean_return_daily`, `avg_state_duration_days`),
      `recommended_strategies`, `avoid_strategies` — PLUS `method`
      (`"hmm" | "ewma_override" | "rules"`) and a `warnings` list, which the
      addendum requires (`refit`/`insufficient_history`/
      `hmm_non_convergence` notes) but canonical §3's example output does
      not show at all — flagged, not resolved, this batch (see
      `tests/ASSUMPTIONS.md`'s new P1C-batch-B entry; same shape as
      assumption 47's size_position/get_correlation_matrix precedent).
    - Bars come ONLY from `_runtime.get_daily_bars(symbol, lookback_days)`
      (closed daily bars — the live bar is never visible here, batch A's
      lookahead trap); `get_regime` never calls a provider directly.
    - EWMA override (G3): `method="ewma_override"` forces
      `current_state="high_vol_chop"` and `recommended_strategies=[]`,
      computed as pure arithmetic on the LOADED artifact — never triggers a
      refit.
    - Rules fallback (`method="rules"`) fires on < 60 daily bars or HMM
      non-convergence; never returns a half-fit model's states (Traps).
    """
    return _regime.compute_regime(symbol, lookback_days, n_states)


def get_derivatives_context(symbol: str, lookback_periods: int = 48) -> dict[str, Any]:
    """Perp funding/OI/positioning via provider chain (TD-12, G6). Phase 3."""
    raise NotImplementedError("P3 — DESIGN §9.1 derivatives bullet; deprioritized per Mike")


def compute_strategy_metrics(
    trade_log: list[TradeRecord] | list[dict[str, Any]],
    *,
    risk_free_rate_annual: float = 0.045,
    mar: float = 0.0,
    n_trials: int = 1,
    base_equity_usd: Decimal | None = None,
) -> StrategyMetrics:
    """Evaluate a trade log's statistical edge (DESIGN §9.4, TD-14, G1).

    Pure and offline. ``n_trials`` is the number of strategy variants tested
    (query the experiment registry for it — DSR is only honest with the real
    count). ``base_equity_usd`` unlocks percent-drawdown and Calmar; without
    it they are None + warning, never a guess.
    """
    return _metrics.compute(
        trade_log,
        risk_free_rate_annual=risk_free_rate_annual,
        mar=mar,
        n_trials=n_trials,
        base_equity_usd=base_equity_usd,
    )


def size_position(
    symbol: str,
    account_equity_usd: Decimal,
    risk_pct_per_trade: float = 0.01,
    atr_multiplier: float = 2.0,
    kelly_win_rate: float | None = None,
    kelly_payoff_ratio: float | None = None,
    kelly_fraction: float = 0.25,
) -> dict[str, Any]:
    """min(ATR-normalized, quarter-Kelly) sizing; purity per TD-11 — the
    signature can never grow P&L-history inputs."""
    if (kelly_win_rate is None) != (kelly_payoff_ratio is None):
        raise ValueError(
            "kelly_win_rate and kelly_payoff_ratio must both be provided or both be "
            "None — half an edge spec is a caller bug, not a degraded mode"
        )

    bars = _runtime.get_daily_bars(symbol, lookback_days=30)
    closes = [float(b.close) for b in bars.bars]
    highs = [float(b.high) for b in bars.bars]
    lows = [float(b.low) for b in bars.bars]

    current_price = closes[-1]
    atr_values = volatility.atr(highs, lows, closes, period=14)
    non_none_atr = [v for v in atr_values if v is not None]
    if not non_none_atr:
        raise ValueError(
            f"insufficient closed daily bars for {symbol!r} to compute ATR(14); "
            f"got {len(closes)} bars, need at least 14"
        )
    atr_14 = non_none_atr[-1]

    warnings: list[str] = []

    atr_result = _sizing.atr_position(
        equity_usd=account_equity_usd,
        risk_pct=risk_pct_per_trade,
        atr=Decimal(str(atr_14)),
        multiplier=atr_multiplier,
        price=Decimal(str(current_price)),
    )
    atr_position_size_usd = float(atr_result["size_usd"])
    atr_units = float(atr_result["units"])
    stop_distance_usd = float(atr_result["stop_distance"])
    stop_pct = float(atr_result["stop_pct"])
    risk_usd = float(atr_result["risk_usd"])

    if kelly_win_rate is None or kelly_payoff_ratio is None:
        warnings.append("kelly_inputs_missing")
        kelly_full_f = 0.0
        kelly_quarter_f = 0.0
        kelly_position_size_usd = 0.0
        recommended_size_usd = atr_position_size_usd
    else:
        kelly_full_f, kelly_quarter_f = _sizing.kelly_fractions(
            win_rate=kelly_win_rate, payoff_ratio=kelly_payoff_ratio, fraction=kelly_fraction
        )
        if kelly_full_f <= 0.0:
            warnings.append("negative_kelly")
        kelly_position_size_usd = kelly_quarter_f * float(account_equity_usd)
        recommended_size_usd = min(atr_position_size_usd, kelly_position_size_usd)

    recommended_units = recommended_size_usd / current_price if current_price else 0.0

    return {
        "symbol": symbol,
        "current_price": current_price,
        "atr_14": atr_14,
        "stop_distance_usd": stop_distance_usd,
        "stop_pct": stop_pct,
        "atr_position_size_usd": atr_position_size_usd,
        "atr_units": atr_units,
        "kelly_full_f": kelly_full_f,
        "kelly_quarter_f": kelly_quarter_f,
        "kelly_position_size_usd": kelly_position_size_usd,
        "recommended_size_usd": recommended_size_usd,
        "recommended_units": recommended_units,
        "risk_usd": risk_usd,
        "r_multiple_target": 2.0,
        "warnings": warnings,
    }


def get_correlation_matrix(
    symbols: list[str], window_days: int = 30, timeframe: str = "1d"
) -> dict[str, Any]:
    """Rolling Pearson on daily log-returns, UTC inner-join (§9.1, R-013)."""
    series_by_symbol: dict[str, list[tuple[date, float]]] = {}
    for symbol in symbols:
        bars = _runtime.get_daily_bars(symbol, lookback_days=window_days)
        closes = [(b.ts_open.date(), float(b.close)) for b in bars.bars]
        returns: list[tuple[date, float]] = []
        for i in range(1, len(closes)):
            prev_close = closes[i - 1][1]
            curr_date, curr_close = closes[i]
            if prev_close > 0 and curr_close > 0:
                returns.append((curr_date, math.log(curr_close / prev_close)))
        series_by_symbol[symbol] = returns

    result = _correlation.compute_correlation(series_by_symbol)

    high_correlation_warnings = [
        {"pair": [a, b], "r": r} for a, b, r in result.high_correlation_warnings
    ]
    insufficient_overlap_warnings = [
        {"pair": [a, b], "overlap": overlap}
        for a, b, overlap in result.insufficient_overlap_warnings
    ]

    return {
        "matrix": result.matrix,
        "window_days": window_days,
        "as_of": _runtime.clock().isoformat(),
        "high_correlation_warnings": high_correlation_warnings,
        "insufficient_overlap_warnings": insufficient_overlap_warnings,
    }


__all__ = [
    "compute_strategy_metrics",
    "get_correlation_matrix",
    "get_derivatives_context",
    "get_regime",
    "scan_markets",
    "size_position",
]
