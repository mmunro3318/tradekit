"""Pure evaluation core (DESIGN §7.1; CTO addendum, story-3 pins).

`evaluate_pure(action, ctx, policy_version_hash, rules)` is meant to be a
PURE function of its four arguments — no I/O, no clock reads beyond what
`ctx.now` already carries — so the same inputs always produce a
byte-identical `Verdict` (the property test in `tests/unit/policy/
test_evaluate.py` targets exactly this function). STUB this batch (CTO's
batch-C red/green split call: "_evaluate ... stay stubs -> red") — the
public `policy.evaluate()` ledgering wrapper that calls this is also a stub;
wiring both together, plus `GateViolationDetected`/`PolicyVersionLoaded`/
`ConfigChanged` emission, is the batch-D+ dev pass.

Individual rules are ALREADY unit-testable without this function —
`_rules.py`'s `Rule.check(action, ctx)` is pure and real; tests exercise
rules directly. This module only owns "run every applicable rule, roll the
results up into one Verdict."
"""

from __future__ import annotations

import hashlib

from tradekit.contracts import ProposedAction, RuleHit, Verdict
from tradekit.policy._context import PolicyContext
from tradekit.policy._rules import Rule


def _deterministic_verdict_id(
    action: ProposedAction, ctx: PolicyContext, policy_version_hash: str, hits: list[RuleHit]
) -> str:
    """A pure, deterministic id — NOT a fresh ULID (which would break the
    property test's "same inputs -> byte-identical Verdict" requirement).
    sha256 over the action/context/hash/hits, all rendered through each
    model's own JSON serialization so the id is reproducible byte-for-byte
    across repeated calls with identical inputs."""
    blob = "|".join(
        [
            action.model_dump_json(),
            ctx.model_dump_json(),
            policy_version_hash,
            "|".join(hit.model_dump_json() for hit in hits),
        ]
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def evaluate_pure(
    action: ProposedAction,
    ctx: PolicyContext,
    policy_version_hash: str,
    rules: tuple[Rule, ...],
) -> Verdict:
    """Run every rule in `rules` applicable to `action.kind` against `ctx`
    and roll the `RuleHit`s up into one `Verdict` (`allow` iff every hit
    passed). No I/O — `policy.evaluate()` is the only caller, and it is the
    layer that ledgers `ActionProposed`/`VerdictIssued`/
    `GateViolationDetected` around this pure call."""
    applicable = tuple(rule for rule in rules if action.kind in rule.applies_to)
    hits = [rule.check(action, ctx) for rule in applicable]
    allow = all(hit.outcome == "pass" for hit in hits)
    verdict_id = _deterministic_verdict_id(action, ctx, policy_version_hash, hits)
    return Verdict(
        verdict_id=verdict_id,
        allow=allow,
        rule_hits=hits,
        policy_version_hash=policy_version_hash,
    )


__all__ = ["evaluate_pure"]
