"""ThesisContract and its component blocks (DESIGN §5.1; SME F1, F5, F6)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from tradekit.contracts._base import FrozenModel
from tradekit.contracts._predicates import InvalidationSpec, Predicate


class AssetRef(FrozenModel):
    symbol: str
    venue: str
    asset_class: str  # "equity" | "crypto" today; extensible enum (§17 P5 options)
    tick_size: Decimal  # drives quantize() at the MAE boundary (TD-23)


class EntrySpec(FrozenModel):
    order_type: Literal["market", "limit", "stop", "stop_limit"]
    limit_price: Decimal | None = None  # limit/trigger price where order_type needs one
    valid_until: datetime


class EVBlock(FrozenModel):
    # Numeric and mandatory (F5): prose where a number belongs must not validate.
    p_win: Decimal
    reward_usd: Decimal
    risk_usd: Decimal
    ev_usd: Decimal


class ThesisContract(FrozenModel):
    thesis_id: str  # ULID, assigned at draft
    schema_ver: int = 1
    account_ref: str  # "paper:alpha" | "live:alpaca" | "advisory:kraken" | ...
    asset: AssetRef
    direction: Literal["long", "short"]
    strategy_tag: str  # links to wiki strategy page + experiment registry
    rationale: str  # falsifiable catalyst, prose (reviewed, not graded)

    entry: EntrySpec
    horizon_end: datetime  # UTC; grading hard stop
    target_price: Decimal  # success predicate anchor
    stop_price: Decimal  # failure predicate anchor (price-based)
    invalidation: InvalidationSpec  # structural; separate from stop (F1)

    size_usd: Decimal  # from mae.size_position; R-012 closes the loop
    sizing_method: Literal["min_atr_kelly"]
    ev_block: EVBlock

    success_criteria: list[Predicate]
    failure_criteria: list[Predicate]
    market_snapshot_id: str  # decision-time snapshot event (D15), set at submit
    review_artifact_id: str | None = None  # set when adversarial review completes
