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

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from tradekit.contracts import Event, EventFilter, ProposedAction
from tradekit.ledger import Ledger, default_ledger
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


# Ambient "now" seam — `policy` may import NEITHER `mae` nor `thesis`
# internals (CTO addendum, story-3 pins: "policy touches NONE" of mae; the
# hard rule extends to thesis too), so it cannot reach `mae._runtime.clock`.
# This is `policy`'s OWN private clock indirection, same shape/rationale as
# `mae._runtime._clock` (SPRINT-P1C addendum) — tests monkeypatch
# `"tradekit.policy._context._clock"` by dotted string path, never `clock()`
# itself, so the public function keeps its real body under test.
def _default_clock() -> datetime:
    return datetime.now(UTC)


_clock: Callable[[], datetime] = _default_clock


def clock() -> datetime:
    """Aware-UTC "now" via the `_clock` seam."""
    return _clock()


def _events_for_thesis(ledger: Ledger, event_type: str, thesis_id: str) -> list[Event]:
    return [
        event
        for event in ledger.query(EventFilter(types=[event_type]))
        if event.payload.get("thesis_id") == thesis_id
    ]


def _latest_payload_for_thesis(
    ledger: Ledger, event_type: str, thesis_id: str, **payload_match: Any
) -> dict[str, Any] | None:
    matches = [
        event
        for event in _events_for_thesis(ledger, event_type, thesis_id)
        if all(event.payload.get(k) == v for k, v in payload_match.items())
    ]
    return matches[-1].payload if matches else None


def _halt_state(ledger: Ledger) -> tuple[bool, str | None]:
    """Fold every `HaltSet`/`HaltCleared` event, in ledger (append) order,
    into the CURRENT halt state — the last one wins, exactly "unresolved
    HaltSet/HaltCleared pairs" (task pin)."""
    halted = False
    reason: str | None = None
    for event in ledger.query(EventFilter(types=["HaltSet", "HaltCleared"])):
        if event.type == "HaltSet":
            halted = True
            reason = event.payload.get("reason")
        else:  # HaltCleared
            halted = False
            reason = None
    return halted, reason


def _account_tier(account_ref: str) -> Literal["T0", "T1", "T2"] | None:
    """MVP tier-by-construction (P2 has no `promotion_state` projection
    yet, batch D): a `"paper:"` account_ref can only exist at T1 (the
    promotion ladder's own diagram: T0 research -> T1 paper -> T2 live —
    trading paper AT ALL implies the T1 grant already happened), an
    `"advisory:"` account_ref is T0 research/manual. A `"live:"`
    account_ref's real tier lives in `promotion_state` (unwired this
    batch) -> `None` -> R-002 correctly denies every live action until
    batch D, same anti-permissive shape as R-011's live-sequence budget."""
    if account_ref.startswith("paper:"):
        return "T1"
    if account_ref.startswith("advisory:"):
        return "T0"
    return None


def _paper_equity(dials: PolicyDials, account_ref: str) -> Decimal | None:
    """`paper_starting_equity_usd` + cumulative realized pnl for
    `account_ref` from `pnl_daily` (task pin) — `pnl_daily` has no real
    `FillRecorded` writer yet in P2 (ASSUMPTIONS 62: population deferred
    whole-cloth to batch B/D), so the cumulative term is always `0` this
    batch; this mirrors `thesis._submit.build_submit_payloads`'s OWN
    identical equity calc (`PolicyDials.load().paper_starting_equity_usd`,
    no pnl term either, same deferral). `None` for non-paper accounts — P2
    ships no live/advisory balance feed to derive a real settled balance
    from (anti-permissive: a guessed live balance is worse than denying)."""
    if not account_ref.startswith("paper:"):
        return None
    return dials.paper_starting_equity_usd


def _trades_today_count(ledger: Ledger, account_ref: str, now: datetime) -> int:
    """Count of this account's own `submit_order` `ActionProposed` events
    on `now`'s UTC calendar day — a real (possibly-zero) count, never a
    guess; a fresh ledger with no prior proposals today is genuinely `0`."""
    today = now.date()
    count = 0
    for event in ledger.query(EventFilter(types=["ActionProposed"])):
        if (
            event.payload.get("account_ref") == account_ref
            and event.payload.get("kind") == "submit_order"
            and event.ts_utc.astimezone(UTC).date() == today
        ):
            count += 1
    return count


