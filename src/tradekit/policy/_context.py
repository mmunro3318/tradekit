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

from tradekit import mae
from tradekit.contracts import Event, EventFilter, ProposedAction, StrategyMetrics, TradeRecord
from tradekit.ledger import Ledger, default_ledger
from tradekit.policy._dials import PolicyDials, resolve_account_dial


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

    # R-005 (live)/R-006/R-014/R-017/R-018 (SPRINT P3 batch A, TD-24) — the
    # targeted account's AccountConfig.principal_usd, resolved by
    # `assemble()` from the ledgered `AccountCreated` event (or, for P2's
    # default account with no explicit AccountConfig on record, synthesized
    # from `dials.paper_starting_equity_usd` — the addendum's "implicit
    # AccountConfig from config.toml defaults"). None => insufficient_context
    # for any rule that needs it (never a guessed principal).
    account_principal_usd: Decimal | None = None

    # R-017/R-018 — the RESOLVED per-account dial (AccountConfig field ->
    # PolicyDials default -> code default, `_dials.resolve_account_dial`).
    # `None` is a legitimate resolved value meaning "disabled for this
    # account" -> the rule emits `not_configured`, never insufficient_context
    # (disabled is a real, deliberate answer, not missing data).
    account_max_daily_drawdown: Decimal | None = None
    account_max_lifetime_drawdown: Decimal | None = None

    # R-017 — today's realized pnl as a FRACTION of account principal (UTC
    # calendar day, `pnl_daily`-equivalent aggregation). Signed: negative on
    # a losing day. None => insufficient_context (never assumed 0 — same
    # anti-permissive discipline as `trailing_30d_drawdown_pct`).
    daily_pnl_fraction: Decimal | None = None

    # R-018 — lifetime peak-to-trough drawdown as a FRACTION of principal,
    # over the account's full graded history (no 30-day window, unlike
    # `trailing_30d_drawdown_pct`). None => insufficient_context.
    lifetime_drawdown_fraction: Decimal | None = None


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


def _account_tier(ledger: Ledger, account_ref: str) -> Literal["T0", "T1", "T2"] | None:
    """MVP tier-by-construction: a `"paper:"` account_ref can only exist at
    T1 (the promotion ladder's own diagram: T0 research -> T1 paper -> T2
    live — trading paper AT ALL implies the T1 grant already happened), an
    `"advisory:"` account_ref is T0 research/manual.

    A `"live:"` account_ref's real tier lives in the `promotion_state`
    projection (SPRINT P3 batch C, ASSUMPTIONS round-18 — ends the P2
    fail-closed carve-out, ASSUMPTIONS 92). REUSE, not duplicate (CTO
    adjudication): `policy.__init__._current_tier` already derives
    `(tier, live_sequence_remaining, last_confirmed_event)` off
    `PromotionConfirmed`/`Demoted` history — imported here via a deferred
    `from tradekit import policy` (module-attribute call, called only at
    function-call time, never at import time, to avoid the
    `policy.__init__` <-> `policy._context` import cycle: `__init__.py`
    itself imports `_context` at module scope). Only a T2 result is ever
    surfaced here — `_current_tier`'s own `_base_tier` fallback (T0/T1) for
    an unconfirmed or since-demoted "live:" ref is deliberately collapsed
    to `None`: the fail-closed default for R-002 remains for any "live:"
    account_ref that has not EARNED a currently-live T2 confirmation, same
    anti-permissive discipline as R-011's live-sequence budget below."""
    if account_ref.startswith("paper:"):
        return "T1"
    if account_ref.startswith("advisory:"):
        return "T0"
    if account_ref.startswith("live:"):
        from tradekit import policy as _policy

        tier, _remaining, _last_confirmed = _policy._current_tier(ledger, account_ref)
        return tier if tier == "T2" else None
    return None


