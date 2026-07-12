"""Policy/broker/grading/registry contracts (DESIGN §5.3).

Minimal field sets defensible from §5.3's table; they harden as their
producing subsystems land (P2/P3). Heterogeneous sub-structures (evaluated
predicates, snapshot context) stay plain JSON objects under the same
deferral ratified for event payloads (ASSUMPTIONS 10).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import AwareDatetime, Field

from tradekit.contracts._base import FrozenModel
from tradekit.contracts._thesis import AssetRef


class RuleHit(FrozenModel):
    rule_id: str  # stable forever (§7.2)
    outcome: Literal["pass", "fail"]
    measured: str | None = None  # rendered value — rule-dependent type, audit-facing
    limit: str | None = None  # the dial the measurement was held against


class Verdict(FrozenModel):
    verdict_id: str
    allow: bool
    rule_hits: list[RuleHit] = Field(default_factory=list)
    policy_version_hash: str  # verdicts reproducible historically (§13)


class VerdictToken(FrozenModel):
    # Proof-of-allow handed to broker adapters (§8.1): references the ledgered
    # Verdict, carries no authority of its own.
    verdict_id: str
    policy_version_hash: str


class ProposedAction(FrozenModel):
    kind: str  # "submit_order" | "cancel" | "promote" | "void" | ... (open set until P2)
    account_ref: str
    requested_by: str
    thesis_id: str | None = None
    order: OrderRequest | None = None


class OrderRequest(FrozenModel):
    thesis_id: str
    account_ref: str
    asset: AssetRef
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit", "stop", "stop_limit"]
    qty: Decimal
    limit_price: Decimal | None = None


class OrderAck(FrozenModel):
    order_id: str
    status: Literal["accepted", "rejected"]
    ts_utc: AwareDatetime
    venue_order_id: str | None = None


class Fill(FrozenModel):
    order_id: str
    thesis_id: str
    ts_utc: AwareDatetime
    price: Decimal
    qty: Decimal
    fees_usd: Decimal
    quote_snapshot: dict[str, Any] = Field(default_factory=dict)  # every fill auditable (§8.3)


class Grade(FrozenModel):
    thesis_id: str
    result: Literal["PASS", "FAIL", "VOID"]
    evaluated: list[dict[str, Any]]  # per-predicate measured values (§10.2)
    pnl_usd: Decimal  # net of fees, Decimal end-to-end (§10.3)
    ambiguous_bar: bool = False  # stop+target same bar → conservative stop-first (§10.2)


class MarketSnapshot(FrozenModel):
    snapshot_id: str
    ts_utc: AwareDatetime
    prices: dict[str, Decimal] = Field(default_factory=dict)
    regime: dict[str, Any] = Field(default_factory=dict)
    derivatives: dict[str, Any] = Field(default_factory=dict)
    correlations: dict[str, Any] = Field(default_factory=dict)


class RunManifest(FrozenModel):
    run_id: str
    model: str
    framework: str
    prompt: str  # verbatim (D15)
    prompt_sha256: str
    config_version: int
