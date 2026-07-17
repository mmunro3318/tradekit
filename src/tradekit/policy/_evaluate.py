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

from tradekit.contracts import ProposedAction, Verdict
from tradekit.policy._context import PolicyContext
from tradekit.policy._rules import Rule


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
    raise NotImplementedError(
        "P2 batch D — docs/handoff/SPRINT-P2-thesis-policy.md story 3; pure "
        "(action, ctx, rules) -> Verdict core, no I/O"
    )


__all__ = ["evaluate_pure"]
