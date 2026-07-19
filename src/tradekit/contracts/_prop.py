"""Prop evaluation simulator contracts (SPRINT P5-PROP §1b; ASSUMPTIONS
round-26). Money is Decimal, ratios/statistics are float (§13 convention —
percentile equity paths and probabilities are statistics, not ledger money).

Trade models are a discriminated union (StrictFrozenModel variants, same
`extra="forbid"` rationale as the thesis predicates): `parametric` draws
independent per-trade outcomes (entry 148), `empirical` block-bootstraps a
TradeRecord sample, `scripted` replays a fixed sequence as ONE deterministic
path (entry 147 — the golden/replay seam and the backtest→barriers bridge).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field

from tradekit.contracts._base import FrozenModel, StrictFrozenModel
from tradekit.contracts._metrics import TradeRecord


class ParametricTradeModel(StrictFrozenModel):
    kind: Literal["parametric"] = "parametric"
    win_rate: float = Field(ge=0.0, le=1.0)
    payoff_ratio: float = Field(gt=0.0)  # avg win R / avg loss R
    risk_frac: Decimal = Field(gt=0)  # fraction of CURRENT balance risked (entry 148)
    notional_frac: Decimal = Field(gt=0)  # position notional as fraction of balance
    trades_per_day: int = Field(ge=1)
    hold_hours: float = Field(gt=0.0)


class EmpiricalTradeModel(StrictFrozenModel):
    kind: Literal["empirical"] = "empirical"
    trades: tuple[TradeRecord, ...] = Field(min_length=1)
    block_len: int = Field(ge=1)  # serial dependence lives HERE (entry 148)
    trades_per_day: int = Field(ge=1)


class ScriptedTradeModel(StrictFrozenModel):
    kind: Literal["scripted"] = "scripted"
    trades: tuple[TradeRecord, ...] = Field(min_length=1)


TradeModel = ParametricTradeModel | EmpiricalTradeModel | ScriptedTradeModel


class PropSimSpec(FrozenModel):
    """One evaluation-simulation request. Barrier dials are the VENUE
    numbers (entry 144: R-rules enforce internal walls; the simulator
    models the venue's outer truth). Defaults are Kraken Prop Starter
    (Report-1 §6/§8)."""

    starting_balance: Decimal = Field(gt=0)
    mdl_pct: Decimal = Field(default=Decimal("0.03"), gt=0)
    mdd_pct: Decimal = Field(default=Decimal("0.06"), gt=0)
    # None = funded-mode variant: no target barrier (sprint §1b).
    profit_target_pct: Decimal | None = Field(default=Decimal("0.10"))
    fee_side_bps: Decimal = Field(default=Decimal("4"), ge=0)
    funding_daily_pct: Decimal = Field(default=Decimal("0.00033"), ge=0)
    ruin_prob_monthly_max: float = Field(default=0.02, gt=0.0, lt=1.0)  # Q.A.8
    trade_model: TradeModel = Field(discriminator="kind")
    n_paths: int = Field(default=10_000, ge=1)
    horizon_days: int = Field(ge=1)


class PropSimResult(FrozenModel):
    """simulate_evaluation output. Scripted mode is one deterministic path:
    probabilities collapse to {0.0, 1.0} and the `final_balance` /
    `first_breach_day` / `breach_reason` / `daily_snapshots` fields are
    populated; in parametric/empirical mode those four are None (a single
    path's ledger is meaningless across 10k paths)."""

    pass_prob: float
    ruin_prob: float  # total; split below
    ruin_prob_mdl: float
    ruin_prob_mdd: float
    survival_prob: float  # horizon ended, no barrier hit
    expected_days_to_outcome: float | None  # None when nothing absorbed
    # keys "p05"/"p50"/"p95" -> per-day equity levels (statistics -> float)
    equity_percentiles: dict[str, list[float]]
    daily_breach_hazard: list[float]
    # Largest ladder rung with monthly ruin <= ruin_prob_monthly_max
    # (entry 150); parametric mode only, None otherwise or when no rung clears.
    recommended_max_risk_frac: Decimal | None
    # Scripted-mode-only observability (entry 147):
    final_balance: Decimal | None = None
    first_breach_day: int | None = None  # 1-based day index
    breach_reason: Literal["mdl", "mdd"] | None = None
    daily_snapshots: list[Decimal] | None = None  # 00:30 UTC balances; [0] = day 1


__all__ = [
    "EmpiricalTradeModel",
    "ParametricTradeModel",
    "PropSimResult",
    "PropSimSpec",
    "ScriptedTradeModel",
    "TradeModel",
]
