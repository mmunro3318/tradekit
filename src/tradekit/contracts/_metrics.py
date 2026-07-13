"""Trade-log and strategy-metrics contracts (DESIGN §9.4, TD-14).

Money is Decimal; ratios (Sharpe, PF, DSR, ...) are float — they live in the
analysis layer's numeric domain and are never compared against ticks (§13).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, Field

from tradekit.contracts._base import FrozenModel


class TradeRecord(FrozenModel):
    """One completed round-trip trade, as agents submit them for evaluation."""

    entry_ts: AwareDatetime
    exit_ts: AwareDatetime
    entry_price: Decimal = Field(gt=0)
    exit_price: Decimal = Field(gt=0)
    side: Literal["long", "short"]
    size_usd: Decimal = Field(gt=0)
    fees_usd: Decimal = Decimal("0")
    strategy_tag: str | None = None


class StrategyMetrics(FrozenModel):
    """compute_strategy_metrics output. None means 'not computable from the
    inputs given' — a warning names why; nothing is ever silently invented."""

    n_trades: int
    win_rate: float
    avg_win_usd: Decimal | None
    avg_loss_usd: Decimal | None  # absolute value
    expectancy_usd: Decimal  # mean net pnl per trade (fees included)
    profit_factor: float | None  # None when no losing trades
    sharpe_annual: float | None
    sortino_annual: float | None
    calmar: float | None  # needs base_equity_usd
    max_drawdown_usd: Decimal
    max_drawdown_pct: float | None  # vs peak equity; needs base_equity_usd
    total_pnl_usd: Decimal  # net of fees (single number; no gross/net split)
    total_fees_usd: Decimal
    avg_hold_hours: float
    dsr: float | None  # Deflated Sharpe; only at n >= 30 (G1)
    penalized_sharpe_annual: float | None  # only in the 10 <= n < 30 provisional band
    n_trials: int  # strategy variants tested — feeds DSR (experiment registry)
    edge_verdict: Literal["positive", "marginal", "negative", "insufficient"]
    warnings: list[str] = Field(default_factory=list)
