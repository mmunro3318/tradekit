"""Frozen policy-context snapshot (DESIGN §7.1; CTO addendum, story-3 pins).

`PolicyContext` (the SHAPE) is REAL this batch — `_rules.py`'s `check`
callables are typed against it and the per-rule allow/deny tests construct
synthetic instances directly, exactly the same "declarative data the tests
read" status as `_dials.PolicyDials`/`_rules.RULES` (CTO's batch-C red/green
split call). `assemble()` (the I/O-performing PROJECTIONS -> PolicyContext
reader) stays an unconditional `NotImplementedError` stub this batch — it is
one of the six-verbs-adjacent pieces the CTO pinned red (batch D's series/
promotion projections don't exist yet for it to read from anyway).

Anti-permissive default rule (CTO addendum, story-3 pins): "a rule must
never pass because data was missing." Every `PolicyContext` field a rule
NEEDS to render a real verdict is `| None`-typed with NO non-None default —
`assemble()` (once implemented) must set it explicitly from a projection, or
leave it `None`, and `_rules.py`'s per-rule `check` treats `None` on a
needed field as `insufficient_context` (deny), never a silent pass. Fields
that are legitimately EMPTY in P2 (no open positions yet, since P2 ships no
broker fill pipeline) default to their empty container (`{}`/`[]`/`0`) —
those are vacuous passes, not missing data; see `tests/ASSUMPTIONS.md`'s
batch-C entry enumerating the split per rule.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from tradekit.contracts import ProposedAction
from tradekit.policy._dials import PolicyDials


class PolicyContext(BaseModel):
    """Everything a rule's `check(action, ctx)` may read. Not built on
    `contracts.FrozenModel` — that base is a `contracts`-internal
    (TID251-banned outside `contracts`, DESIGN §1); `PolicyContext` is
    `policy`'s own leaf type, frozen the same way `FrozenModel` is.
    `arbitrary_types_allowed` lets `PolicyDials` (a `BaseSettings`, not a
    plain `BaseModel`) sit as a field like any other nested model."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    now: AwareDatetime
    dials: PolicyDials

    # R-001 — kill switch.
    halted: bool = False
    halt_reason: str | None = None

    # R-002 — promotion tier gating the account_ref this action targets.
    account_tier: Literal["T0", "T1", "T2"] | None = None

    # R-003 — settled balance incl. fees (None => insufficient_context for
    # any action that needs it, e.g. submit_order).
    settled_balance_usd: Decimal | None = None

    # R-005/R-006 — sizing context. `account_equity_usd` drives the paper
    # 10%-of-equity cap; `live_exposure_usd` is CURRENT open live notional
    # (0 is a legitimate "no live exposure yet" vacuous value, P2 MVP).
    account_equity_usd: Decimal | None = None
    live_exposure_usd: Decimal = Decimal("0")

    # R-007 — today's trade count for this account_ref (UTC calendar day).
    trades_today_count: int | None = None

    # R-009 — 30-day peak-to-trough drawdown, as a positive fraction
    # (0.10 == 10%). None => insufficient_context (never assumed 0).
    trailing_30d_drawdown_pct: Decimal | None = None

    # R-010 — thesis prerequisites, read off the referenced thesis's own
    # contract + submit-time state (assembled from `theses`/event log).
    thesis_review_artifact_id: str | None = None
    thesis_market_snapshot_id: str | None = None
    thesis_ev_ok: bool | None = None

    # R-011 — live-sequence budget remaining after a T2 promotion (None
    # until story 4 lands a promotion_state projection to read it from).
    live_trades_remaining: int | None = None

    # R-012 — sizing purity: the notional `mae.size_position` recorded for
    # THIS thesis at submit time (SizingComputed, verbatim).
    recorded_sizing_usd: Decimal | None = None

    # R-013 — |correlation| of the candidate symbol to each OPEN position,
    # from `mae.get_correlation_matrix` (assembled by `assemble()`, never
    # computed inside a rule's `check` — evaluate() stays pure). Empty dict
    # is the legitimate "no open positions" vacuous case, not missing data.
    open_position_correlations: dict[str, Decimal] = Field(default_factory=dict)

    # R-014 — advisory cooling-off: age of the REFERENCED thesis since its
    # ThesisSubmitted marker. None => insufficient_context for any advisory
    # action above the notional threshold.
    thesis_age_hours: Decimal | None = None

    # R-015 — trailing graded outcomes for this account_ref, OLDEST first,
    # capped at the dial's window by whoever assembles this (empty list is
    # the legitimate "nothing graded yet" vacuous case).
    trailing_graded_outcomes: tuple[Literal["PASS", "FAIL", "VOID"], ...] = ()

    # R-016 — stubbed strategy-metrics summary (FLAGGED SEAM: real
    # `mae.compute_strategy_metrics` wiring is batch D's job, CTO addendum
    # story-3 pins — this field exists so R-016 is unit-testable NOW against
    # a synthetic summary shaped like `contracts.StrategyMetrics`'s
    # promotion-relevant subset). None => insufficient_context.
    strategy_metrics: dict[str, Any] | None = None


def assemble(action: ProposedAction, dials: PolicyDials) -> PolicyContext:
    """Read `theses`/`series`/`promotion_state`/`pnl_daily` projections
    (via `ledger.default_ledger()`) and `mae.get_correlation_matrix` for
    `action`'s open positions, and build the frozen snapshot `evaluate()`
    hands to the pure core. STUB this batch (CTO's batch-C red/green split:
    "_context ... stay stubs -> red") — batch D's projections don't exist
    yet for this to read."""
    raise NotImplementedError(
        "P2 batch D — docs/handoff/SPRINT-P2-thesis-policy.md story 3/4; "
        "assembles PolicyContext from projections + mae.get_correlation_matrix"
    )


__all__ = ["PolicyContext", "assemble"]
