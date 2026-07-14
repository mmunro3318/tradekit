"""JSON Schema export (DESIGN §5): typed contracts for non-Python agents (D9)."""

from __future__ import annotations

from typing import Any

from tradekit.contracts._base import FrozenModel
from tradekit.contracts._events import ChainReport, Event, EventFilter
from tradekit.contracts._execution import (
    Fill,
    Grade,
    MarketSnapshot,
    OrderAck,
    OrderRequest,
    ProposedAction,
    RuleHit,
    RunManifest,
    Verdict,
    VerdictToken,
)
from tradekit.contracts._marketdata import (
    Bar,
    BarSeries,
    CoinMarket,
    CriteriaOutcome,
    Friction,
    GlobalCrypto,
)
from tradekit.contracts._metrics import StrategyMetrics, TradeRecord
from tradekit.contracts._predicates import (
    MeasurableInvalidation,
    PriceClose,
    PriceTouch,
    StructuralInvalidation,
    TimeExpiry,
)
from tradekit.contracts._thesis import AssetRef, EntrySpec, EVBlock, ThesisContract

# Union aliases (Predicate, InvalidationSpec) export via their variants — each
# variant schema carries its `kind` discriminator, which is what a non-Python
# agent needs to author one.
_PUBLIC_MODELS: tuple[type[FrozenModel], ...] = (
    AssetRef,
    Bar,
    BarSeries,
    ChainReport,
    CoinMarket,
    CriteriaOutcome,
    Friction,
    EntrySpec,
    EVBlock,
    Event,
    EventFilter,
    Fill,
    GlobalCrypto,
    Grade,
    MarketSnapshot,
    MeasurableInvalidation,
    OrderAck,
    OrderRequest,
    PriceClose,
    PriceTouch,
    ProposedAction,
    RuleHit,
    RunManifest,
    StrategyMetrics,
    StructuralInvalidation,
    ThesisContract,
    TimeExpiry,
    TradeRecord,
    Verdict,
    VerdictToken,
)


def json_schemas() -> dict[str, dict[str, Any]]:
    """Model name -> JSON Schema, for `tk schema export` (§4.4)."""
    return {model.__name__: model.model_json_schema() for model in _PUBLIC_MODELS}
