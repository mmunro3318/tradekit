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
from decimal import ROUND_DOWN, Decimal
from typing import Any

from tradekit.contracts import StrategyMetrics, TradeRecord
from tradekit.mae import _confluence, _correlation, _metrics, _regime, _runtime, _scanner, _sizing
from tradekit.mae._confluence import ScanLeg
from tradekit.mae._indicators import volatility
from tradekit.mae._scan_trace import ScanAuditMode
from tradekit.mae._strategies import STRATEGIES, STRATEGY_BY_KEY, StrategyDef, build_registry
from tradekit.mae._vocab import BBPosition, MacdSignal


def scan_markets(
    asset_class: str,
    timeframes: list[str],
    filters: dict[str, Any],
    symbols: list[str] | None = None,
    regime_gate: bool = True,
    *,
    audit: ScanAuditMode = "off",
) -> dict[str, Any]:
    """Screen a universe for setups matching TA filters (canonical §3).

    P1C batch C: thin delegate to `_scanner.scan` — see that module's
    docstring for the full fetch -> indicator -> filter -> regime-gate
    pipeline, filter semantics, and output-shape pins (internals never
    re-exported here per DESIGN §1, same shape as `get_regime`).

    `audit` (T-AUDIT-2): passed through untouched to `_scanner.scan` — see
    that function's docstring for the "off"/"on"/"exhaustive" contract."""
    return _scanner.scan(asset_class, timeframes, filters, symbols, regime_gate, audit=audit)


