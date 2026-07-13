"""tradekit.mae — Market Analysis Engine (DESIGN §9, TD-12).

Deep interface: exactly the six canonical verbs. Data providers, indicators,
regime models, and metric math are private implementation.

Status: compute_strategy_metrics is COMPLETE (pure, offline — TD-14/G1 math
in _metrics.py). The other five verbs are pinned signatures awaiting the P1
data layer; each stub names its handoff sprint doc.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from tradekit.contracts import StrategyMetrics, TradeRecord
from tradekit.mae import _metrics


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
    """HMM regime classification + EWMA 3-sigma override (TD-13, G3)."""
    raise NotImplementedError("P1 — docs/handoff/SPRINT-P1C-regime-scanner-sizing.md")


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
    raise NotImplementedError("P1 — docs/handoff/SPRINT-P1C-regime-scanner-sizing.md")


def get_correlation_matrix(
    symbols: list[str], window_days: int = 30, timeframe: str = "1d"
) -> dict[str, Any]:
    """Rolling Pearson on daily log-returns, UTC inner-join (§9.1, R-013)."""
    raise NotImplementedError("P1 — docs/handoff/SPRINT-P1C-regime-scanner-sizing.md")


__all__ = [
    "compute_strategy_metrics",
    "get_correlation_matrix",
    "get_derivatives_context",
    "get_regime",
    "scan_markets",
    "size_position",
]
