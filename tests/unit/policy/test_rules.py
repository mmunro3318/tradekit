"""R-001..R-016 — one allow + one deny test per rule (DESIGN §7.2; CTO
addendum, story-3 pins). REAL this batch (`_rules.py`'s `Rule.check` is a
pure function of `(action, ctx)`; these tests call it DIRECTLY, with no
`_evaluate`/`policy.evaluate()` involvement at all — `_rules.RULES_BY_ID`
IS unit-testable today even though the pure core that will eventually run
every rule together stays a stub). All GREEN.

Threshold arithmetic is frozen in the comment directly above the fixture
that exercises it (FIXTURE-FREEZE rule) — every Decimal literal below is
hand-verified, not computed at test time.

Insufficient-context vs vacuous-pass split (CTO addendum): R-013 (no open
positions) and R-015 (nothing graded yet) pass VACUOUSLY on an empty
container — there is genuinely nothing to gate. Every other rule's deny
fixture below either trips a real threshold OR (R-010's deny case)
demonstrates the anti-permissive `insufficient_context` path: a missing
field denies, it never passes silently. See `tests/ASSUMPTIONS.md`'s
batch-C entry for the full per-rule enumeration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tradekit.contracts import OrderRequest, ProposedAction
from tradekit.policy._context import PolicyContext
from tradekit.policy._dials import PolicyDials
from tradekit.policy._rules import RULES_BY_ID

NOW = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
DIALS = PolicyDials()  # field defaults == committed config.toml, §7.2


def _asset(symbol: str = "BTC/USD") -> dict[str, str]:
    return {"symbol": symbol, "venue": "kraken", "asset_class": "crypto", "tick_size": "0.01"}


def _order(
    *, account_ref: str, symbol: str = "BTC/USD", qty: str = "1", limit_price: str | None = "10.00"
) -> OrderRequest:
    return OrderRequest(
        thesis_id="TH-1",
        account_ref=account_ref,
        asset=_asset(symbol),  # type: ignore[arg-type]
        side="buy",
        order_type="limit" if limit_price is not None else "market",
        qty=Decimal(qty),
        limit_price=Decimal(limit_price) if limit_price is not None else None,
    )


def _action(
    *,
    kind: str = "submit_order",
    account_ref: str = "paper:alpha",
    order: OrderRequest | None = "__default__",  # type: ignore[assignment]
) -> ProposedAction:
    if order == "__default__":
        order = _order(account_ref=account_ref)
    return ProposedAction(
        kind=kind, account_ref=account_ref, requested_by="agent:test", thesis_id="TH-1", order=order
    )


def _ctx(**overrides: object) -> PolicyContext:
    base: dict[str, object] = {"now": NOW, "dials": DIALS}
    base.update(overrides)
    return PolicyContext(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# R-001 — kill switch
# ---------------------------------------------------------------------------


def test_r001_allows_when_not_halted() -> None:
    hit = RULES_BY_ID["R-001"].check(_action(), _ctx(halted=False))
    assert hit.outcome == "pass"


def test_r001_denies_when_halted() -> None:
    hit = RULES_BY_ID["R-001"].check(_action(), _ctx(halted=True, halt_reason="mismatch"))
    assert hit.outcome == "fail"
    assert hit.limit == "mismatch"


# ---------------------------------------------------------------------------
# R-002 — promotion tier
# ---------------------------------------------------------------------------


def test_r002_allows_when_tier_meets_the_account_refs_requirement() -> None:
    action = _action(account_ref="paper:alpha")  # requires >= T1
    hit = RULES_BY_ID["R-002"].check(action, _ctx(account_tier="T1"))
    assert hit.outcome == "pass"


def test_r002_denies_when_tier_is_below_requirement() -> None:
    action = _action(account_ref="paper:alpha")  # requires >= T1
    hit = RULES_BY_ID["R-002"].check(action, _ctx(account_tier="T0"))
    assert hit.outcome == "fail"


# ---------------------------------------------------------------------------
# R-003 — settled balance incl. fees
# ---------------------------------------------------------------------------


def test_r003_allows_when_balance_covers_the_order_notional() -> None:
    # order notional = qty(1) * limit_price(10.00) = 10.00
    action = _action(order=_order(account_ref="paper:alpha", limit_price="10.00"))
    hit = RULES_BY_ID["R-003"].check(action, _ctx(settled_balance_usd=Decimal("50")))
    assert hit.outcome == "pass"


def test_r003_denies_when_balance_is_insufficient() -> None:
    action = _action(order=_order(account_ref="paper:alpha", limit_price="10.00"))
    hit = RULES_BY_ID["R-003"].check(action, _ctx(settled_balance_usd=Decimal("5")))
    assert hit.outcome == "fail"


# ---------------------------------------------------------------------------
# R-004 — live asset allowlist
# ---------------------------------------------------------------------------


def test_r004_allows_a_listed_symbol_on_live() -> None:
    order = _order(account_ref="live:alpaca", symbol="BTC/USD")
    action = _action(account_ref="live:alpaca", order=order)
    hit = RULES_BY_ID["R-004"].check(action, _ctx())
    assert hit.outcome == "pass"


def test_r004_denies_an_unlisted_symbol_on_live() -> None:
    order = _order(account_ref="live:alpaca", symbol="DOGE/USD")
    action = _action(account_ref="live:alpaca", order=order)
    hit = RULES_BY_ID["R-004"].check(action, _ctx())
    assert hit.outcome == "fail"


# ---------------------------------------------------------------------------
# R-005 — max position notional (freeze gate: paper 10% of equity 500 = $50)
# ---------------------------------------------------------------------------


def test_r005_paper_allows_exactly_50_dollars_notional_at_500_equity() -> None:
    # 0.10 * 500 = 50.00; notional = 1 * 50.00 = 50.00 <= 50.00 -> allow
    order = _order(account_ref="paper:alpha", limit_price="50.00")
    action = _action(account_ref="paper:alpha", order=order)
    hit = RULES_BY_ID["R-005"].check(action, _ctx(account_equity_usd=Decimal("500")))
    assert hit.outcome == "pass"
    assert hit.measured == "50.00" and hit.limit == "50.00"


def test_r005_paper_denies_50_dollars_and_one_cent_notional_at_500_equity() -> None:
    # notional = 1 * 50.01 = 50.01 > 50.00 -> deny
    order = _order(account_ref="paper:alpha", limit_price="50.01")
    action = _action(account_ref="paper:alpha", order=order)
    hit = RULES_BY_ID["R-005"].check(action, _ctx(account_equity_usd=Decimal("500")))
    assert hit.outcome == "fail"


# TD-24 migration (SPRINT P3 batch A, Mike-signed 2026-07-17): R-005's LIVE
# leg moved from a flat $25 dial to 5% of account principal — these are the
# NEW-semantics boundary tests (0.05 * 500 = 25.00), added fresh this batch
# (the live leg had no pre-existing test_rules.py coverage to preserve).


def test_r005_live_allows_exactly_25_dollars_notional_at_500_principal() -> None:
    # 0.05 * 500 = 25.00; notional = 1 * 25.00 = 25.00 <= 25.00 -> allow
    order = _order(account_ref="live:alpaca", limit_price="25.00")
    action = _action(account_ref="live:alpaca", order=order)
    hit = RULES_BY_ID["R-005"].check(action, _ctx(account_principal_usd=Decimal("500")))
    assert hit.outcome == "pass"
    assert hit.measured == "25.00" and hit.limit == "25.00"


def test_r005_live_denies_25_dollars_and_one_cent_notional_at_500_principal() -> None:
    # notional = 1 * 25.01 = 25.01 > 25.00 -> deny
    order = _order(account_ref="live:alpaca", limit_price="25.01")
    action = _action(account_ref="live:alpaca", order=order)
    hit = RULES_BY_ID["R-005"].check(action, _ctx(account_principal_usd=Decimal("500")))
    assert hit.outcome == "fail"


def test_r005_live_denies_insufficient_context_with_no_principal() -> None:
    order = _order(account_ref="live:alpaca", limit_price="25.00")
    action = _action(account_ref="live:alpaca", order=order)
    hit = RULES_BY_ID["R-005"].check(action, _ctx())
    assert hit.outcome == "fail"
    assert hit.measured == "insufficient_context:account_principal_usd"


# ---------------------------------------------------------------------------
# R-006 — max total live exposure (freeze gate: 80 + 20.00 = 100.00 <= 100)
#
# TD-24 migration (SPRINT P3 batch A, Mike-signed 2026-07-17): the dial
# moved from a flat max_total_live_exposure_usd=$100 to
# max_total_live_exposure_pct(0.20) * account_principal_usd — the boundary
# VALUES below are UNCHANGED (0.20 * 500 = 100.00, identical to the old flat
# $100), but the check now requires `account_principal_usd` in context,
# so `_ctx(...)` gains that one extra kwarg. Flagged per the sprint
# addendum's "enumerate any test whose dial VALUE legitimately moved" — the
# VALUE did not move, only the context SHAPE (a new required field) did;
# see the batch's final report for the full enumeration.
# ---------------------------------------------------------------------------


def test_r006_allows_when_projected_exposure_equals_the_cap() -> None:
    order = _order(account_ref="live:alpaca", limit_price="20.00")
    action = _action(account_ref="live:alpaca", order=order)
    hit = RULES_BY_ID["R-006"].check(
        action, _ctx(live_exposure_usd=Decimal("80"), account_principal_usd=Decimal("500"))
    )
    assert hit.outcome == "pass"


def test_r006_denies_when_projected_exposure_exceeds_the_cap_by_a_cent() -> None:
    # 80 + 20.01 = 100.01 > 100
    order = _order(account_ref="live:alpaca", limit_price="20.01")
    action = _action(account_ref="live:alpaca", order=order)
    hit = RULES_BY_ID["R-006"].check(
        action, _ctx(live_exposure_usd=Decimal("80"), account_principal_usd=Decimal("500"))
    )
    assert hit.outcome == "fail"


def test_r006_denies_insufficient_context_with_no_principal() -> None:
    order = _order(account_ref="live:alpaca", limit_price="20.00")
    action = _action(account_ref="live:alpaca", order=order)
    hit = RULES_BY_ID["R-006"].check(action, _ctx(live_exposure_usd=Decimal("80")))
    assert hit.outcome == "fail"
    assert hit.measured == "insufficient_context:account_principal_usd"


# ---------------------------------------------------------------------------
# R-007 — daily trade count (live cap 3)
# ---------------------------------------------------------------------------


def test_r007_allows_below_the_live_daily_cap() -> None:
    action = _action(account_ref="live:alpaca", order=_order(account_ref="live:alpaca"))
    hit = RULES_BY_ID["R-007"].check(action, _ctx(trades_today_count=2))
    assert hit.outcome == "pass"


def test_r007_denies_at_the_live_daily_cap() -> None:
    action = _action(account_ref="live:alpaca", order=_order(account_ref="live:alpaca"))
    hit = RULES_BY_ID["R-007"].check(action, _ctx(trades_today_count=3))
    assert hit.outcome == "fail"


# ---------------------------------------------------------------------------
# R-008 — min notional $10
# ---------------------------------------------------------------------------


def test_r008_allows_exactly_the_min_notional() -> None:
    action = _action(order=_order(account_ref="paper:alpha", limit_price="10.00"))
    hit = RULES_BY_ID["R-008"].check(action, _ctx())
    assert hit.outcome == "pass"


def test_r008_denies_one_cent_under_the_min_notional() -> None:
    action = _action(order=_order(account_ref="paper:alpha", limit_price="9.99"))
    hit = RULES_BY_ID["R-008"].check(action, _ctx())
    assert hit.outcome == "fail"


# ---------------------------------------------------------------------------
# R-009 — drawdown circuit breaker (cap 10%)
# ---------------------------------------------------------------------------


def test_r009_allows_below_the_drawdown_cap() -> None:
    hit = RULES_BY_ID["R-009"].check(_action(), _ctx(trailing_30d_drawdown_pct=Decimal("0.09")))
    assert hit.outcome == "pass"


def test_r009_denies_at_the_drawdown_cap() -> None:
    hit = RULES_BY_ID["R-009"].check(_action(), _ctx(trailing_30d_drawdown_pct=Decimal("0.10")))
    assert hit.outcome == "fail"


# ---------------------------------------------------------------------------
# R-010 — thesis prerequisites (deny path = insufficient_context)
# ---------------------------------------------------------------------------


def test_r010_allows_with_review_snapshot_and_valid_ev() -> None:
    hit = RULES_BY_ID["R-010"].check(
        _action(),
        _ctx(
            thesis_review_artifact_id="RA-1",
            thesis_market_snapshot_id="SNAP-1",
            thesis_ev_ok=True,
        ),
    )
    assert hit.outcome == "pass"


def test_r010_denies_with_no_review_artifact_insufficient_context() -> None:
    hit = RULES_BY_ID["R-010"].check(
        _action(),
        _ctx(thesis_review_artifact_id=None, thesis_market_snapshot_id="SNAP-1", thesis_ev_ok=True),
    )
    assert hit.outcome == "fail"
    assert hit.measured == "insufficient_context:thesis_review_artifact_id"


# ---------------------------------------------------------------------------
# R-011 — live sequence budget
# ---------------------------------------------------------------------------


def test_r011_allows_when_live_trades_remain() -> None:
    action = _action(account_ref="live:alpaca", order=_order(account_ref="live:alpaca"))
    hit = RULES_BY_ID["R-011"].check(action, _ctx(live_trades_remaining=2))
    assert hit.outcome == "pass"


def test_r011_denies_when_no_live_trades_remain() -> None:
    action = _action(account_ref="live:alpaca", order=_order(account_ref="live:alpaca"))
    hit = RULES_BY_ID["R-011"].check(action, _ctx(live_trades_remaining=0))
    assert hit.outcome == "fail"


# ---------------------------------------------------------------------------
# R-012 — sizing purity (freeze gate: |submitted - recorded| / recorded <= 1%)
# ---------------------------------------------------------------------------


def test_r012_allows_exactly_at_the_1_percent_tolerance_boundary() -> None:
    # recorded 50.00; submitted 50.50 -> deviation 0.50/50.00 = 0.01 == 1% -> allow
    action = _action(order=_order(account_ref="paper:alpha", limit_price="50.50"))
    hit = RULES_BY_ID["R-012"].check(action, _ctx(recorded_sizing_usd=Decimal("50.00")))
    assert hit.outcome == "pass"


def test_r012_denies_just_past_the_1_percent_tolerance_boundary() -> None:
    # recorded 50.00; submitted 50.51 -> deviation 0.51/50.00 = 0.0102 > 1% -> deny
    action = _action(order=_order(account_ref="paper:alpha", limit_price="50.51"))
    hit = RULES_BY_ID["R-012"].check(action, _ctx(recorded_sizing_usd=Decimal("50.00")))
    assert hit.outcome == "fail"


# ---------------------------------------------------------------------------
# R-013 — correlation cap (vacuous pass when no open positions)
# ---------------------------------------------------------------------------


def test_r013_allows_vacuously_with_no_open_positions() -> None:
    hit = RULES_BY_ID["R-013"].check(_action(), _ctx(open_position_correlations={}))
    assert hit.outcome == "pass"
    assert hit.measured == "no_open_positions"


def test_r013_denies_above_the_correlation_cap() -> None:
    hit = RULES_BY_ID["R-013"].check(
        _action(), _ctx(open_position_correlations={"ETH/USD": Decimal("0.76")})
    )
    assert hit.outcome == "fail"


# ---------------------------------------------------------------------------
# R-014 — advisory cooling-off (freeze gate: >$200 needs thesis age >= 24h)
#
# TD-24 migration: dial moved from a flat cooling_off_notional_usd=$200 to
# cooling_off_pct(0.40) * account_principal_usd — VALUES unchanged (0.40 *
# 500 = 200.00), context now needs account_principal_usd (same flagged
# shape-only change as R-006 above).
# ---------------------------------------------------------------------------


def test_r014_allows_an_aged_thesis_above_the_notional_threshold() -> None:
    action = _action(
        account_ref="advisory:kraken",
        order=_order(account_ref="advisory:kraken", limit_price="250.00"),
    )
    hit = RULES_BY_ID["R-014"].check(
        action, _ctx(thesis_age_hours=Decimal("30"), account_principal_usd=Decimal("500"))
    )
    assert hit.outcome == "pass"


def test_r014_denies_a_fresh_thesis_above_the_notional_threshold() -> None:
    action = _action(
        account_ref="advisory:kraken",
        order=_order(account_ref="advisory:kraken", limit_price="250.00"),
    )
    hit = RULES_BY_ID["R-014"].check(
        action, _ctx(thesis_age_hours=Decimal("10"), account_principal_usd=Decimal("500"))
    )
    assert hit.outcome == "fail"


def test_r014_allows_exactly_at_the_40_percent_of_principal_boundary_with_no_age_check() -> None:
    # 0.40 * 500 = 200.00; notional == threshold -> allow, no age needed
    # (mirrors the pre-existing "notional <= threshold" allow branch).
    action = _action(
        account_ref="advisory:kraken",
        order=_order(account_ref="advisory:kraken", limit_price="200.00"),
    )
    hit = RULES_BY_ID["R-014"].check(action, _ctx(account_principal_usd=Decimal("500")))
    assert hit.outcome == "pass"


def test_r014_denies_insufficient_context_with_no_principal() -> None:
    action = _action(
        account_ref="advisory:kraken",
        order=_order(account_ref="advisory:kraken", limit_price="250.00"),
    )
    hit = RULES_BY_ID["R-014"].check(action, _ctx(thesis_age_hours=Decimal("30")))
    assert hit.outcome == "fail"
    assert hit.measured == "insufficient_context:account_principal_usd"


# ---------------------------------------------------------------------------
# R-015 — VOID-rate audit (freeze gate: trailing 20, 4 voids = 20% allows, 5 denies)
# ---------------------------------------------------------------------------


def test_r015_allows_at_exactly_the_20_percent_void_rate() -> None:
    outcomes = tuple(["VOID"] * 4 + ["PASS"] * 16)  # 4/20 = 0.20
    hit = RULES_BY_ID["R-015"].check(_action(), _ctx(trailing_graded_outcomes=outcomes))
    assert hit.outcome == "pass"


def test_r015_denies_above_the_20_percent_void_rate() -> None:
    outcomes = tuple(["VOID"] * 5 + ["PASS"] * 15)  # 5/20 = 0.25
    hit = RULES_BY_ID["R-015"].check(_action(), _ctx(trailing_graded_outcomes=outcomes))
    assert hit.outcome == "fail"


# ---------------------------------------------------------------------------
# R-016 — promotion metric gates (stubbed metrics summary, FLAGGED SEAM)
# ---------------------------------------------------------------------------


def test_r016_allows_when_the_stubbed_metrics_summary_passes_gates() -> None:
    action = _action(kind="promote", order=None)
    hit = RULES_BY_ID["R-016"].check(action, _ctx(strategy_metrics={"passes_gates": True}))
    assert hit.outcome == "pass"


def test_r016_denies_when_the_stubbed_metrics_summary_fails_gates() -> None:
    action = _action(kind="promote", order=None)
    hit = RULES_BY_ID["R-016"].check(action, _ctx(strategy_metrics={"passes_gates": False}))
    assert hit.outcome == "fail"


# ---------------------------------------------------------------------------
# R-017 — max_daily_drawdown (TD-24, SPRINT P3 batch A, Mike-signed
# 2026-07-17). FIXTURE-FREEZE: -15.00 = 0.03 * 500 exactly (allow, <=);
# -15.01 is one cent past the 3% dial (deny).
# ---------------------------------------------------------------------------


def test_r017_allows_exactly_at_the_configured_daily_drawdown_boundary() -> None:
    # dial 0.03; daily pnl -15.00 -> loss_fraction = 15.00/500 = 0.03 == dial -> allow
    hit = RULES_BY_ID["R-017"].check(
        _action(),
        _ctx(
            account_max_daily_drawdown=Decimal("0.03"),
            daily_pnl_fraction=Decimal("-15.00") / Decimal("500"),
        ),
    )
    assert hit.outcome == "pass"


def test_r017_denies_one_cent_past_the_configured_daily_drawdown_boundary() -> None:
    # daily pnl -15.01 -> loss_fraction = 15.01/500 = 0.03002 > 0.03 -> deny
    hit = RULES_BY_ID["R-017"].check(
        _action(),
        _ctx(
            account_max_daily_drawdown=Decimal("0.03"),
            daily_pnl_fraction=Decimal("-15.01") / Decimal("500"),
        ),
    )
    assert hit.outcome == "fail"


def test_r017_emits_not_configured_when_the_dial_is_disabled() -> None:
    # account_max_daily_drawdown resolves to None (AccountConfig + dial both
    # unset) — the rule is still CONSULTED (audit trail), never a silent skip.
    hit = RULES_BY_ID["R-017"].check(
        _action(), _ctx(account_max_daily_drawdown=None, daily_pnl_fraction=Decimal("-0.50"))
    )
    assert hit.outcome == "not_configured"


def test_r017_not_configured_does_not_deny_the_overall_verdict() -> None:
    """`not_configured` must roll up as allow, not deny, in `evaluate_pure`
    (the pure core rolling multiple RuleHits into one Verdict) — a rule
    consulted-but-disabled cannot itself block a submission."""
    from tradekit.policy._evaluate import evaluate_pure

    action = _action(kind="submit_order")
    ctx = _ctx(
        halted=False,
        account_tier="T1",
        settled_balance_usd=Decimal("1000"),
        account_equity_usd=Decimal("1000"),
        trades_today_count=0,
        trailing_30d_drawdown_pct=Decimal("0"),
        thesis_review_artifact_id="RA-1",
        thesis_market_snapshot_id="SNAP-1",
        thesis_ev_ok=True,
        recorded_sizing_usd=Decimal("10.00"),
        account_max_daily_drawdown=None,
        account_max_lifetime_drawdown=None,
    )
    rule = RULES_BY_ID["R-017"]
    verdict = evaluate_pure(action, ctx, "hash-1", (rule,))
    assert verdict.allow is True
    assert verdict.rule_hits[0].outcome == "not_configured"


# ---------------------------------------------------------------------------
# R-018 — max_lifetime_drawdown (TD-24). Same shape as R-017, over
# `lifetime_drawdown_fraction` instead of `daily_pnl_fraction`.
# ---------------------------------------------------------------------------


def test_r018_allows_exactly_at_the_configured_lifetime_drawdown_boundary() -> None:
    hit = RULES_BY_ID["R-018"].check(
        _action(),
        _ctx(
            account_max_lifetime_drawdown=Decimal("0.25"),
            lifetime_drawdown_fraction=Decimal("0.25"),
        ),
    )
    assert hit.outcome == "pass"


def test_r018_denies_past_the_configured_lifetime_drawdown_boundary() -> None:
    hit = RULES_BY_ID["R-018"].check(
        _action(),
        _ctx(
            account_max_lifetime_drawdown=Decimal("0.25"),
            lifetime_drawdown_fraction=Decimal("0.2501"),
        ),
    )
    assert hit.outcome == "fail"


def test_r018_emits_not_configured_when_the_dial_is_disabled() -> None:
    hit = RULES_BY_ID["R-018"].check(
        _action(),
        _ctx(account_max_lifetime_drawdown=None, lifetime_drawdown_fraction=Decimal("0.10")),
    )
    assert hit.outcome == "not_configured"


def test_r018_denies_insufficient_context_when_configured_but_no_fraction_known() -> None:
    hit = RULES_BY_ID["R-018"].check(
        _action(), _ctx(account_max_lifetime_drawdown=Decimal("0.25"))
    )
    assert hit.outcome == "fail"
    assert hit.measured == "insufficient_context:lifetime_drawdown_fraction"


# ---------------------------------------------------------------------------
# Registry shape
# ---------------------------------------------------------------------------


def test_every_rule_id_r001_through_r018_is_registered_with_a_nonempty_why() -> None:
    expected = {f"R-{i:03d}" for i in range(1, 19)}
    assert set(RULES_BY_ID) == expected
    for rule in RULES_BY_ID.values():
        assert rule.why.strip(), f"{rule.id} has an empty WHY — Mike-facing text is mandatory"