def _live_trades_remaining(ledger: Ledger, account_ref: str) -> int | None:
    """R-011's `live_trades_remaining` — SPRINT P3 batch C, ASSUMPTIONS
    round-18: a PURE derivation, never a ledgered decrement event (no new
    event type). `None` for a non-"live:" account_ref, or a "live:" ref
    with no CURRENT T2 confirmation (unconfirmed, or since-demoted — same
    fail-closed shape as `_account_tier` above; reuses the SAME
    `policy._current_tier` call, deferred-imported to dodge the same
    import cycle).

    For a currently-confirmed T2 account: `PromotionConfirmed.
    live_sequence_remaining` (the budget AT confirmation, always 3) MINUS
    the count of this account's own `FillRecorded` events at OR AFTER that
    `PromotionConfirmed`'s own `ts_utc` — a fill from a PRIOR confirmation
    cycle (before the current one) never counts against the current
    budget."""
    if not account_ref.startswith("live:"):
        return None
    from tradekit import policy as _policy

    tier, _remaining, last_confirmed = _policy._current_tier(ledger, account_ref)
    if tier != "T2" or last_confirmed is None:
        return None
    budget = last_confirmed.payload.get("live_sequence_remaining")
    if budget is None:
        return None
    since_ts = last_confirmed.ts_utc.astimezone(UTC)
    fill_count = sum(
        1
        for event in ledger.query(EventFilter(types=["FillRecorded"]))
        if event.payload.get("account_ref") == account_ref
        and event.ts_utc.astimezone(UTC) >= since_ts
    )
    return int(budget) - fill_count


def _confirmed_live_t2(ledger: Ledger, account_ref: str) -> bool:
    """True iff `account_ref` is a `"live:"` ref that is CURRENTLY T2
    (confirmed and not since demoted) — SPRINT P3 batch C, ASSUMPTIONS
    round-18: `broker.get` now routes `"live:"` refs through the SAME
    `PaperBroker` simulation `"paper:"` refs use (no real venue adapter
    lands before batch D), so a confirmed-T2 live account settles against
    the SAME `dials.paper_starting_equity_usd` sandbox balance a paper
    account does — the P2 "no live/advisory balance feed" deferral's own
    premise (`"no P2 producer ever moves an account to live:"`) no longer
    holds once `policy.confirm_promotion` is a real producer (batch D).
    Reuses `_account_tier` (itself reusing `policy._current_tier`) rather
    than re-deriving confirmation state a third way."""
    return account_ref.startswith("live:") and _account_tier(ledger, account_ref) == "T2"


def _paper_equity(ledger: Ledger, dials: PolicyDials, account_ref: str) -> Decimal | None:
    """`paper_starting_equity_usd` + cumulative realized pnl for
    `account_ref` from `pnl_daily` (task pin) — `pnl_daily` has no real
    `FillRecorded` writer yet in P2 (ASSUMPTIONS 62: population deferred
    whole-cloth to batch B/D), so the cumulative term is always `0` this
    batch; this mirrors `thesis._submit.build_submit_payloads`'s OWN
    identical equity calc (`PolicyDials.load().paper_starting_equity_usd`,
    no pnl term either, same deferral). `None` for a non-paper, non-
    confirmed-live-T2 account — P2 ships no live/advisory balance feed to
    derive a real settled balance from (anti-permissive: a guessed live
    balance is worse than denying); a CONFIRMED T2 `"live:"` account is the
    SPRINT P3 batch C exception (see `_confirmed_live_t2` above)."""
    if account_ref.startswith("paper:") or _confirmed_live_t2(ledger, account_ref):
        return dials.paper_starting_equity_usd
    return None


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


def _account_config(ledger: Ledger, account_ref: str) -> dict[str, Any] | None:
    """Latest `AccountCreated.config` payload for `account_ref` (TD-24), or
    `None` when no such event has ever been ledgered."""
    matches = [
        event.payload.get("config")
        for event in ledger.query(EventFilter(types=["AccountCreated"]))
        if event.payload.get("account_ref") == account_ref
    ]
    return matches[-1] if matches else None


def _account_principal(ledger: Ledger, dials: PolicyDials, account_ref: str) -> Decimal | None:
    """R-005(live)/R-006/R-014/R-017/R-018's `account_principal_usd` (TD-24).
    A real `AccountCreated` event wins when present; P2's default account
    (`dials.default_account_ref`, "paper:alpha") gets the addendum's
    "implicit AccountConfig from config.toml defaults" — its principal is
    `dials.paper_starting_equity_usd` even with no `AccountCreated` event on
    record. Any other account with no `AccountCreated` event -> `None`
    (insufficient_context, never a guessed principal). SPRINT P3 batch C
    exception (ASSUMPTIONS round-18): a CONFIRMED T2 `"live:"` account with
    no explicit `AccountConfig` also gets the same implicit-default
    treatment as the default paper account (`_confirmed_live_t2` above) —
    `broker.get` now routes `"live:"` refs through the SAME `PaperBroker`
    sandbox `"paper:"` refs use, so a live account with no real venue
    principal on record settles against the identical sandbox balance."""
    config = _account_config(ledger, account_ref)
    if config is not None:
        principal = config.get("principal_usd")
        return Decimal(str(principal)) if principal is not None else None
    if account_ref == dials.default_account_ref or _confirmed_live_t2(ledger, account_ref):
        return dials.paper_starting_equity_usd
    return None


