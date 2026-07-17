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

from ulid import ULID

from tradekit import policy
from tradekit.contracts import (
    Event,
    EventFilter,
    MarketSnapshotTakenPayload,
    OrderRequest,
    ProposedAction,
    ReviewCompletedPayload,
    SizingComputedPayload,
    ThesisSubmittedPayload,
)
from tradekit.ledger import default_ledger
from tradekit.policy import _evaluate
from tradekit.policy._context import PolicyContext
from tradekit.policy._dials import PolicyDials, policy_version_hash
from tradekit.policy._rules import RULE_IDS, RULES

NOW = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)


def _harness_append(event_type: str, payload: dict) -> None:
    default_ledger().append(
        Event(
            event_id=str(ULID()),
            ts_utc=NOW,
            type=event_type,  # type: ignore[arg-type]
            actor="test:harness",
            run_id=None,
            schema_ver=1,
            payload=payload,
        )
    )


def _seed_thesis_events(
    thesis_id: str = "TH-1", *, include_sizing: bool = True
) -> None:
    """Harness-append the minimal REAL events that EARN an allow for
    `thesis_id` (CTO adjudication, batch-C dev pass: the allow path must be
    earned — a fabricated/never-drafted thesis_id defeating R-010/R-012 is
    the exact gaming vector the engine exists to block; the original
    fixture's bare TH-1 was the defect, not the anti-permissive semantics).

    Each event maps to a specific rule input `_context.assemble` derives:
    - `MarketSnapshotTaken` — the submit-time snapshot artifact (SNAP-1);
      R-010's `market_snapshot_id` itself rides `ThesisSubmitted` below,
      this event is the snapshot's own record (CTO addendum story-1 pins).
    - `SizingComputed` (`sizing.recommended_size_usd = "10.00"`) — R-012's
      `recorded_sizing_usd`, matched exactly by `_allow_action()`'s
      qty 1 x limit 10.00 order (deviation 0 <= 1% tolerance).
    - `ThesisSubmitted` (carries `market_snapshot_id="SNAP-1"` + the EV
      numbers) — R-010's `thesis_market_snapshot_id` and `thesis_ev_ok`
      (the marker only ever exists AFTER EV validation passed,
      ASSUMPTIONS 65) + R-014's age clock.
    - `ReviewCompleted(kind="thesis_review", review_artifact_id="RA-1")` —
      R-010's `thesis_review_artifact_id` (P2 ships no review verb; tests
      append it as a harness action, same as `thesis.approve`'s own read).
    """
    _harness_append(
        "MarketSnapshotTaken",
        MarketSnapshotTakenPayload(
            thesis_id=thesis_id,
            snapshot_id="SNAP-1",
            symbol="BTC/USD",
            ts=NOW,
            last_close=Decimal("10.00"),
            source="test-fixture",
        ).model_dump(mode="json"),
    )
    if include_sizing:
        _harness_append(
            "SizingComputed",
            SizingComputedPayload(
                thesis_id=thesis_id,
                symbol="BTC/USD",
                account_equity_usd=Decimal("500"),
                sizing={"recommended_size_usd": "10.00"},
            ).model_dump(mode="json"),
        )
    _harness_append(
        "ThesisSubmitted",
        ThesisSubmittedPayload(
            thesis_id=thesis_id,
            market_snapshot_id="SNAP-1",
            resolved_target_price=Decimal("12.00"),
            resolved_stop_price=Decimal("9.00"),
            resolved_success_criteria=[],
            resolved_failure_criteria=[],
            ev_stated_usd=Decimal("0.50"),
            ev_recomputed_usd=Decimal("0.50"),
        ).model_dump(mode="json"),
    )
    _harness_append(
        "ReviewCompleted",
        ReviewCompletedPayload(
            thesis_id=thesis_id,
            review_artifact_id="RA-1",
            passed=True,
            kind="thesis_review",
        ).model_dump(mode="json"),
    )


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
    _seed_thesis_events()
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
    _seed_thesis_events()  # honest state — the intended trip is R-008's floor
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
    _seed_thesis_events()
    verdict = policy.evaluate(_allow_action())
    dials = PolicyDials()
    expected = policy_version_hash(dials, list(RULE_IDS))
    assert verdict.policy_version_hash == expected


def test_evaluate_appends_policy_version_loaded_on_first_call_for_a_hash() -> None:
    _seed_thesis_events()
    policy.evaluate(_allow_action())
    loaded = default_ledger().query(EventFilter(types=["PolicyVersionLoaded"]))
    assert len(loaded) == 1


def test_evaluate_does_not_repeat_policy_version_loaded_for_the_same_hash() -> None:
    _seed_thesis_events()
    policy.evaluate(_allow_action())
    policy.evaluate(_allow_action())
    loaded = default_ledger().query(EventFilter(types=["PolicyVersionLoaded"]))
    assert len(loaded) == 1, "PolicyVersionLoaded fires once per NEW hash, not once per call"


def test_evaluate_appends_config_changed_when_the_hash_differs_from_last_recorded(
    monkeypatch, tmp_path
) -> None:
    _seed_thesis_events()
    policy.evaluate(_allow_action())  # first hash recorded

    config = tmp_path / "changed.toml"
    config.write_text('max_position_usd_live = "999"\n', encoding="utf-8")
    monkeypatch.setenv("TK_CONFIG_PATH", str(config))

    policy.evaluate(_allow_action())  # different dials -> different hash

    changed = default_ledger().query(EventFilter(types=["ConfigChanged"]))
    assert len(changed) == 1


# ---------------------------------------------------------------------------
# Anti-permissive deny pins (CTO adjudication, batch-C dev pass): a
# fabricated thesis_id must never defeat R-010/R-012 — the closed hole.
# ---------------------------------------------------------------------------


def test_evaluate_denies_a_fabricated_never_drafted_thesis_id_via_r010() -> None:
    # NO harness events at all for this thesis_id — the ledger has never
    # seen it. R-010's prerequisite fields must come back None/absent and
    # deny with insufficient_context, never a silent/vacuous pass.
    action = ProposedAction(
        kind="submit_order",
        account_ref="paper:alpha",
        requested_by="agent:test",
        thesis_id="TH-FABRICATED",
        order=_order(thesis_id="TH-FABRICATED"),
    )
    verdict = policy.evaluate(action)

    assert verdict.allow is False
    r010 = next(hit for hit in verdict.rule_hits if hit.rule_id == "R-010")
    assert r010.outcome == "fail"
    assert "insufficient_context" in (r010.measured or "")
    violations = default_ledger().query(EventFilter(types=["GateViolationDetected"]))
    assert any(v.payload["rule_id"] == "R-010" for v in violations), (
        "a fabricated-thesis-id denial is a gate violation like any other — "
        "it must be ledgered, never silent"
    )


def test_evaluate_denies_a_submitted_thesis_with_no_sizing_computed_via_r012() -> None:
    # Submitted + reviewed, but NO SizingComputed on record: R-012 has
    # nothing to hold the order against and must deny with
    # insufficient_context — not fall back to trusting the order's own
    # notional (a zero-deviation no-op would let an unsized thesis bypass
    # sizing purity entirely).
    _seed_thesis_events(include_sizing=False)
    verdict = policy.evaluate(_allow_action())

    assert verdict.allow is False
    r012 = next(hit for hit in verdict.rule_hits if hit.rule_id == "R-012")
    assert r012.outcome == "fail"
    assert "insufficient_context" in (r012.measured or "")