def _trailing_drawdown_pct(
    ledger: Ledger, dials: PolicyDials, account_ref: str, now: datetime
) -> Decimal:
    """Peak-to-trough drawdown, as a positive fraction, over the trailing
    30 days' `ThesisGraded.pnl_usd` for theses whose `ThesisDrafted`
    contract carries this `account_ref` (`pnl_daily`'s own FillRecorded
    aggregation isn't wired yet — ASSUMPTIONS 62 — so this reads the
    grading events directly; behaviorally identical once `pnl_daily`
    lands, since both roll up the same underlying realized pnl). An
    account with no graded history in the window has a flat equity curve
    -> a GENUINELY COMPUTED `Decimal("0")`, never an assumed default (CTO
    addendum: "None => insufficient_context, never assumed 0" — this
    function never returns `None`, only a real computed fraction)."""
    cutoff = now - timedelta(days=30)
    thesis_ids = {
        event.payload.get("thesis_id")
        for event in ledger.query(EventFilter(types=["ThesisDrafted"]))
        if event.payload.get("contract", {}).get("account_ref") == account_ref
    }
    graded = sorted(
        (
            event
            for event in ledger.query(EventFilter(types=["ThesisGraded"]))
            if event.payload.get("thesis_id") in thesis_ids
            and event.ts_utc.astimezone(UTC) >= cutoff
            and event.ts_utc.astimezone(UTC) <= now
        ),
        key=lambda event: event.ts_utc,
    )
    equity = dials.paper_starting_equity_usd
    peak = equity
    max_drawdown = Decimal("0")
    for event in graded:
        pnl = event.payload.get("pnl_usd")
        if pnl is None:
            continue
        equity += Decimal(str(pnl))
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    return max_drawdown


def _thesis_prereqs(
    ledger: Ledger, thesis_id: str | None
) -> tuple[str | None, str | None, bool | None]:
    """`(review_artifact_id, market_snapshot_id, ev_ok)` for R-010.

    Real derivation off this thesis's own event log: `market_snapshot_id`
    and `ev_ok` come from its `ThesisSubmitted` marker (`thesis.submit`
    only ever appends that event AFTER EV validation passes within
    tolerance — ASSUMPTIONS/CTO addendum story-1 pins — so the marker's
    mere existence already proves `ev_ok`); `review_artifact_id` comes
    from its `ReviewCompleted(kind="thesis_review")` sign-off (P2 ships no
    review verb — tests append this as a harness action, same as
    `thesis.approve`'s own read of it).

    ANTI-PERMISSIVE, NO EXCEPTIONS (CTO adjudication, batch-C dev pass —
    an earlier draft carried a permissive fallback for a thesis_id with no
    ledger history at all; REJECTED: a fabricated/never-drafted thesis_id
    passing R-010/R-012 is exactly the gaming vector the policy engine
    exists to block, ASSUMPTIONS 25's spirit). Unknown/never-submitted
    thesis_id -> every field stays `None` -> R-010 denies with
    `insufficient_context`. The allow path must be EARNED by real
    `ThesisSubmitted`/`ReviewCompleted` events in the ledger."""
    if thesis_id is None:
        return None, None, None
    submitted = _latest_payload_for_thesis(ledger, "ThesisSubmitted", thesis_id)
    review = _latest_payload_for_thesis(
        ledger, "ReviewCompleted", thesis_id, kind="thesis_review"
    )
    market_snapshot_id = submitted.get("market_snapshot_id") if submitted else None
    # `thesis.submit` only ever appends the ThesisSubmitted marker AFTER EV
    # validation passes within tolerance (ASSUMPTIONS 65) — the marker's
    # existence IS the ev_ok proof; its absence is insufficient context.
    ev_ok = True if submitted is not None else None
    review_artifact_id = review.get("review_artifact_id") if review else None
    return review_artifact_id, market_snapshot_id, ev_ok


def _recorded_sizing(ledger: Ledger, action: ProposedAction) -> Decimal | None:
    """R-012's `recorded_sizing_usd` — the notional `SizingComputed`
    recorded verbatim at `thesis.submit` time, compared against the
    submitted order (F6, sizing purity).

    ANTI-PERMISSIVE, NO EXCEPTIONS (CTO adjudication, batch-C dev pass —
    same ruling as `_thesis_prereqs` above: an earlier draft fell back to
    the action's own order notional for a thesis with no `SizingComputed`
    on record, a zero-deviation no-op that let a fabricated thesis_id
    defeat sizing purity; REJECTED). No recorded `SizingComputed` for
    this thesis -> `None` -> R-012 denies with `insufficient_context`."""
    if action.thesis_id is None:
        return None
    sizing = _latest_payload_for_thesis(ledger, "SizingComputed", action.thesis_id)
    if sizing is None:
        return None
    recommended = sizing.get("sizing", {}).get("recommended_size_usd")
    if recommended is None:
        return None
    return Decimal(str(recommended))


