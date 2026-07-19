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
    Bar, BarSeries, TIMEFRAME_SECONDS        # market data (§9.1)
    Friction                                 # cost decomposition (TD-8)
    CriteriaOutcome                          # grading-engine result (§10.2)
    GlobalCrypto, CoinMarket                 # CoinGecko macro data (§9.1, not a port)
    json_schemas() -> dict[str, dict]   # JSON Schema export for non-Python agents

Note on payload models: per the CTO ratification of ASSUMPTIONS 10, the P0
envelope takes plain-dict payloads with taxonomy validation on ``type``;
typed per-event payload models land with their producing subsystems (P2/P3).

SPRINT P2 batch A additive surface (thesis-lifecycle payload models):
    ThesisDraftedPayload, ThesisSubmittedPayload, MarketSnapshotTakenPayload,
    SizingComputedPayload, ThesisApprovedPayload, ThesisRejectedPayload,
    ThesisActivatedPayload, ReviewCompletedPayload,
    InvalidationAttestedPayload, ThesisGradedPayload,
    GateViolationDetectedPayload, HaltSetPayload, HaltClearedPayload
    — producer-side: validate through the model, then
    ``model_dump(mode="json")`` into ``Event.payload`` (ASSUMPTIONS 10's
    ratified pattern). See ``_event_payloads.py`` and ``tests/ASSUMPTIONS.md``.
"""

from tradekit.contracts._bridge import PropPanelSnapshot, PropPositionRow, TicketReadback
from tradekit.contracts._event_payloads import (
    AccountCreatedPayload,
    ActionProposedPayload,
    ConfigChangedPayload,
    DemotedPayload,
    FillRecordedPayload,
    GateViolationDetectedPayload,
    HaltClearedPayload,
    HaltSetPayload,
    InvalidationAttestedPayload,
    LessonRecordedPayload,
    MarketSnapshotTakenPayload,
    OrderAckPayload,
    OrderCancelledPayload,
    OrderSubmittedPayload,
    PolicyVersionLoadedPayload,
    PromotionConfirmedPayload,
    PromotionGrantedPayload,
    ReconciliationRunPayload,
    ReviewCompletedPayload,
    SeriesClosedPayload,
    SizingComputedPayload,
    ThesisActivatedPayload,
    ThesisApprovedPayload,
    ThesisDraftedPayload,
    ThesisGradedPayload,
    ThesisRejectedPayload,
    ThesisSubmittedPayload,
    VerdictIssuedPayload,
)
from tradekit.contracts._events import ChainReport, Event, EventFilter
from tradekit.contracts._execution import (
    AccountConfig,
    AccountState,
    Fill,
    Grade,
    MarketSnapshot,
    OrderAck,
    OrderRequest,
    OrderStatus,
    Position,
    ProposedAction,
    RuleHit,
    RunManifest,
    Verdict,
    VerdictToken,
)
from tradekit.contracts._hud import AdvisoryTicket, GateResult, HudState, ScanReportEntry
from tradekit.contracts._marketdata import (
    TIMEFRAME_SECONDS,
    Bar,
    BarSeries,
    CoinMarket,
    CriteriaOutcome,
    Friction,
    GlobalCrypto,
)
from tradekit.contracts._metrics import StrategyMetrics, TradeRecord
from tradekit.contracts._predicates import InvalidationSpec, Predicate
from tradekit.contracts._prop import (
    EmpiricalTradeModel,
    ParametricTradeModel,
    PropSimResult,
    PropSimSpec,
    ScriptedTradeModel,
    TradeModel,
)
from tradekit.contracts._quantize import quantize
from tradekit.contracts._review import ReviewArtifact, Verification
from tradekit.contracts._schemas import json_schemas
from tradekit.contracts._thesis import AssetRef, EntrySpec, EVBlock, ThesisContract

__all__ = [
    "TIMEFRAME_SECONDS",
    "AccountConfig",
    "AccountCreatedPayload",
    "AccountState",
    "ActionProposedPayload",
    "AdvisoryTicket",
    "AssetRef",
    "Bar",
    "BarSeries",
    "ChainReport",
    "CoinMarket",
    "ConfigChangedPayload",
    "CriteriaOutcome",
    "DemotedPayload",
    "EVBlock",
    "EmpiricalTradeModel",
    "EntrySpec",
    "Event",
    "EventFilter",
    "Fill",
    "FillRecordedPayload",
    "Friction",
    "GateResult",
    "GateViolationDetectedPayload",
    "GlobalCrypto",
    "Grade",
    "HaltClearedPayload",
    "HaltSetPayload",
    "HudState",
    "InvalidationAttestedPayload",
    "InvalidationSpec",
    "LessonRecordedPayload",
    "MarketSnapshot",
    "MarketSnapshotTakenPayload",
    "OrderAck",
    "OrderAckPayload",
    "OrderCancelledPayload",
    "OrderRequest",
    "OrderStatus",
    "OrderSubmittedPayload",
    "ParametricTradeModel",
    "PolicyVersionLoadedPayload",
    "Position",
    "Predicate",
    "PromotionConfirmedPayload",
    "PromotionGrantedPayload",
    "PropPanelSnapshot",
    "PropPositionRow",
    "PropSimResult",
    "PropSimSpec",
    "ProposedAction",
    "ReconciliationRunPayload",
    "ReviewArtifact",
    "ReviewCompletedPayload",
    "RuleHit",
    "RunManifest",
    "ScanReportEntry",
    "ScriptedTradeModel",
    "SeriesClosedPayload",
    "SizingComputedPayload",
    "StrategyMetrics",
    "ThesisActivatedPayload",
    "ThesisApprovedPayload",
    "ThesisContract",
    "ThesisDraftedPayload",
    "ThesisGradedPayload",
    "ThesisRejectedPayload",
    "ThesisSubmittedPayload",
    "TicketReadback",
    "TradeModel",
    "TradeRecord",
    "Verdict",
    "VerdictIssuedPayload",
    "VerdictToken",
    "Verification",
    "json_schemas",
    "quantize",
]