def _account_drawdown_dial(
    ledger: Ledger, dials: PolicyDials, account_ref: str, field: str, dial_default: Decimal | None
) -> Decimal | None:
    """R-017/R-018's resolved dial: AccountConfig field -> PolicyDials
    config.toml/code default (`_dials.resolve_account_dial`, TD-24's
    three-layer order)."""
    config = _account_config(ledger, account_ref)
    account_value_raw = config.get(field) if config is not None else None
    account_value = Decimal(str(account_value_raw)) if account_value_raw is not None else None
    return resolve_account_dial(account_value, dial_default)


def _daily_pnl_fraction(
    ledger: Ledger, account_ref: str, principal: Decimal | None, now: datetime
) -> Decimal | None:
    """R-017's today's-realized-pnl fraction of principal (UTC calendar
    day). `None` only when `principal` itself is unknown (propagated
    insufficient_context); a real day with no grades yet is a GENUINELY
    COMPUTED `Decimal("0")` (same discipline as `_trailing_drawdown_pct`'s
    own "no graded history -> real 0, never assumed" rule)."""
    if principal is None or principal == 0:
        return None
    thesis_ids = _account_thesis_ids(ledger, account_ref)
    today = now.date()
    total = Decimal("0")
    for event in ledger.query(EventFilter(types=["ThesisGraded"])):
        if event.payload.get("thesis_id") not in thesis_ids:
            continue
        graded_ts = _parse_graded_ts_for_context(event)
        if graded_ts.astimezone(UTC).date() != today:
            continue
        pnl = event.payload.get("pnl_usd")
        if pnl is not None:
            total += Decimal(str(pnl))
    return total / principal


def _lifetime_drawdown_fraction(
    ledger: Ledger, account_ref: str, principal: Decimal | None, now: datetime
) -> Decimal | None:
    """R-018's lifetime peak-to-trough drawdown, as a FRACTION OF PRINCIPAL
    (deliberately not "of peak equity" like R-009's `trailing_30d_drawdown_pct`
    — TD-24's own wording is "vs principal"; FLAGGED ambiguity, see
    tests/ASSUMPTIONS.md round-16). `None` only when `principal` is unknown."""
    if principal is None or principal == 0:
        return None
    thesis_ids = _account_thesis_ids(ledger, account_ref)
    graded = sorted(
        (
            event
            for event in ledger.query(EventFilter(types=["ThesisGraded"]))
            if event.payload.get("thesis_id") in thesis_ids
            and _parse_graded_ts_for_context(event) <= now
        ),
        key=_parse_graded_ts_for_context,
    )
    equity = principal
    peak = equity
    max_drawdown = Decimal("0")
    for event in graded:
        pnl = event.payload.get("pnl_usd")
        if pnl is None:
            continue
        equity += Decimal(str(pnl))
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / principal)
    return max_drawdown


def _parse_graded_ts_for_context(event: Event) -> datetime:
    raw = event.payload.get("graded_ts")
    if raw:
        ts = datetime.fromisoformat(str(raw))
        return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)
    return event.ts_utc


def _latest_thesis_review(ledger: Ledger, thesis_id: str) -> dict[str, Any] | None:
    """Latest `ReviewCompleted(kind="thesis_review")` payload for
    `thesis_id` — a missing `kind` key defaults to `"thesis_review"`, the
    SAME default `ReviewCompletedPayload` itself carries and
    `thesis._machine._next_state` already applies
    (`event.payload.get("kind", "thesis_review")`) when folding state; a
    harness-built raw-dict `ReviewCompleted` event (no payload model, no
    default merge) must resolve identically here, not be silently treated
    as insufficient_context just because the dict omitted the field its own
    typed payload would have defaulted in."""
    matches = [
        event
        for event in _events_for_thesis(ledger, "ReviewCompleted", thesis_id)
        if event.payload.get("kind", "thesis_review") == "thesis_review"
    ]
    return matches[-1].payload if matches else None


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
    review = _latest_thesis_review(ledger, thesis_id)
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


