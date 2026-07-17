"""`policy.evaluate()` ledgering + the pure-core purity property (DESIGN
§7.1, §8.2; CTO addendum, story-3 pins). RED this batch — `policy.evaluate`
and `_evaluate.evaluate_pure` are unconditional `NotImplementedError` stubs
(CTO's batch-C red/green split call), same red-phase discipline as
`tests/unit/thesis/test_lifecycle.py` in P2 batch A: every assertion below
describes the REAL behavior the next dev pass implements, so every test
here fails today with `NotImplementedError`, not wrapped in
`pytest.raises`.

The property test (same inputs ⇒ byte-identical Verdict) targets the PURE
core (`_evaluate.evaluate_pure`) directly, per the sprint doc: "The property
test ... targets the pure core."
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tradekit import policy
from tradekit.contracts import EventFilter, OrderRequest, ProposedAction
from tradekit.ledger import default_ledger
from tradekit.policy import _evaluate
from tradekit.policy._context import PolicyContext
from tradekit.policy._dials import PolicyDials, policy_version_hash
from tradekit.policy._rules import RULE_IDS, RULES

NOW = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)


def _order(**overrides: object) -> OrderRequest:
    base: dict[str, object] = dict(
        thesis_id="TH-1",
        account_ref="paper:alpha",
        asset={
            "symbol": "BTC/USD",
            "venue": "kraken",
            "asset_class": "crypto",
            "tick_size": "0.01",
        },
        side="buy",
        order_type="limit",
        qty=Decimal("1"),
        limit_price=Decimal("10.00"),
    )
    base.update(overrides)
    return OrderRequest(**base)  # type: ignore[arg-type]


def _allow_action() -> ProposedAction:
    # A submit_order this thesis's own rules should ALLOW: modest notional
    # ($10, order R-008's floor exactly, R-005's cap not tripped), tier/
    # balance/etc. supplied generously by the matching context below.
    return ProposedAction(
        kind="submit_order",
        account_ref="paper:alpha",
        requested_by="agent:test",
        thesis_id="TH-1",
        order=_order(),
    )


def _allow_ctx() -> PolicyContext:
    return PolicyContext(
        now=NOW,
        dials=PolicyDials(),
        account_tier="T1",
        settled_balance_usd=Decimal("500"),
        account_equity_usd=Decimal("500"),
        trades_today_count=0,
        trailing_30d_drawdown_pct=Decimal("0"),
        thesis_review_artifact_id="RA-1",
        thesis_market_snapshot_id="SNAP-1",
        thesis_ev_ok=True,
        recorded_sizing_usd=Decimal("10.00"),
    )


def _deny_action() -> ProposedAction:
    # Trips R-008 (min notional $10): qty 1 * limit 5.00 = $5.
    return ProposedAction(
        kind="submit_order",
        account_ref="paper:alpha",
        requested_by="agent:test",
        thesis_id="TH-1",
        order=_order(limit_price=Decimal("5.00")),
    )


# ---------------------------------------------------------------------------
# Purity property — targets the PURE core directly
# ---------------------------------------------------------------------------


def test_evaluate_pure_is_byte_identical_across_three_runs_for_the_same_inputs() -> None:
    action, ctx = _allow_action(), _allow_ctx()
    version_hash = policy_version_hash(ctx.dials, list(RULE_IDS))

    verdicts = [
        _evaluate.evaluate_pure(action, ctx, version_hash, RULES).model_dump_json()
        for _ in range(3)
    ]

    assert verdicts[0] == verdicts[1] == verdicts[2], (
        "evaluate_pure must be a pure function of (action, ctx, policy_version_hash, rules) "
        "— same inputs must serialize to byte-identical Verdicts across repeated calls"
    )


def test_evaluate_pure_allow_verdict_has_no_failing_rule_hits() -> None:
    action, ctx = _allow_action(), _allow_ctx()
    version_hash = policy_version_hash(ctx.dials, list(RULE_IDS))
    verdict = _evaluate.evaluate_pure(action, ctx, version_hash, RULES)
    assert verdict.allow is True
    assert all(hit.outcome == "pass" for hit in verdict.rule_hits)


def test_evaluate_pure_deny_verdict_carries_the_denying_rule_hit() -> None:
    action, ctx = _deny_action(), _allow_ctx()
    version_hash = policy_version_hash(ctx.dials, list(RULE_IDS))
    verdict = _evaluate.evaluate_pure(action, ctx, version_hash, RULES)
    assert verdict.allow is False
    assert any(hit.rule_id == "R-008" and hit.outcome == "fail" for hit in verdict.rule_hits)


# ---------------------------------------------------------------------------
# evaluate() ledgering — public verb, full pipeline
# ---------------------------------------------------------------------------


def test_evaluate_allow_appends_action_proposed_and_verdict_issued_only() -> None:
    action = _allow_action()
    verdict = policy.evaluate(action)

    assert verdict.allow is True
    proposed = default_ledger().query(EventFilter(types=["ActionProposed"]))
    issued = default_ledger().query(EventFilter(types=["VerdictIssued"]))
    violations = default_ledger().query(EventFilter(types=["GateViolationDetected"]))
    assert len(proposed) == 1
    assert len(issued) == 1
    assert len(violations) == 0, "an allow verdict must never emit GateViolationDetected"


def test_evaluate_deny_appends_gate_violation_detected_per_denying_rule() -> None:
    action = _deny_action()
    verdict = policy.evaluate(action)

    assert verdict.allow is False
    violations = default_ledger().query(EventFilter(types=["GateViolationDetected"]))
    denying_rule_ids = {hit.rule_id for hit in verdict.rule_hits if hit.outcome == "fail"}
    assert {v.payload["rule_id"] for v in violations} == denying_rule_ids, (
        "deny verdicts are NEVER silent — every denying rule hit gets its own "
        "GateViolationDetected event (DESIGN §7.2)"
    )


def test_evaluate_verdicts_carry_the_policy_version_hash() -> None:
    verdict = policy.evaluate(_allow_action())
    dials = PolicyDials()
    expected = policy_version_hash(dials, list(RULE_IDS))
    assert verdict.policy_version_hash == expected


def test_evaluate_appends_policy_version_loaded_on_first_call_for_a_hash() -> None:
    policy.evaluate(_allow_action())
    loaded = default_ledger().query(EventFilter(types=["PolicyVersionLoaded"]))
    assert len(loaded) == 1


def test_evaluate_does_not_repeat_policy_version_loaded_for_the_same_hash() -> None:
    policy.evaluate(_allow_action())
    policy.evaluate(_allow_action())
    loaded = default_ledger().query(EventFilter(types=["PolicyVersionLoaded"]))
    assert len(loaded) == 1, "PolicyVersionLoaded fires once per NEW hash, not once per call"


def test_evaluate_appends_config_changed_when_the_hash_differs_from_last_recorded(
    monkeypatch, tmp_path
) -> None:
    policy.evaluate(_allow_action())  # first hash recorded

    config = tmp_path / "changed.toml"
    config.write_text('max_position_usd_live = "999"\n', encoding="utf-8")
    monkeypatch.setenv("TK_CONFIG_PATH", str(config))

    policy.evaluate(_allow_action())  # different dials -> different hash

    changed = default_ledger().query(EventFilter(types=["ConfigChanged"]))
    assert len(changed) == 1