def scan_confluence(
    asset_class: str,
    legs: list[ScanLeg],
    symbols: list[str],
    regime_gate: bool = True,
) -> dict[str, Any]:
    """Multi-timeframe AND-across-legs confluence scan (T-MTF-2,
    docs/design/MTF-SCAN.md "New verb" section).

    Thin delegate to `_confluence.confluence` — see that function's
    docstring for the per-leg lookback/regime-cache/warning-taxonomy pins
    (internals never re-exported here per DESIGN §1, same shape as
    `scan_markets`'s own `_scanner.scan` delegate)."""
    return _confluence.confluence(asset_class, legs, symbols, regime_gate)


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
    *,
    price: Decimal | None = None,
    max_position_usd: Decimal | None = None,
    size_scale: Decimal = Decimal("1"),
) -> dict[str, Any]:
    """min(ATR-normalized, quarter-Kelly) sizing; purity per TD-11 — the
    signature can never grow P&L-history inputs.

    `price`/`max_position_usd` (ASSUMPTIONS 182, SPEC-sizing-cap P1): the
    paper funnel's two sizing call sites now share one price (the ticket's
    limit price) and one cap (`PolicyDials.paper_max_position_usd`) so the
    scan-time preview and the binding `SizingComputed` record never drift.
    `price=None` keeps today's last-daily-close basis; `max_position_usd`
    clips `recommended_size_usd`/`recommended_units` in exact Decimal
    arithmetic so the clipped notional never exceeds the cap by a float
    hair — `atr_position_size_usd`/`kelly_position_size_usd` keep their
    uncapped values as an audit trail.

    `size_scale` (review round 24 F1, ASSUMPTIONS 182.10, SPEC-sizing-cap
    P7): a strategy's own restricted-size fraction (e.g. S4's half-size
    restriction, `StrategyDef.size_scale`), applied AFTER the cap clip in
    exact Decimal arithmetic so the caller-visible `recommended_units`/
    `recommended_size_usd` are the ACTUAL ticket size — the defect this
    fixes is `hud._build`/`thesis._submit` applying the scale themselves
    AFTER calling this function, so the ticket's recorded qty and the
    unscaled `SizingComputed` notional disagreed and every scaled strategy
    died at binding on R-012. `1` (default) is a no-op, byte-identical to
    every pre-existing caller. Must be `> 0` and `<= 1` — a caller bug to
    pass anything else (amplifying size is never a "scale down")."""
    if (kelly_win_rate is None) != (kelly_payoff_ratio is None):
        raise ValueError(
            "kelly_win_rate and kelly_payoff_ratio must both be provided or both be "
            "None — half an edge spec is a caller bug, not a degraded mode"
        )
    if max_position_usd is not None and max_position_usd <= 0:
        raise ValueError(
            "max_position_usd must be positive — a non-positive cap sizes nothing "
            "and is a caller bug"
        )
    if not (Decimal("0") < size_scale <= Decimal("1")):
        raise ValueError(
            "size_scale must be > 0 and <= 1 — a strategy's own restricted-size "
            "fraction, never an amplifier, and is a caller bug otherwise"
        )

    bars = _runtime.get_daily_bars(symbol, lookback_days=30)
    closes = [float(b.close) for b in bars.bars]
    highs = [float(b.high) for b in bars.bars]
    lows = [float(b.low) for b in bars.bars]

    current_price = float(price) if price is not None else closes[-1]
    atr_values = volatility.atr(highs, lows, closes, period=14)
    non_none_atr = [v for v in atr_values if v is not None]
    if not non_none_atr:
        raise ValueError(
            f"insufficient closed daily bars for {symbol!r} to compute ATR(14); "
            f"got {len(closes)} bars, need at least 14"
        )
    atr_14 = non_none_atr[-1]

    warnings: list[str] = []

    price_dec = price if price is not None else Decimal(str(current_price))
    atr_result = _sizing.atr_position(
        equity_usd=account_equity_usd,
        risk_pct=risk_pct_per_trade,
        atr=Decimal(str(atr_14)),
        multiplier=atr_multiplier,
        price=price_dec,
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

    if max_position_usd is not None and recommended_size_usd > float(max_position_usd):
        clipped_units = (max_position_usd / price_dec).quantize(
            Decimal("0.00000001"), rounding=ROUND_DOWN
        )
        recommended_units = float(clipped_units)
        recommended_size_usd = float(clipped_units * price_dec)
        warnings.append("capped_by_max_position")

    if size_scale != Decimal("1"):
        # P7: scale the UNITS in Decimal and re-quantize to 8dp ROUND_DOWN so
        # the caller's own 8dp quantize is a no-op and the recorded notional
        # is exactly units * price — the same exactness the cap clip keeps.
        scaled_units = (Decimal(str(recommended_units)) * size_scale).quantize(
            Decimal("0.00000001"), rounding=ROUND_DOWN
        )
        recommended_units = float(scaled_units)
        recommended_size_usd = float(scaled_units * price_dec)

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
        "max_position_usd": float(max_position_usd) if max_position_usd is not None else None,
        "size_scale": float(size_scale),
        "warnings": warnings,
    }


def get_correlation_matrix(
    symbols: list[str], window_days: int = 30, timeframe: str = "1d"
) -> dict[str, Any]:
    """Rolling Pearson on daily log-returns, UTC inner-join (§9.1, R-013).

    `zero_variance_warnings` lists pairs whose correlation is undefined (a
    constant-return leg) — their matrix cells are None, never a fabricated
    0.0 (ASSUMPTIONS 166)."""
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
    zero_variance_warnings = [
        {"pair": [a, b]} for a, b in result.zero_variance_warnings
    ]

    return {
        "matrix": result.matrix,
        "window_days": window_days,
        "as_of": _runtime.clock().isoformat(),
        "high_correlation_warnings": high_correlation_warnings,
        "insufficient_overlap_warnings": insufficient_overlap_warnings,
        "zero_variance_warnings": zero_variance_warnings,
    }


__all__ = [
    "STRATEGIES",
    "STRATEGY_BY_KEY",
    "BBPosition",
    "MacdSignal",
    "ScanLeg",
    "StrategyDef",
    "build_registry",
    "compute_strategy_metrics",
    "get_correlation_matrix",
    "get_derivatives_context",
    "get_regime",
    "scan_confluence",
    "scan_markets",
    "size_position",
]