def _account_thesis_ids(ledger: Ledger, account_ref: str) -> set[str]:
    return {
        str(event.payload.get("thesis_id"))
        for event in ledger.query(EventFilter(types=["ThesisDrafted"]))
        if event.payload.get("contract", {}).get("account_ref") == account_ref
    }


def _thesis_entry_ts(ledger: Ledger, thesis_id: str) -> datetime | None:
    """Real ledger timestamp marking this thesis's entry into the market —
    `ThesisActivated` if present (the actual broker-fill trigger, P3), else
    `ThesisSubmitted` (the earliest moment a real order was even proposed).
    `None` when neither exists (never fabricated)."""
    activated = _events_for_thesis(ledger, "ThesisActivated", thesis_id)
    if activated:
        return activated[-1].ts_utc.astimezone(UTC)
    submitted = _events_for_thesis(ledger, "ThesisSubmitted", thesis_id)
    if submitted:
        return submitted[-1].ts_utc.astimezone(UTC)
    return None


def _trade_log_for_account(ledger: Ledger, account_ref: str) -> list[TradeRecord]:
    """Derive a `TradeRecord` log from graded non-void, with-pnl theses for
    `account_ref` (CTO addendum's story-4 pin: "over the account's graded
    non-void with-pnl theses").

    FLAGGED (ASSUMPTIONS 90): P2 events carry no per-fill entry/exit PRICE
    data (that lives on `FillRecorded`, whose own trade-log derivation is
    explicitly out of scope this batch) — `entry_price`/`exit_price` here are
    a numeraire-100 reconstruction solved algebraically so
    `_metrics._pnl(record) == the real ledgered pnl_usd` EXACTLY, using only
    real facts already in the ledger (`pnl_usd`, `SizingComputed`'s recorded
    notional, the thesis contract's own `direction`, and real event
    timestamps) — no market price is invented, only an accounting unit. A
    thesis missing `SizingComputed` or any entry-marker event is skipped
    rather than guessed (anti-fabrication, same discipline as
    `_recorded_sizing`/`_thesis_prereqs` above)."""
    thesis_ids = _account_thesis_ids(ledger, account_ref)
    trades: list[TradeRecord] = []
    for event in ledger.query(EventFilter(types=["ThesisGraded"])):
        thesis_id = event.payload.get("thesis_id")
        if thesis_id not in thesis_ids:
            continue
        if event.payload.get("outcome") not in ("PASS", "FAIL"):
            continue
        pnl = event.payload.get("pnl_usd")
        if pnl is None:
            continue
        pnl_dec = Decimal(str(pnl))

        drafted = _latest_payload_for_thesis(ledger, "ThesisDrafted", thesis_id)
        side = (drafted or {}).get("contract", {}).get("direction", "long")
        if side not in ("long", "short"):
            side = "long"

        sizing = _latest_payload_for_thesis(ledger, "SizingComputed", thesis_id)
        recommended = sizing.get("sizing", {}).get("recommended_size_usd") if sizing else None
        size = Decimal(str(recommended)) if recommended is not None else None
        if size is None or size <= 0:
            continue

        entry_ts = _thesis_entry_ts(ledger, thesis_id)
        graded_ts_raw = event.payload.get("graded_ts")
        exit_ts = (
            datetime.fromisoformat(graded_ts_raw) if graded_ts_raw else event.ts_utc
        ).astimezone(UTC)
        if entry_ts is None or exit_ts <= entry_ts:
            continue

        entry_price = Decimal("100")
        direction = Decimal(1) if side == "long" else Decimal(-1)
        exit_price = entry_price + (pnl_dec * entry_price) / (direction * size)
        if exit_price <= 0:
            continue

        trades.append(
            TradeRecord(
                entry_ts=entry_ts,
                exit_ts=exit_ts,
                entry_price=entry_price,
                exit_price=exit_price,
                side=side,
                size_usd=size,
                fees_usd=Decimal("0"),
            )
        )
    return trades


