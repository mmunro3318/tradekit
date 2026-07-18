"""Policy/broker/grading/registry contracts (DESIGN §5.3).

Minimal field sets defensible from §5.3's table; they harden as their
producing subsystems land (P2/P3). Heterogeneous sub-structures (evaluated
predicates, snapshot context) stay plain JSON objects under the same
deferral ratified for event payloads (ASSUMPTIONS 10).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import AwareDatetime, Field, field_validator

from tradekit.contracts._base import FrozenModel
from tradekit.contracts._thesis import AssetRef


class RuleHit(FrozenModel):
    rule_id: str  # stable forever (§7.2)
    # "not_configured" (SPRINT P3 batch A, TD-24): a rule whose backing dial
    # is None (disabled) is still CONSULTED — it emits a hit so the audit
    # trail shows the rule ran, distinct from "pass" (a real check that
    # allowed) and "fail" (a real check that denied). The verdict's overall
    # allow/deny is unaffected by a not_configured hit (CTO addendum).
    outcome: Literal["pass", "fail", "not_configured"]
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
    # "accepted"/"rejected" — PaperBroker/ManualBroker's own submission-ack
    # vocabulary (§8.3/§8.4, unchanged). "open"/"filled"/"canceled" —
    # AlpacaBroker's ADDITIVE widening (SPRINT P4-PAPER batch A/B): its own
    # `submit()` echoes the venue's OWN order status (via ALPACA_STATUS_MAP,
    # `broker._alpaca`) rather than a fixed "accepted" literal, since the
    # POST /v2/orders response already carries a real, venue-observed
    # lifecycle status (e.g. "pending_new" -> our "open") that would
    # otherwise be silently discarded. Additive, backward compatible — every
    # existing "accepted"/"rejected" producer/consumer is unaffected.
    status: Literal["accepted", "open", "filled", "canceled", "rejected"]
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


# ---------------------------------------------------------------------------
# SPRINT P3 batch A — BrokerPort contracts (DESIGN §8.1) + TD-24 AccountConfig.
# ---------------------------------------------------------------------------


class AccountState(FrozenModel):
    """`BrokerPort.account()`'s return shape (§8.1): "equity, settled cash,
    buying power". `Decimal` end-to-end — every field here is money."""

    account_ref: str
    equity_usd: Decimal
    settled_cash_usd: Decimal
    buying_power_usd: Decimal


class Position(FrozenModel):
    """One row of `BrokerPort.positions()` (§8.1). `market_value_usd` is
    `None` when no live quote is available to mark it (e.g. a stale/absent
    cache entry) — never a fabricated value."""

    account_ref: str
    symbol: str
    qty: Decimal
    avg_price: Decimal
    market_value_usd: Decimal | None = None


class OrderStatus(FrozenModel):
    """`BrokerPort.order_status(order_id)`'s return shape (§8.1)."""

    order_id: str
    status: Literal["open", "partially_filled", "filled", "canceled", "rejected"]
    filled_qty: Decimal = Decimal("0")
    remaining_qty: Decimal | None = None


class AccountConfig(FrozenModel):
    """Per-account dial overrides (TD-24, Mike-signed 2026-07-17). `None` on
    any of the four optional gates below means the corresponding rule
    (R-017/R-018; `max_daily_profit`/`consistency_rule` are accepted slots
    with NO enforcing rule in P3) is DISABLED for this account — never
    `+/-Infinity`, and never silently treated as "no context" (the rule
    still runs and emits a `RuleHit(outcome="not_configured")`, ASSUMPTIONS
    round-16).

    `principal_usd` is quantized to whole cents (2dp) — money is Decimal
    end-to-end (TD-3) and a sub-cent principal is not a real dollar amount
    a broker could ever hold; more than 2 fractional digits is a
    `ValidationError`, not a silent round (an agent-authored config file
    with a typo'd principal must die at construction, not misprice every
    dial that scales off it)."""

    account_ref: str
    principal_usd: Decimal
    max_trades_per_day: int = Field(ge=0)
    max_daily_drawdown: Decimal | None = None  # fraction of principal, None = disabled
    max_lifetime_drawdown: Decimal | None = None  # fraction of principal, None = disabled
    max_daily_profit: Decimal | None = None  # accepted slot, NO enforcing rule in P3
    consistency_rule: str | None = None  # opaque; accepted slot, NO enforcing rule in P3

    @field_validator("principal_usd")
    @classmethod
    def _principal_at_most_two_decimal_places(cls, v: Decimal) -> Decimal:
        exponent = v.as_tuple().exponent
        # `exponent` is an int for a finite Decimal (never the 'n'/'F'/'N'
        # special-value string here — AwareDatetime-style special values
        # don't apply to plain Decimal); more negative than -2 means more
        # than 2 fractional digits, e.g. Decimal("1.005") -> exponent -3.
        if isinstance(exponent, int) and exponent < -2:
            raise ValueError(
                f"principal_usd={v} carries more than 2 decimal places — money is "
                "quantized to whole cents (TD-3)"
            )
        return v

    @field_validator("max_daily_drawdown", "max_lifetime_drawdown", "max_daily_profit")
    @classmethod
    def _fraction_dials_are_non_negative(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v < 0:
            raise ValueError(f"fraction dial {v} must be >= 0 (None disables it, not negative)")
        return v
