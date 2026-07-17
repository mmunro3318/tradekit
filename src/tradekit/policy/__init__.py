"""tradekit.policy — the gate engine (DESIGN §7, TD-5).

Deep interface: exactly six verbs, per the §4.2 pins. `evaluate(action)` is
the money-path gate (DESIGN §8.2); `status()` surfaces the current
policy-version + dials + halt state; `halt()`/`resume()` are the manual
kill switch (R-001); `promotion_status()`/`confirm_promotion()` are the
promotion ladder (§7.3, story 4 — batch D).

Status (SPRINT P2 batch C, CTO's red/green split call): `_dials.py` and
`_rules.py` are REAL this batch (declarative data, unit-tested directly —
see `tests/unit/policy/test_dials.py`/`test_rules.py`). All SIX verbs below
stay unconditional `NotImplementedError` stubs — same red-phase discipline
as `tradekit.thesis`'s batch-A pass (`tests/unit/policy/test_evaluate.py`/
`test_halt.py` assert the REAL expected behavior and are red for that
reason, not wrapped in `pytest.raises`).

Policy imports NOTHING from `broker` or `mae` (CTO addendum, story-3 pins:
"policy touches NONE" of mae internals) — R-013's correlations and R-016's
strategy metrics arrive pre-assembled inside `PolicyContext`, never fetched
by a rule's `check` or by these verbs directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from ulid import ULID

from tradekit.contracts import (
    ActionProposedPayload,
    ConfigChangedPayload,
    DemotedPayload,
    Event,
    EventFilter,
    GateViolationDetectedPayload,
    HaltClearedPayload,
    HaltSetPayload,
    PolicyVersionLoadedPayload,
    PromotionConfirmedPayload,
    PromotionGrantedPayload,
    ProposedAction,
    Verdict,
    VerdictIssuedPayload,
)
from tradekit.ledger import Ledger, default_ledger
from tradekit.policy import _context, _evaluate, _series
from tradekit.policy._dials import PolicyDials, canonical_dump, policy_version_hash
from tradekit.policy._rules import RULE_IDS, RULES, RULES_BY_ID


class PromotionRefused(Exception):
    """`confirm_promotion()`'s typed refusal (ASSUMPTIONS 88, additive
    export) — no unconsumed `PromotionGranted` event exists for
    `PolicyDials.default_account_ref`."""

# 'agent:<model>' | 'mike' | 'system:<job>' — every event this module
# produces is a machine-derived gate decision, not an LLM or human action.
_ACTOR = "system:policy"


def _append(ledger: Ledger, event_type: str, payload: dict[str, Any]) -> str:
    event = Event(
        event_id=str(ULID()),
        ts_utc=_context.clock(),
        type=event_type,  # type: ignore[arg-type]
        actor=_ACTOR,
        run_id=None,
        schema_ver=1,
        payload=payload,
    )
    return ledger.append(event)


def _ensure_policy_version(ledger: Ledger, dials: PolicyDials, version_hash: str) -> None:
    """First `evaluate()`/`status()` per process ensures a
    `PolicyVersionLoaded` event for the current hash; a hash different from
    the last one this ledger has recorded additionally appends
    `ConfigChanged` (CTO addendum, "Ambient wiring")."""
    loaded = ledger.query(EventFilter(types=["PolicyVersionLoaded"]))
    known_hashes = {event.payload.get("policy_version_hash") for event in loaded}
    if version_hash in known_hashes:
        return
    dials_dump = canonical_dump(dials)
    loaded_payload = PolicyVersionLoadedPayload(
        policy_version_hash=version_hash,
        rule_ids=sorted(RULE_IDS),
        dials=dials_dump,
    )
    _append(ledger, "PolicyVersionLoaded", loaded_payload.model_dump(mode="json"))
    if loaded:
        previous_hash = loaded[-1].payload.get("policy_version_hash")
        changed_payload = ConfigChangedPayload(
            previous_hash=previous_hash, new_hash=version_hash, dials=dials_dump
        )
        _append(ledger, "ConfigChanged", changed_payload.model_dump(mode="json"))


def evaluate(action: ProposedAction) -> Verdict:
    """Assemble a frozen `PolicyContext` (`_context.assemble`, MAY do I/O)
    -> run the PURE core (`_evaluate.evaluate_pure`) -> append
    `ActionProposed` + `VerdictIssued` (+ `GateViolationDetected` per
    denying rule hit) -> return the `Verdict`. Deny verdicts are NEVER
    silent (DESIGN §7.2)."""
    ledger = default_ledger()
    dials = PolicyDials.load()
    version_hash = policy_version_hash(dials, list(RULE_IDS))
    _ensure_policy_version(ledger, dials, version_hash)

    ctx = _context.assemble(action, dials)

    proposed_payload = ActionProposedPayload(
        kind=action.kind,
        account_ref=action.account_ref,
        requested_by=action.requested_by,
        thesis_id=action.thesis_id,
        order=action.order.model_dump(mode="json") if action.order is not None else None,
    )
    _append(ledger, "ActionProposed", proposed_payload.model_dump(mode="json"))

    verdict = _evaluate.evaluate_pure(action, ctx, version_hash, RULES)

    issued_payload = VerdictIssuedPayload(
        verdict_id=verdict.verdict_id,
        kind=action.kind,
        account_ref=action.account_ref,
        thesis_id=action.thesis_id,
        allow=verdict.allow,
        rule_hits=[hit.model_dump(mode="json") for hit in verdict.rule_hits],
        policy_version_hash=verdict.policy_version_hash,
    )
    _append(ledger, "VerdictIssued", issued_payload.model_dump(mode="json"))

    for hit in verdict.rule_hits:
        if hit.outcome != "fail":
            continue
        rule = RULES_BY_ID.get(hit.rule_id)
        violation_payload = GateViolationDetectedPayload(
            rule_id=hit.rule_id,
            account_ref=action.account_ref,
            thesis_id=action.thesis_id,
            measured=hit.measured,
            limit=hit.limit,
            why=rule.why if rule is not None else f"rule {hit.rule_id} denied this action",
        )
        _append(ledger, "GateViolationDetected", violation_payload.model_dump(mode="json"))

    return verdict


def status() -> dict[str, Any]:
    """`{policy_version_hash, halted, dials, rules}` snapshot (additive keys
    fine) — ensures a `PolicyVersionLoaded` event for the current hash on
    first call per process, plus `ConfigChanged` when the hash differs from
    the last recorded one (CTO addendum, "Ambient wiring")."""
    ledger = default_ledger()
    dials = PolicyDials.load()
    version_hash = policy_version_hash(dials, list(RULE_IDS))
    _ensure_policy_version(ledger, dials, version_hash)
    halted, halt_reason = _context._halt_state(ledger)
    return {
        "policy_version_hash": version_hash,
        "halted": halted,
        "halt_reason": halt_reason,
        "dials": canonical_dump(dials),
        "rules": [{"id": rule.id, "why": rule.why} for rule in RULES],
    }


def promotion_status() -> dict[str, Any]:
    """Series/promotion-ladder readiness snapshot (§7.3, story 4 — CTO
    addendum). Argless (the pinned §4.2 signature — FLAGGED, ASSUMPTIONS:
    the account it reports on is `PolicyDials.default_account_ref`, a P2 MVP
    single-account convention).

    Returns `{tier, current_series, last_4_series, t2_eligible,
    live_sequence_remaining}` — `t2_eligible` carries a per-criterion
    breakdown (3-of-4-clean / most-recent-clean / >=30 non-void /
    R-016 metrics gate).

    READ VERB THAT MAY WRITE (FLAGGED, ASSUMPTIONS — the CTO addendum's own
    proposal, offered as ratifiable rather than a dedicated
    `evaluate_promotion` verb, which would widen the six-verb surface):
    when every T1->T2 conjunct passes AND no unconsumed `PromotionGranted`
    event already exists for this account, this call appends EXACTLY ONE
    `PromotionGranted` event (idempotent — a second call with the same
    ledger state does not duplicate the grant). It also machine-evaluates
    demotion the SAME way (FLAGGED, ASSUMPTIONS): if the account is
    currently T2 and a demotion trigger (R-009 drawdown trip / a
    `GateViolationDetected` while T2 / a failed live grading) has occurred
    since the last `PromotionConfirmed`, this call appends `Demoted`.

    Batch D — dev pass implements this against `policy._series` +
    `mae.compute_strategy_metrics` (R-016 rewire, ASSUMPTIONS 77's forward
    pin) + the `promotion_state` projection."""
    ledger = default_ledger()
    dials = PolicyDials.load()
    account_ref = dials.default_account_ref
    now = _context.clock()
    epoch = dials.series_epoch

    current_idx = _series.series_index(now, epoch)
    evaluation_idx = _latest_graded_series_index(ledger, account_ref, epoch)
    if evaluation_idx is None:
        evaluation_idx = current_idx - 1
    last_4_indices = [
        evaluation_idx - 3,
        evaluation_idx - 2,
        evaluation_idx - 1,
        evaluation_idx,
    ]
    last_4_stats = [
        _series.series_stats(ledger, account_ref, idx, dials, now) for idx in last_4_indices
    ]

    clean_count = sum(1 for stats in last_4_stats if stats.clean)
    non_void_total = sum(stats.graded_count for stats in last_4_stats)

    metrics = _context.strategy_metrics_for_account(ledger, account_ref, dials)
    r016_pass = metrics is not None and metrics.edge_verdict == "positive"

    criteria = {
        "three_of_last_four_clean": clean_count >= 3,
        "most_recent_complete_clean": last_4_stats[-1].clean,
        "non_void_total_at_least_30": non_void_total >= 30,
        "r016_metrics_pass": r016_pass,
    }
    eligible = all(criteria.values())

    tier, live_remaining, last_confirmed = _current_tier(ledger, account_ref)

    if eligible and tier != "T2" and not _has_unconsumed_grant(ledger, account_ref):
        grant_payload = PromotionGrantedPayload(
            account_ref=account_ref, from_tier="T1", to_tier="T2", criteria=criteria
        )
        _append(ledger, "PromotionGranted", grant_payload.model_dump(mode="json"))

    if tier == "T2" and last_confirmed is not None:
        trigger = _demotion_trigger(ledger, account_ref, last_confirmed.ts_utc)
        if trigger is not None:
            kind, detail = trigger
            demoted_payload = DemotedPayload(
                account_ref=account_ref,
                from_tier="T2",
                to_tier="T1",
                trigger=kind,  # type: ignore[arg-type]
                detail=detail,
            )
            _append(ledger, "Demoted", demoted_payload.model_dump(mode="json"))
            tier = "T1"
            live_remaining = None

    current_series_stats = _series.series_stats(ledger, account_ref, current_idx, dials, now)

    return {
        "account_ref": account_ref,
        "tier": tier,
        "current_series": {
            "index": current_idx,
            "window": [
                current_series_stats.window_start.isoformat(),
                current_series_stats.window_end.isoformat(),
            ],
            "counts": {
                "graded": current_series_stats.graded_count,
                "void": current_series_stats.void_count,
            },
            "clean_so_far": current_series_stats.clean,
        },
        "last_4_series": [
            {
                "index": stats.series_index,
                "complete": stats.complete,
                "clean": stats.clean,
                "graded_count": stats.graded_count,
                "void_count": stats.void_count,
            }
            for stats in last_4_stats
        ],
        "t2_eligible": {"eligible": eligible, "criteria": criteria},
        "live_sequence_remaining": live_remaining,
    }


def _latest_graded_series_index(
    ledger: Ledger, account_ref: str, epoch: datetime
) -> int | None:
    """The highest series index this account has ANY `ThesisGraded` history
    in — the T1->T2 evaluation's own "most recent" series (CTO addendum:
    "the most recent (series 3) is one of the clean ones", i.e. the
    evaluation window is anchored to the account's own graded history, not
    to wall-clock "now" — a fresh account with no grading yet has no
    evaluation history at all). `None` when the account has never had a
    thesis graded."""
    thesis_ids = _series._account_thesis_ids(ledger, account_ref)
    indices = [
        _series.series_index(_series._graded_ts(event), epoch)
        for event in ledger.query(EventFilter(types=["ThesisGraded"]))
        if event.payload.get("thesis_id") in thesis_ids
    ]
    return max(indices) if indices else None


def _base_tier(account_ref: str) -> Literal["T0", "T1", "T2"]:
    """Pre-promotion baseline tier, same convention as `_context._account_
    tier`: a `"paper:"` account can only exist at T1 (trading paper at all
    implies the T1 grant already happened)."""
    if account_ref.startswith("paper:"):
        return "T1"
    return "T0"


def _current_tier(
    ledger: Ledger, account_ref: str
) -> tuple[Literal["T0", "T1", "T2"], int | None, Event | None]:
    """`(tier, live_sequence_remaining, last_confirmed_event)` derived from
    `PromotionConfirmed`/`Demoted` history for `account_ref` — T2 iff the
    latest `PromotionConfirmed` has no LATER `Demoted` (§7.3)."""
    confirmed = sorted(
        (
            event
            for event in ledger.query(EventFilter(types=["PromotionConfirmed"]))
            if event.payload.get("account_ref") == account_ref
        ),
        key=lambda event: event.ts_utc,
    )
    if not confirmed:
        return _base_tier(account_ref), None, None
    last_confirmed = confirmed[-1]
    demoted = [
        event
        for event in ledger.query(EventFilter(types=["Demoted"]))
        if event.payload.get("account_ref") == account_ref
        and event.ts_utc > last_confirmed.ts_utc
    ]
    if demoted:
        return _base_tier(account_ref), None, last_confirmed
    remaining = last_confirmed.payload.get("live_sequence_remaining")
    return "T2", remaining, last_confirmed


def _has_unconsumed_grant(ledger: Ledger, account_ref: str) -> bool:
    grants = [
        event
        for event in ledger.query(EventFilter(types=["PromotionGranted"]))
        if event.payload.get("account_ref") == account_ref
    ]
    if not grants:
        return False
    confirmed_grant_ids = {
        event.payload.get("granted_event_id")
        for event in ledger.query(EventFilter(types=["PromotionConfirmed"]))
        if event.payload.get("account_ref") == account_ref
    }
    return any(grant.event_id not in confirmed_grant_ids for grant in grants)


def _demotion_trigger(
    ledger: Ledger, account_ref: str, since_ts: datetime
) -> tuple[str, str] | None:
    """First demotion trigger for `account_ref` strictly since `since_ts`
    (§7.3's three named triggers). P2 only produces the `GateViolationDetected`
    trigger end-to-end (ASSUMPTIONS 92: R-009 drawdown-breach and
    failed-live-grade triggers share the identical mechanics but have no
    dedicated P2 producer/test this batch — a coverage gap, not a design
    gap)."""
    since_ts = since_ts.astimezone(UTC)
    violations = sorted(
        (
            event
            for event in ledger.query(EventFilter(types=["GateViolationDetected"]))
            if event.payload.get("account_ref") == account_ref
            and event.ts_utc.astimezone(UTC) > since_ts
        ),
        key=lambda event: event.ts_utc,
    )
    if violations:
        first = violations[0]
        return "gate_violation", f"{first.payload.get('rule_id')} ({first.event_id})"
    return None


def confirm_promotion() -> None:
    """Mike-only verb (CLI `tk promote confirm`): requires an unconsumed
    `PromotionGranted` event for `PolicyDials.default_account_ref` (no later
    `PromotionConfirmed`/`Demoted` for that same grant) — consumes it and
    appends `PromotionConfirmed` with `live_sequence_remaining=3` (§7.3,
    R-011). Refuses (typed exception — FLAGGED, ASSUMPTIONS: name
    `PromotionRefused`, additive `policy` export, same class of pin as
    `thesis.VoidRefused`) when no grant exists, or the most recent grant is
    already consumed. Story 4 — batch D."""
    ledger = default_ledger()
    dials = PolicyDials.load()
    account_ref = dials.default_account_ref

    grants = sorted(
        (
            event
            for event in ledger.query(EventFilter(types=["PromotionGranted"]))
            if event.payload.get("account_ref") == account_ref
        ),
        key=lambda event: event.ts_utc,
    )
    confirmed_grant_ids = {
        event.payload.get("granted_event_id")
        for event in ledger.query(EventFilter(types=["PromotionConfirmed"]))
        if event.payload.get("account_ref") == account_ref
    }
    unconsumed = [grant for grant in grants if grant.event_id not in confirmed_grant_ids]
    if not unconsumed:
        raise PromotionRefused(
            f"no unconsumed PromotionGranted event for account_ref={account_ref!r}"
        )
    grant = unconsumed[-1]

    payload = PromotionConfirmedPayload(
        account_ref=account_ref,
        to_tier="T2",
        granted_event_id=grant.event_id,
        live_sequence_remaining=3,
        confirmed_by="mike",
    )
    _append(ledger, "PromotionConfirmed", payload.model_dump(mode="json"))


def halt(reason: str) -> None:
    """Appends `HaltSet(reason)` — R-001 denies every mutating action while
    it is unresolved."""
    ledger = default_ledger()
    payload = HaltSetPayload(reason=reason, scope="all", set_by=_ACTOR)
    _append(ledger, "HaltSet", payload.model_dump(mode="json"))


def resume() -> None:
    """Appends `HaltCleared`, clearing the most recent unresolved
    `HaltSet`."""
    ledger = default_ledger()
    halt_events = ledger.query(EventFilter(types=["HaltSet"]))
    halt_event_id = halt_events[-1].event_id if halt_events else None
    payload = HaltClearedPayload(
        reason="resume", halt_event_id=halt_event_id, cleared_by=_ACTOR
    )
    _append(ledger, "HaltCleared", payload.model_dump(mode="json"))


__all__ = [
    "PromotionRefused",
    "confirm_promotion",
    "evaluate",
    "halt",
    "promotion_status",
    "resume",
    "status",
]