def _thesis_age_hours(ledger: Ledger, thesis_id: str | None, now: datetime) -> Decimal | None:
    """R-014's advisory cooling-off clock: hours since `thesis_id`'s
    `ThesisSubmitted` marker. `None` when unknown (no submission on
    record) — R-014 only needs this for advisory orders above the
    notional threshold, where it is genuinely `insufficient_context`."""
    if thesis_id is None:
        return None
    submitted = _latest_payload_for_thesis(ledger, "ThesisSubmitted", thesis_id)
    if submitted is None:
        return None
    submitted_events = _events_for_thesis(ledger, "ThesisSubmitted", thesis_id)
    submitted_ts = submitted_events[-1].ts_utc.astimezone(UTC)
    delta = now.astimezone(UTC) - submitted_ts
    return Decimal(str(delta.total_seconds() / 3600.0))


def _trailing_graded_outcomes(
    ledger: Ledger, account_ref: str, window: int
) -> tuple[Literal["PASS", "FAIL", "VOID"], ...]:
    """R-015's trailing graded outcomes for `account_ref`, OLDEST first,
    capped at `window` (the dial), read off `ThesisGraded` events for
    theses whose `ThesisDrafted` contract carries this `account_ref`."""
    thesis_ids = {
        event.payload.get("thesis_id")
        for event in ledger.query(EventFilter(types=["ThesisDrafted"]))
        if event.payload.get("contract", {}).get("account_ref") == account_ref
    }
    graded = sorted(
        (
            event
            for event in ledger.query(EventFilter(types=["ThesisGraded"]))
            if event.payload.get("thesis_id") in thesis_ids
        ),
        key=lambda event: event.ts_utc,
    )
    outcomes = tuple(event.payload.get("outcome") for event in graded)
    trimmed = outcomes[-window:] if window > 0 else ()
    return trimmed  # type: ignore[return-value]


def assemble(action: ProposedAction, dials: PolicyDials) -> PolicyContext:
    """Read the ledger (via `ledger.default_ledger()`) and build the frozen
    `PolicyContext` snapshot `evaluate()` hands to the pure core.

    Halted state folds every unresolved `HaltSet`/`HaltCleared` pair;
    trailing graded outcomes and drawdown read `ThesisGraded` history;
    paper equity is `dials.paper_starting_equity_usd` (+ `pnl_daily`, once
    wired — ASSUMPTIONS 62); open positions/correlations are empty (P2
    ships no broker fill pipeline, DESIGN §7.1 vacuous-pass case);
    everything else missing gets the SAFE default enumerated per-field in
    the private helpers above (`tests/ASSUMPTIONS.md`'s batch-C entry 76
    enumerates the insufficient-context-vs-vacuous-pass split this
    function must honor)."""
    ledger = default_ledger()
    now = clock()

    halted, halt_reason = _halt_state(ledger)
    equity = _paper_equity(dials, action.account_ref)
    review_artifact_id, market_snapshot_id, ev_ok = _thesis_prereqs(ledger, action.thesis_id)

    return PolicyContext(
        now=now,
        dials=dials,
        halted=halted,
        halt_reason=halt_reason,
        account_tier=_account_tier(action.account_ref),
        settled_balance_usd=equity,
        account_equity_usd=equity,
        live_exposure_usd=Decimal("0"),
        trades_today_count=_trades_today_count(ledger, action.account_ref, now),
        trailing_30d_drawdown_pct=_trailing_drawdown_pct(ledger, dials, action.account_ref, now),
        thesis_review_artifact_id=review_artifact_id,
        thesis_market_snapshot_id=market_snapshot_id,
        thesis_ev_ok=ev_ok,
        live_trades_remaining=None,  # promotion_state unwired — batch D.
        recorded_sizing_usd=_recorded_sizing(ledger, action),
        open_position_correlations={},
        thesis_age_hours=_thesis_age_hours(ledger, action.thesis_id, now),
        trailing_graded_outcomes=_trailing_graded_outcomes(
            ledger, action.account_ref, dials.void_rate_window
        ),
        strategy_metrics=None,  # mae.compute_strategy_metrics wiring — batch D (entry 77).
    )


__all__ = ["PolicyContext", "assemble", "clock"]
