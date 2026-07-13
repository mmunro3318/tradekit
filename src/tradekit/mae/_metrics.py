"""Strategy-metrics math (DESIGN §9.4, TD-14, G1). Pure stdlib, fully offline.

Conventions (binding — tests/unit/mae golden vectors derive from these):

- Per-trade pnl = side * (exit-entry)/entry * size_usd - fees_usd, side +1
  long / -1 short. Money math in Decimal; ratios in float (§13).
- Per-trade return r = pnl / size_usd.
- Sharpe: trade-level SR = (mean(r) - rf_per_trade) / stdev(r, ddof=1),
  annualized by sqrt(trades_per_year) with trades_per_year = n / span_years,
  span = first entry -> last exit, 365.25-day years. rf_per_trade =
  risk_free_rate_annual * avg_hold_years.
- Sortino: downside deviation over the FULL sample (n in the denominator,
  not just losers), MAR applied per-trade; annualized identically.
- Drawdown: cumulative-pnl curve in exit_ts order. Percent drawdown and
  Calmar are measured against PEAK equity and need base_equity_usd.
- PSR/DSR (Bailey & Lopez de Prado): computed on the NON-annualized
  per-trade SR. DSR's benchmark SR0 uses V[SR] = (1 - g3*SR +
  (g4-1)/4*SR^2)/(n-1) with g4 the RAW kurtosis (normal = 3), and the real
  n_trials from the experiment registry. DSR only at n >= 30; the
  10 <= n < 30 band reports penalized SR = SR_annual * (1 - 1/sqrt(n)) (G1).
"""

from __future__ import annotations

import math
import statistics
from decimal import Decimal
from typing import Any, Literal

from pydantic import TypeAdapter

from tradekit.contracts import StrategyMetrics, TradeRecord

_EULER_GAMMA = 0.5772156649015329
_HOURS_PER_YEAR = 365.25 * 24.0
_TRADES = TypeAdapter(list[TradeRecord])


def compute(
    trade_log: list[TradeRecord] | list[dict[str, Any]],
    *,
    risk_free_rate_annual: float,
    mar: float,
    n_trials: int,
    base_equity_usd: Decimal | None,
) -> StrategyMetrics:
    trades = _TRADES.validate_python(trade_log)
    if not trades:
        raise ValueError("empty trade_log: nothing to evaluate")
    for t in trades:
        if t.exit_ts < t.entry_ts:
            raise ValueError(f"trade exits before it enters: {t.entry_ts} -> {t.exit_ts}")

    trades = sorted(trades, key=lambda t: (t.exit_ts, t.entry_ts))
    warnings: list[str] = []
    n = len(trades)

    pnls = [_pnl(t) for t in trades]
    returns = [float(p / t.size_usd) for p, t in zip(pnls, trades, strict=True)]
    total_pnl = sum(pnls, Decimal("0"))
    total_fees = sum((t.fees_usd for t in trades), Decimal("0"))

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_rate = len(wins) / n
    avg_win = sum(wins, Decimal("0")) / len(wins) if wins else None
    avg_loss = abs(sum(losses, Decimal("0")) / len(losses)) if losses else None
    expectancy = total_pnl / n

    gross_loss = abs(sum(losses, Decimal("0")))
    if not losses or gross_loss == 0:
        profit_factor = None
        warnings.append("no_losing_trades")
    else:
        profit_factor = float(sum(wins, Decimal("0")) / gross_loss)
        if profit_factor > 3.0:
            warnings.append("overfit_risk_pf")  # PF>3 rarely survives out-of-sample (canonical §3)
    if not wins:
        warnings.append("no_winning_trades")

    hold_hours = [(t.exit_ts - t.entry_ts).total_seconds() / 3600.0 for t in trades]
    avg_hold_hours = sum(hold_hours) / n
    span_years = (
        max(t.exit_ts for t in trades) - min(t.entry_ts for t in trades)
    ).total_seconds() / (_HOURS_PER_YEAR * 3600.0)

    sharpe_annual, sortino_annual, sr_trade = _risk_ratios(
        returns, risk_free_rate_annual, mar, avg_hold_hours, span_years, n, warnings
    )
    mdd_usd, mdd_pct, calmar = _drawdown_block(
        pnls, total_pnl, base_equity_usd, span_years, warnings
    )

    dsr, penalized = _small_sample_regime(
        returns, sr_trade, sharpe_annual, n, n_trials, warnings
    )

    return StrategyMetrics(
        n_trades=n,
        win_rate=win_rate,
        avg_win_usd=avg_win,
        avg_loss_usd=avg_loss,
        expectancy_usd=expectancy,
        profit_factor=profit_factor,
        sharpe_annual=sharpe_annual,
        sortino_annual=sortino_annual,
        calmar=calmar,
        max_drawdown_usd=mdd_usd,
        max_drawdown_pct=mdd_pct,
        total_pnl_usd=total_pnl,
        total_fees_usd=total_fees,
        avg_hold_hours=avg_hold_hours,
        dsr=dsr,
        penalized_sharpe_annual=penalized,
        n_trials=n_trials,
        edge_verdict=_verdict(n, expectancy, profit_factor, dsr, penalized),
        warnings=warnings,
    )


