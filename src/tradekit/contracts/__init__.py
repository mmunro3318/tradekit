"""tradekit.contracts — shared leaf module (DESIGN §5, TD-3, TD-23).

The one module every other module may import; imports nothing from tradekit.
All cross-boundary payloads are frozen Pydantic v2 models; money/quantities
are Decimal; every float→Decimal conversion goes through ``quantize``.

Public surface (implemented in P0 M0.2):
    AssetRef, quantize
    Predicate (price_touch | price_close | time_expiry), InvalidationSpec
    ThesisContract, EntrySpec, EVBlock
    Event (envelope) + typed payload models (taxonomy DESIGN §6.3)
    EventFilter, ChainReport                 # ledger query/audit contracts
    ProposedAction, Verdict, VerdictToken, RuleHit
    OrderRequest, OrderAck, Fill, Grade, MarketSnapshot, RunManifest
    TradeRecord, StrategyMetrics             # trade-log evaluation (§9.4)
    json_schemas() -> dict[str, dict]   # JSON Schema export for non-Python agents

Note on payload models: per the CTO ratification of ASSUMPTIONS 10, the P0
envelope takes plain-dict payloads with taxonomy validation on ``type``;
typed per-event payload models land with their producing subsystems (P2/P3).
"""

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
from tradekit.contracts._metrics import StrategyMetrics, TradeRecord
from tradekit.contracts._predicates import InvalidationSpec, Predicate
from tradekit.contracts._quantize import quantize
from tradekit.contracts._schemas import json_schemas
from tradekit.contracts._thesis import AssetRef, EntrySpec, EVBlock, ThesisContract

__all__ = [
    "AssetRef",
    "ChainReport",
    "EVBlock",
    "EntrySpec",
    "Event",
    "EventFilter",
    "Fill",
    "Grade",
    "InvalidationSpec",
    "MarketSnapshot",
    "OrderAck",
    "OrderRequest",
    "Predicate",
    "ProposedAction",
    "RuleHit",
    "RunManifest",
    "StrategyMetrics",
    "ThesisContract",
    "TradeRecord",
    "Verdict",
    "VerdictToken",
    "json_schemas",
    "quantize",
]
