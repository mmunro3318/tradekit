"""tradekit.contracts — shared leaf module (DESIGN §5, TD-3, TD-23).

The one module every other module may import; imports nothing from tradekit.
All cross-boundary payloads are frozen Pydantic v2 models; money/quantities
are Decimal; every float→Decimal conversion goes through ``quantize``.

Public surface (implemented in P0 M0.2):
    AssetRef, quantize
    Predicate (price_touch | price_close | time_expiry), InvalidationSpec
    ThesisContract, EntrySpec, EVBlock
    Event (envelope) + typed payload models (taxonomy DESIGN §6.3)
    ProposedAction, Verdict, VerdictToken, RuleHit
    OrderRequest, OrderAck, Fill, Grade, MarketSnapshot, RunManifest
    json_schemas() -> dict[str, dict]   # JSON Schema export for non-Python agents
"""