def _pnl(t: TradeRecord) -> Decimal:
    direction = Decimal(1) if t.side == "long" else Decimal(-1)
    return direction * (t.exit_price - t.entry_price) / t.entry_price * t.size_usd - t.fees_usd


def _risk_ratios(
    returns: list[float],
    rf_annual: float,
    mar: float,
    avg_hold_hours: float,
    span_years: float,
    n: int,
    warnings: list[str],
) -> tuple[float | None, float | None, float | None]:
    """(sharpe_annual, sortino_annual, per-trade SR for PSR/DSR)."""
    if span_years <= 0:
        warnings.append("zero_time_span")
        return None, None, None
    if n < 2:
        warnings.append("sample_size_insufficient")
        return None, None, None

    ann = math.sqrt(n / span_years)  # sqrt(trades per year)
    rf_per_trade = rf_annual * (avg_hold_hours / _HOURS_PER_YEAR)
    mean_r = statistics.fmean(returns)

    std = statistics.stdev(returns)
    sr_trade = (mean_r - rf_per_trade) / std if std > 0 else None
    sharpe = sr_trade * ann if sr_trade is not None else None
    if std == 0:
        warnings.append("zero_variance")

    downside = math.sqrt(sum(min(0.0, r - mar) ** 2 for r in returns) / n)
    sortino = ((mean_r - mar) / downside) * ann if downside > 0 else None
    return sharpe, sortino, sr_trade


def _drawdown_block(
    pnls: list[Decimal],
    total_pnl: Decimal,
    base_equity: Decimal | None,
    span_years: float,
    warnings: list[str],
) -> tuple[Decimal, float | None, float | None]:
    cum = Decimal("0")
    peak = Decimal("0")
    mdd_usd = Decimal("0")
    mdd_pct = 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        mdd_usd = max(mdd_usd, peak - cum)
        if base_equity is not None and (base_equity + peak) > 0:
            mdd_pct = max(mdd_pct, float((peak - cum) / (base_equity + peak)))

    if base_equity is None:
        warnings.append("base_equity_not_provided")
        return mdd_usd, None, None

    calmar = None
    total_ret = float(total_pnl / base_equity)
    if span_years > 0 and (1.0 + total_ret) > 0:
        cagr = (1.0 + total_ret) ** (1.0 / span_years) - 1.0
        if mdd_pct > 0:
            calmar = cagr / mdd_pct
        else:
            warnings.append("no_drawdown")
    return mdd_usd, mdd_pct, calmar


def _small_sample_regime(
    returns: list[float],
    sr_trade: float | None,
    sharpe_annual: float | None,
    n: int,
    n_trials: int,
    warnings: list[str],
) -> tuple[float | None, float | None]:
    """G1: DSR at n>=30; penalized Sharpe in [10, 30); nothing below 10."""
    if n < 10:
        if "sample_size_insufficient" not in warnings:
            warnings.append("sample_size_insufficient")
        warnings.append("dsr_not_applicable_small_n")
        return None, None
    if n < 50:
        warnings.append("sample_size_small")
    if n < 30:
        warnings.append("dsr_not_applicable_small_n")
        penalized = (
            sharpe_annual * (1.0 - 1.0 / math.sqrt(n)) if sharpe_annual is not None else None
        )
        return None, penalized
    if sr_trade is None:
        return None, None
    return _deflated_sharpe(returns, sr_trade, n, max(1, n_trials), warnings), None


def _deflated_sharpe(
    returns: list[float], sr: float, n: int, n_trials: int, warnings: list[str]
) -> float | None:
    mean_r = statistics.fmean(returns)
    m2 = statistics.fmean([(r - mean_r) ** 2 for r in returns])
    if m2 <= 0:
        warnings.append("zero_variance")
        return None
    skew = statistics.fmean([(r - mean_r) ** 3 for r in returns]) / m2**1.5
    kurt = statistics.fmean([(r - mean_r) ** 4 for r in returns]) / m2**2  # raw; normal=3

    denom = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr
    if denom <= 0:
        warnings.append("psr_denominator_nonpositive")
        return None

    if n_trials <= 1:
        sr_star = 0.0
    else:
        norm = statistics.NormalDist()
        v_sr = denom / (n - 1)
        sr_star = math.sqrt(v_sr) * (
            (1.0 - _EULER_GAMMA) * norm.inv_cdf(1.0 - 1.0 / n_trials)
            + _EULER_GAMMA * norm.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
        )

    z = (sr - sr_star) * math.sqrt(n - 1.0) / math.sqrt(denom)
    return statistics.NormalDist().cdf(z)


def _verdict(
    n: int,
    expectancy: Decimal,
    profit_factor: float | None,
    dsr: float | None,
    penalized: float | None,
) -> Literal["positive", "marginal", "negative", "insufficient"]:
    """Deterministic verdict table (DESIGN §9.4). PF None = no losers = passes
    the PF bar by construction."""
    if n < 10:
        return "insufficient"
    if expectancy <= 0 or (profit_factor is not None and profit_factor < 1.0):
        return "negative"
    pf_ok = profit_factor is None or profit_factor >= 1.3
    edge_ok = (dsr is not None and dsr > 0.5) if n >= 30 else (penalized or 0.0) > 0.0
    if pf_ok and expectancy > 0 and edge_ok:
        return "positive"
    return "marginal"