def strategy_metrics_for_account(
    ledger: Ledger, account_ref: str, dials: PolicyDials
) -> StrategyMetrics | None:
    """R-016's real metrics wiring (ASSUMPTIONS 77's forward pin) — calls
    the PUBLIC `tradekit.mae.compute_strategy_metrics` verb (module-attribute
    call, `mae.compute_strategy_metrics(...)`, never a `from ... import`, so
    tests can monkeypatch the dotted path `"tradekit.mae.
    compute_strategy_metrics"`) over `_trade_log_for_account`'s derivation.
    `None` when there is no trade log to evaluate yet (insufficient_context,
    never a fabricated verdict) — the call to `mae.compute_strategy_metrics`
    always happens (never short-circuited on an empty trade log BEFORE the
    call) so a monkeypatched seam is always exercised; only the REAL
    implementation's `ValueError` on an empty log is caught here."""
    trade_log = _trade_log_for_account(ledger, account_ref)
    try:
        return mae.compute_strategy_metrics(
            trade_log,
            n_trials=dials.n_trials_default,
            base_equity_usd=dials.paper_starting_equity_usd,
        )
    except ValueError:
        return None


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
    equity = _paper_equity(ledger, dials, action.account_ref)
    review_artifact_id, market_snapshot_id, ev_ok = _thesis_prereqs(ledger, action.thesis_id)

    strategy_metrics: dict[str, Any] | None = None
    if action.kind == "promote":
        # R-016 rewire (ASSUMPTIONS 77's forward pin, batch D): real
        # mae.compute_strategy_metrics over the account's own graded
        # non-void with-pnl theses — batch C's hardcoded `strategy_metrics=
        # None` placeholder is retired. `passes_gates` stays a REAL derived
        # key (edge_verdict == "positive", ASSUMPTIONS 89) alongside the
        # full StrategyMetrics dump, so `_rules._check_r016` (unit-tested
        # directly against hand-built contexts in test_rules.py) needs no
        # change — it reads a real boolean now, not a synthetic stand-in.
        metrics = strategy_metrics_for_account(ledger, action.account_ref, dials)
        if metrics is not None:
            dumped = metrics.model_dump(mode="json")
            dumped["passes_gates"] = metrics.edge_verdict == "positive"
            strategy_metrics = dumped

    principal = _account_principal(ledger, dials, action.account_ref)
    max_daily_dd = _account_drawdown_dial(
        ledger, dials, action.account_ref, "max_daily_drawdown", dials.max_daily_drawdown_default
    )
    max_lifetime_dd = _account_drawdown_dial(
        ledger,
        dials,
        action.account_ref,
        "max_lifetime_drawdown",
        dials.max_lifetime_drawdown_default,
    )

    return PolicyContext(
        now=now,
        dials=dials,
        halted=halted,
        halt_reason=halt_reason,
        account_tier=_account_tier(ledger, action.account_ref),
        settled_balance_usd=equity,
        account_equity_usd=equity,
        live_exposure_usd=Decimal("0"),
        trades_today_count=_trades_today_count(ledger, action.account_ref, now),
        trailing_30d_drawdown_pct=_trailing_drawdown_pct(ledger, dials, action.account_ref, now),
        thesis_review_artifact_id=review_artifact_id,
        thesis_market_snapshot_id=market_snapshot_id,
        thesis_ev_ok=ev_ok,
        live_trades_remaining=_live_trades_remaining(ledger, action.account_ref),
        recorded_sizing_usd=_recorded_sizing(ledger, action),
        open_position_correlations={},
        thesis_age_hours=_thesis_age_hours(ledger, action.thesis_id, now),
        trailing_graded_outcomes=_trailing_graded_outcomes(
            ledger, action.account_ref, dials.void_rate_window
        ),
        strategy_metrics=strategy_metrics,
        account_principal_usd=principal,
        account_max_daily_drawdown=max_daily_dd,
        account_max_lifetime_drawdown=max_lifetime_dd,
        daily_pnl_fraction=_daily_pnl_fraction(ledger, action.account_ref, principal, now),
        lifetime_drawdown_fraction=_lifetime_drawdown_fraction(
            ledger, action.account_ref, principal, now
        ),
    )


__all__ = ["PolicyContext", "assemble", "clock", "strategy_metrics_for_account"]
