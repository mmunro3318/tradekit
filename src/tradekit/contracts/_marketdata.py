"""Market-data and grading-outcome contracts (DESIGN §9.1, §10.2, TD-17).

Bars carry Decimal prices parsed from venue strings — never through float.
ts_open is canonical (TD-17); a bar's close time is ts_open + timeframe.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import AwareDatetime, Field, model_validator

from tradekit.contracts._base import FrozenModel
from tradekit.contracts._thesis import AssetRef

# Timeframe -> seconds. The single source of truth for bar-close arithmetic;
# grading's lookahead guard depends on it.
TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3_600,
    "4h": 14_400,
    "1d": 86_400,
}


class Bar(FrozenModel):
    ts_open: AwareDatetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def _ohlc_sane(self) -> Bar:
        if not (self.low <= self.open <= self.high and self.low <= self.close <= self.high):
            raise ValueError(
                f"incoherent OHLC at {self.ts_open}: open/close must lie within [low, high]"
            )
        return self


class BarSeries(FrozenModel):
    asset: AssetRef
    timeframe: str
    bars: list[Bar]
    source: str  # provider name — provenance always visible (§9.1)
    stale: bool = False  # degraded provider; consumers must see it (§13)

    @model_validator(mode="after")
    def _validate(self) -> BarSeries:
        if self.timeframe not in TIMEFRAME_SECONDS:
            raise ValueError(f"unknown timeframe {self.timeframe!r}; known: {[*TIMEFRAME_SECONDS]}")
        opens = [b.ts_open for b in self.bars]
        if opens != sorted(opens) or len(set(opens)) != len(opens):
            raise ValueError(
                "bars must be strictly ascending by ts_open — disorder becomes wrong grades"
            )
        return self


class Friction(FrozenModel):
    """One-side trading cost decomposition (TD-8)."""

    fee_usd: Decimal
    half_spread_usd: Decimal
    slippage_usd: Decimal
    total_usd: Decimal


class CriteriaOutcome(FrozenModel):
    """Pure grading-engine result (DESIGN §10.2) — becomes a Grade in P2.

    PENDING = horizon not reached and nothing triggered (grade sweep keeps
    the thesis active). `evaluated` stays a loose JSON list per the
    ASSUMPTIONS-10 pattern until the audit UI needs more.
    """

    result: Literal["PASS", "FAIL", "VOID", "PENDING"]
    triggered: Literal["success", "failure", "invalidation", "horizon_expiry"] | None = None
    trigger_ts: AwareDatetime | None = None  # ts_open of the deciding bar
    ambiguous_bar: bool = False  # >=2 categories in one bar; resolved against the agent
    evaluated: list[dict[str, Any]] = Field(default_factory=list)
