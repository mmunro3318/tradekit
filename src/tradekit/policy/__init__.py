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

from tradekit.contracts import ProposedAction, Verdict


def evaluate(action: ProposedAction) -> Verdict:
    """Assemble a frozen `PolicyContext` (`_context.assemble`, MAY do I/O)
    -> run the PURE core (`_evaluate.evaluate_pure`) -> append
    `ActionProposed` + `VerdictIssued` (+ `GateViolationDetected` per
    denying rule hit) -> return the `Verdict`. Deny verdicts are NEVER
    silent (DESIGN §7.2)."""
    raise NotImplementedError("P2 batch D — docs/handoff/SPRINT-P2-thesis-policy.md story 3")


def status() -> dict[str, Any]:
    """`{policy_version_hash, halted, dials, rules}` snapshot (additive keys
    fine) — ensures a `PolicyVersionLoaded` event for the current hash on
    first call per process, plus `ConfigChanged` when the hash differs from
    the last recorded one (CTO addendum, "Ambient wiring")."""
    raise NotImplementedError("P2 batch D — docs/handoff/SPRINT-P2-thesis-policy.md story 3")


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
    raise NotImplementedError("P2 batch D — docs/handoff/SPRINT-P2-thesis-policy.md story 3")


def resume() -> None:
    """Appends `HaltCleared`, clearing the most recent unresolved
    `HaltSet`."""
    raise NotImplementedError("P2 batch D — docs/handoff/SPRINT-P2-thesis-policy.md story 3")


__all__ = [
    "confirm_promotion",
    "evaluate",
    "halt",
    "promotion_status",
    "resume",
    "status",
]
