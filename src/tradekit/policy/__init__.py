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

from typing import Any

from ulid import ULID

from tradekit.contracts import (
    ActionProposedPayload,
    ConfigChangedPayload,
    Event,
    EventFilter,
    GateViolationDetectedPayload,
    HaltClearedPayload,
    HaltSetPayload,
    PolicyVersionLoadedPayload,
    ProposedAction,
    Verdict,
    VerdictIssuedPayload,
)
from tradekit.ledger import Ledger, default_ledger
from tradekit.policy import _context, _evaluate
from tradekit.policy._dials import PolicyDials, canonical_dump, policy_version_hash
from tradekit.policy._rules import RULE_IDS, RULES, RULES_BY_ID

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
    """Series/promotion-ladder readiness snapshot (§7.3). Story 4 — NOT this
    sprint's scope for this batch; deferred whole to batch D."""
    raise NotImplementedError("P2 batch D — docs/handoff/SPRINT-P2-thesis-policy.md story 4")


def confirm_promotion() -> None:
    """Mike-only verb: consumes an unconsumed `PromotionGranted` and appends
    `PromotionConfirmed` with `live_sequence_remaining=3` (§7.3, R-011).
    Story 4 — batch D."""
    raise NotImplementedError("P2 batch D — docs/handoff/SPRINT-P2-thesis-policy.md story 4")


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
    "confirm_promotion",
    "evaluate",
    "halt",
    "promotion_status",
    "resume",
    "status",
]
