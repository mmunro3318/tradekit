"""SPRINT P2 done-gate — ring-3 adversarial replay suite (DESIGN §15 threat
table; SPRINT-P2-thesis-policy story 5). One scenario per §15 gaming vector,
each attacking the system the way a cooperative-but-uncalibrated LLM trading
agent would try to game it.

DISCIPLINE: these tests PASS iff the gates actually hold. Every scenario
drives the system through REAL verbs wherever possible — draft/submit/
approve/grade/void/policy.evaluate/halt/resume — reserving harness event
appends ONLY for the emissions P3 owns (ReviewCompleted, ThesisActivated,
FillRecorded) and for the sanctioned clock/bars monkeypatch seams
(`tradekit.mae._runtime._clock`/`get_closed_bars`, `tradekit.policy.
_context._clock`). A scenario that FAILS has found a real hole in the gate —
it is left failing and reported, never weakened.

§15-row -> test map (coverage honesty in tests/ASSUMPTIONS.md's batch-E
entry): VOID abuse -> R-015 (1); micro-trade series gaming -> R-008 (2);
window cherry-picking -> series arithmetic (3); revenge-sizing -> R-012 (4);
drawdown lockout incl. advisory F7 -> R-009 (5); in-process bypass / kill
switch -> R-001 (6); thesis prerequisites / fabricated id -> R-010 (7);
VOID sign-off leg -> void() (8); tampered history -> verify_chain (9).

Determinism (freeze-gate): no sleeps, no network, no real clock. Every
threshold's arithmetic is shown inline at the assertion that leans on it.
Fixtures reuse the proven ATR/predicate bar shapes from
`tests/unit/thesis/test_grade_verb.py` / `test_submit.py`, so a grading
fixture here reads the same way as the frozen core's own tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradekit import policy, thesis
from tradekit.contracts import AssetRef, Bar, BarSeries, EventFilter, OrderRequest, ProposedAction
from tradekit.ledger import default_ledger
from tradekit.policy._dials import PolicyDials
from tradekit.policy._rules import RULES_BY_ID
from tradekit.policy._series import series_index

# ---------------------------------------------------------------------------
# Shared fixtures / builders (house ring-3 style)
# ---------------------------------------------------------------------------

_ASSET = AssetRef(symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))

# Submit-phase bars: flat open=close=100, high=105/low=95 -> constant True
# Range 10 -> Wilder ATR(14) = 10 -> mae.size_position(equity=500) records
# recommended_size_usd = risk(1% * 500 = 5) / stop_pct(2*ATR/price = 20/100 =
# 0.20) = 25.00. Chosen so an HONEST order sits inside R-005's paper cap
# (10% * 500 = 50) and above R-008's floor (10) — the honest control clears.
_SUBMIT_START = datetime(2026, 1, 1, tzinfo=UTC)
_N_SUBMIT_BARS = 20

# Grading-phase window (day-aligned so lookback arithmetic is exact).
ACTIVATION_TS = datetime(2026, 3, 1, tzinfo=UTC)
GRADE_HORIZON = ACTIVATION_TS + timedelta(days=10)
GRADE_NOW = ACTIVATION_TS + timedelta(days=2)

# Policy "now" for every evaluate() — within 30d of the grade timestamps so
# trailing-30d drawdown reads the seeded grading history.
POLICY_NOW = datetime(2026, 3, 5, 12, 0, tzinfo=UTC)


def _submit_bars(n: int = _N_SUBMIT_BARS) -> BarSeries:
    bars = [
        Bar(
            ts_open=_SUBMIT_START + timedelta(days=i),
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("95"),
            close=Decimal("100"),
            volume=Decimal("1000"),
        )
        for i in range(n)
    ]
    return BarSeries(asset=_ASSET, timeframe="1d", bars=bars, source="fake-kraken")


def _fake_submit_bars(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
    return _submit_bars()


def _fake_submit_clock() -> datetime:
    return _SUBMIT_START + timedelta(days=_N_SUBMIT_BARS + 5)  # 2026-01-26


def _fake_grade_bars(bars: list[Bar]):
    def _f(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
        return BarSeries(asset=_ASSET, timeframe=timeframe, bars=bars, source="fake-kraken")

    return _f


# --- grading bar presets (default target 66000 / stop 57000, 1d predicates) ---
_PASS_BARS = [
    Bar(ts_open=ACTIVATION_TS, open=Decimal("60000"), high=Decimal("61000"),
        low=Decimal("59000"), close=Decimal("60500"), volume=Decimal("10")),
    Bar(ts_open=ACTIVATION_TS + timedelta(days=1), open=Decimal("61000"),
        high=Decimal("67000"), low=Decimal("60500"), close=Decimal("66500"),
        volume=Decimal("10")),  # high 67000 >= target 66000 -> PASS
]
_FAIL_BARS = [
    Bar(ts_open=ACTIVATION_TS, open=Decimal("58000"), high=Decimal("58500"),
        low=Decimal("56500"), close=Decimal("57000"), volume=Decimal("10")),
]  # low 56500 <= stop 57000 -> FAIL
_VOID_BARS = [
    # low 57200 > stop 57000 (failure low-touch does NOT fire); high 59500 <
    # target 66000 (success does not fire); close 57500 <= invalidation 58000
    # -> VOID alone (measurable invalidation, auto-eval, zero discretion).
    Bar(ts_open=ACTIVATION_TS, open=Decimal("59000"), high=Decimal("59500"),
        low=Decimal("57200"), close=Decimal("57500"), volume=Decimal("10")),
]

_STRUCTURAL_INVALIDATION = {
    "kind": "structural",
    "description": "Catalyst structurally broken: primary exchange delisted the pair.",
}
_VOID_INVALIDATION = {
    "kind": "measurable",
    "predicate": {"kind": "price_close", "cmp": "lte", "value": "58000.00",
                  "timeframe": "1d", "by": GRADE_HORIZON},
}


def _tf1d(kind: str, cmp: str, value: str, by: datetime = GRADE_HORIZON) -> dict:
    return {"kind": kind, "cmp": cmp, "value": value, "timeframe": "1d", "by": by}


def _thesis_kw(thesis_kwargs, *, account_ref="paper:alpha", invalidation=None, thesis_id=None):
    kw = dict(thesis_kwargs)
    if thesis_id is not None:
        kw["thesis_id"] = thesis_id
    kw["account_ref"] = account_ref
    kw["horizon_end"] = GRADE_HORIZON
    kw["target_price"] = Decimal("66000.00")
    kw["stop_price"] = Decimal("57000.00")
    kw["success_criteria"] = [_tf1d("price_touch", "gte", "66000.00")]
    kw["failure_criteria"] = [_tf1d("price_touch", "lte", "57000.00")]
    kw["invalidation"] = invalidation or {
        "kind": "measurable",
        "predicate": _tf1d("price_close", "lte", "40000.00"),  # never fires vs >=56k bars
    }
    return kw


def _pin_submit_seam(monkeypatch) -> None:
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_submit_bars)
    monkeypatch.setattr("tradekit.mae._runtime._clock", _fake_submit_clock)


def _pin_policy_clock(monkeypatch, now: datetime = POLICY_NOW) -> None:
    monkeypatch.setattr("tradekit.policy._context._clock", lambda: now)


def _review_completed(make_event, thesis_id: str, kind: str = "thesis_review"):
    return make_event(
        type="ReviewCompleted",
        payload={"thesis_id": thesis_id, "review_artifact_id": f"rev-{thesis_id}",
                 "passed": True, "kind": kind},
    )


def _honest_submitted(thesis_kwargs, monkeypatch, make_event, *, account_ref="paper:alpha") -> str:
    """draft -> submit -> ReviewCompleted(thesis_review): the minimal REAL
    state that EARNS an R-010/R-012 allow (submit records SizingComputed;
    review supplies the artifact). No approve/activate needed for policy."""
    _pin_submit_seam(monkeypatch)
    tid = thesis.draft(_thesis_kw(thesis_kwargs, account_ref=account_ref))
    thesis.submit(tid)
    default_ledger().append(_review_completed(make_event, tid))
    return tid


def _build_active(thesis_kwargs, monkeypatch, make_event, *, account_ref="paper:alpha",
                  invalidation=None) -> str:
    """draft -> submit -> ReviewCompleted -> approve -> ThesisActivated: a real
    thesis parked at `active`, ready to grade()."""
    _pin_submit_seam(monkeypatch)
    tid = thesis.draft(
        _thesis_kw(thesis_kwargs, account_ref=account_ref, invalidation=invalidation)
    )
    thesis.submit(tid)
    default_ledger().append(_review_completed(make_event, tid))
    thesis.approve(tid)
    default_ledger().append(
        make_event(
            type="ThesisActivated",
            payload={"thesis_id": tid, "order_id": f"ord-{tid}",
                     "ts_utc": ACTIVATION_TS.isoformat()},
            ts=ACTIVATION_TS,
        )
    )
    return tid


def _grade(monkeypatch, tid: str, bars: list[Bar], *, now: datetime) -> dict:
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_grade_bars(bars))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: now)
    return thesis.grade(tid)


def _graded(thesis_kwargs, monkeypatch, make_event, outcome: str, *, account_ref="paper:alpha",
            now: datetime, fills=None) -> str:
    """A full REAL graded thesis with the requested outcome (PASS/FAIL/VOID)."""
    if outcome == "VOID":
        invalidation, bars = _VOID_INVALIDATION, _VOID_BARS
    elif outcome == "PASS":
        invalidation, bars = None, _PASS_BARS
    elif outcome == "FAIL":
        invalidation, bars = None, _FAIL_BARS
    else:  # pragma: no cover — test author error
        raise ValueError(outcome)
    tid = _build_active(thesis_kwargs, monkeypatch, make_event,
                        account_ref=account_ref, invalidation=invalidation)
    for price, qty, fees, ts in fills or []:
        default_ledger().append(
            make_event(
                type="FillRecorded",
                ts=ts,
                payload={"order_id": "ord-fill", "thesis_id": tid, "ts_utc": ts.isoformat(),
                         "price": price, "qty": qty, "fees_usd": fees},
            )
        )
    _grade(monkeypatch, tid, bars, now=now)
    return tid


def _recorded_sizing_usd(tid: str) -> Decimal:
    for e in default_ledger().query(EventFilter(types=["SizingComputed"])):
        if e.payload.get("thesis_id") == tid:
            return Decimal(str(e.payload["sizing"]["recommended_size_usd"]))
    raise AssertionError(f"no SizingComputed for {tid!r}")


def _order(tid: str, *, account_ref="paper:alpha", notional: Decimal) -> OrderRequest:
    # qty 1 * limit = notional, so order notional is exactly `notional`.
    return OrderRequest(thesis_id=tid, account_ref=account_ref, asset=_ASSET, side="buy",
                        order_type="limit", qty=Decimal("1"), limit_price=Decimal(str(notional)))


def _submit_action(tid: str, *, account_ref="paper:alpha", notional: Decimal) -> ProposedAction:
    return ProposedAction(
        kind="submit_order", account_ref=account_ref, requested_by="agent:test",
        thesis_id=tid, order=_order(tid, account_ref=account_ref, notional=notional),
    )


def _hit(verdict, rule_id: str):
    return next(h for h in verdict.rule_hits if h.rule_id == rule_id)


def _failing_rule_ids(verdict) -> set[str]:
    return {h.rule_id for h in verdict.rule_hits if h.outcome == "fail"}


def _violations(rule_id: str | None = None):
    evs = default_ledger().query(EventFilter(types=["GateViolationDetected"]))
    return [e for e in evs if rule_id is None or e.payload.get("rule_id") == rule_id]


# ===========================================================================
# 1. VOID-farm  (§15 "VOID abuse" -> R-015)
# ===========================================================================


def test_void_farm_25pct_voids_blocks_new_submission_via_r015(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    """Gaming story: an agent grades its losers and VOIDs 5 of its last 20 to
    keep the win-rate stats clean. Gate: R-015 caps trailing void-rate at 20%
    — 5/20 = 0.25 > 0.20 blocks the next otherwise-honest submission."""
    outcomes = ["VOID"] * 5 + ["PASS"] * 10 + ["FAIL"] * 5  # 20 graded, 5 void
    for i, o in enumerate(outcomes):
        _graded(thesis_kwargs, monkeypatch, make_event, o,
                now=GRADE_NOW + timedelta(minutes=i))

    tid = _honest_submitted(thesis_kwargs, monkeypatch, make_event)
    _pin_policy_clock(monkeypatch)
    verdict = policy.evaluate(_submit_action(tid, notional=_recorded_sizing_usd(tid)))

    # void_rate = 5 / 20 = 0.25 ; cap = 0.20 ; 0.25 > 0.20 -> deny.
    r015 = _hit(verdict, "R-015")
    assert r015.outcome == "fail"
    assert Decimal(r015.measured) == Decimal("0.25")
    assert verdict.allow is False
    assert _failing_rule_ids(verdict) == {"R-015"}, (
        "an otherwise-honest submission (real thesis, matched sizing, present review) must be "
        "blocked SOLELY by the VOID-rate audit — nothing else about it is wrong"
    )
    assert [v.payload["rule_id"] for v in _violations("R-015")] == ["R-015"], (
        "the R-015 denial must be ledgered as a GateViolationDetected — never silent (§7.2)"
    )


def test_void_farm_boundary_20pct_voids_passes_r015(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    """Positive control: exactly 4/20 = 0.20 voids sits AT the cap (<=), so
    R-015 permits the submission — the gate denies gaming, not honest voids."""
    outcomes = ["VOID"] * 4 + ["PASS"] * 11 + ["FAIL"] * 5  # 20 graded, 4 void
    for i, o in enumerate(outcomes):
        _graded(thesis_kwargs, monkeypatch, make_event, o,
                now=GRADE_NOW + timedelta(minutes=i))

    tid = _honest_submitted(thesis_kwargs, monkeypatch, make_event)
    _pin_policy_clock(monkeypatch)
    verdict = policy.evaluate(_submit_action(tid, notional=_recorded_sizing_usd(tid)))

    # void_rate = 4 / 20 = 0.20 ; cap = 0.20 ; 0.20 <= 0.20 -> pass.
    r015 = _hit(verdict, "R-015")
    assert r015.outcome == "pass"
    assert Decimal(r015.measured) == Decimal("0.20")
    assert verdict.allow is True, "at the boundary an honest submission clears every gate"
    assert _violations("R-015") == []


# ===========================================================================
# 2. Micro-series gaming  (§15 "Micro-trade series gaming" -> R-008)
# ===========================================================================


def test_micro_series_ten_two_dollar_orders_each_denied_by_r008(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    """Gaming story: manufacture a long clean series out of ten $2 trades that
    fee-noise cannot meaningfully grade. Gate: R-008 min-notional $10 denies
    EVERY one, and every denial is ledgered (none silent)."""
    _pin_policy_clock(monkeypatch)
    for i in range(10):
        tid = f"TH-MICRO-{i}"
        action = ProposedAction(
            kind="submit_order", account_ref="paper:alpha", requested_by="agent:test",
            thesis_id=tid, order=_order(tid, notional=Decimal("2.00")),
        )
        verdict = policy.evaluate(action)  # order notional = 1 * 2.00 = 2.00
        assert verdict.allow is False
        r008 = _hit(verdict, "R-008")
        assert r008.outcome == "fail"  # 2.00 < 10 min_notional -> deny
        assert r008.measured == "2.00"

    r008_violations = _violations("R-008")
    assert len(r008_violations) == 10, (
        "ten $2 submissions -> ten R-008 GateViolationDetected events; the micro-series "
        "gaming vector is denied on every attempt, never once let through silently"
    )


# ===========================================================================
# 3. Window cherry-picking  (§15 -> impossible by construction)
# ===========================================================================


def test_window_cherry_picking_series_assignment_is_pure_timestamp_arithmetic(
) -> None:
    """Gaming story: reassign a graded thesis into a friendlier 30-day series
    window. Impossible by construction — series membership is pure UTC calendar
    arithmetic keyed on the immutable grade timestamp, and NO public verb can
    mutate it. A grade history shifted by +/-1s across a boundary lands
    deterministically in adjacent series, with no way to nudge it back."""
    epoch = PolicyDials().series_epoch  # 2026-01-01T00:00Z
    boundary = epoch + timedelta(days=30)  # start of series 1 (right-open windows)

    # floor((grade_ts - epoch) / 30d): boundary exactly -> 1, boundary-1s -> 0.
    assert series_index(epoch, epoch) == 0
    assert series_index(boundary, epoch) == 1
    assert series_index(boundary - timedelta(seconds=1), epoch) == 0
    assert series_index(boundary + timedelta(seconds=1), epoch) == 1
    assert series_index(epoch - timedelta(seconds=1), epoch) == -1, (
        "windows floor toward -inf, so a grade one second before the epoch is series -1, "
        "not clamped to 0 — no arithmetic seam to exploit"
    )
    # Same history, ±1s around a boundary -> adjacent series (0 vs 1); the shift
    # cannot land it two windows away or back where it started.
    assert series_index(boundary - timedelta(seconds=1), epoch) + 1 == series_index(
        boundary + timedelta(seconds=1), epoch
    )

    # No series-mutating verb exists on the public surfaces (freeze the sets:
    # a future `reassign_series`/`set_series` would break these).
    assert set(policy.__all__) == {
        "PromotionRefused", "confirm_promotion", "evaluate", "halt",
        "promotion_status", "resume", "status",
    }
    assert set(thesis.__all__) == {
        "IllegalTransition", "VoidRefused", "approve", "draft", "grade",
        "reject", "submit", "void",
    }
    assert not any("series" in name.lower() for name in (*policy.__all__, *thesis.__all__)), (
        "no public verb references 'series' at all — series accounting is read-derived from "
        "the grade-timestamp arithmetic above, never a settable attribute"
    )


# ===========================================================================
# 4. Revenge-sizing  (§15 "Revenge-sizing after losses" -> R-012)
# ===========================================================================


def test_revenge_sizing_2x_denied_by_r012_control_within_tolerance_passes(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    """Gaming story: after a loss, submit an order 2x the size its own sizing
    model computed to 'make it back'. Gate: R-012 sizing-purity denies any
    order deviating > 1% from the recorded SizingComputed output. Positive
    control: an order matching the recorded size clears R-012."""
    tid = _honest_submitted(thesis_kwargs, monkeypatch, make_event)
    recorded = _recorded_sizing_usd(tid)  # real mae.size_position output = 25.00
    _pin_policy_clock(monkeypatch)

    # Positive control: notional == recorded -> deviation 0 <= 0.01 tolerance.
    ok = policy.evaluate(_submit_action(tid, notional=recorded))
    assert _hit(ok, "R-012").outcome == "pass"
    assert ok.allow is True, "an honestly-sized order clears every gate"

    # Revenge: notional = 2 * recorded -> deviation |50 - 25| / 25 = 1.0 > 0.01.
    bad = policy.evaluate(_submit_action(tid, notional=recorded * 2))
    r012 = _hit(bad, "R-012")
    assert r012.outcome == "fail"
    assert Decimal(r012.measured) == Decimal("1")
    assert _failing_rule_ids(bad) == {"R-012"}, (
        "doubling the size trips sizing purity and nothing else — the deviation is the whole "
        "attack, and R-012 is the whole defense"
    )
    assert [v.payload["rule_id"] for v in _violations("R-012")] == ["R-012"]


# ===========================================================================
# 5. Drawdown breach mid-series  (§15 "Revenge-sizing/drawdown" -> R-009, F7)
# ===========================================================================


def _drawdown_fills():
    """Two fills yielding a LONG round-trip pnl of -60.00 (net of zero fees):
    (54000 - 60000) * 0.01 = -60.00 -> equity 500 -> 440 -> drawdown
    (500 - 440) / 500 = 0.12 >= the 0.10 breaker."""
    return [
        ("60000.00", "0.01", "0", ACTIVATION_TS),
        ("54000.00", "0.01", "0", ACTIVATION_TS + timedelta(days=1)),
    ]


def test_drawdown_breach_locks_out_new_paper_position_via_r009(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    """Gaming story: keep opening positions while down 12% on the series,
    compounding a losing streak. Gate: R-009 blocks new positions once the
    trailing-30d drawdown reaches 10%."""
    _graded(thesis_kwargs, monkeypatch, make_event, "FAIL",
            account_ref="paper:alpha", now=GRADE_NOW, fills=_drawdown_fills())

    tid = _honest_submitted(thesis_kwargs, monkeypatch, make_event)
    _pin_policy_clock(monkeypatch)
    verdict = policy.evaluate(_submit_action(tid, notional=_recorded_sizing_usd(tid)))

    r009 = _hit(verdict, "R-009")
    assert r009.outcome == "fail"
    assert Decimal(r009.measured) == Decimal("0.12")  # 60 / 500 peak-to-trough
    assert verdict.allow is False
    assert _failing_rule_ids(verdict) == {"R-009"}, (
        "a 12% drawdown locks out the next position by itself — the account is otherwise in "
        "good standing, which is exactly when an agent is tempted to keep going"
    )
    assert [v.payload["rule_id"] for v in _violations("R-009")] == ["R-009"]


def test_drawdown_breach_locks_out_advisory_account_too_f7(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    """F7: the SAME 10% drawdown breaker applies to advisory ('advisory:...')
    accounts — a human in the loss-recovery-bias zone is exactly who the
    breaker exists for. Same -12% history on an advisory account still trips
    R-009 on the next submission."""
    _graded(thesis_kwargs, monkeypatch, make_event, "FAIL",
            account_ref="advisory:mike", now=GRADE_NOW, fills=_drawdown_fills())

    _pin_policy_clock(monkeypatch)
    action = _submit_action("TH-ADVISORY-NEW", account_ref="advisory:mike",
                            notional=Decimal("25"))
    verdict = policy.evaluate(action)

    r009 = _hit(verdict, "R-009")
    assert r009.outcome == "fail"
    assert Decimal(r009.measured) == Decimal("0.12")  # advisory equity curve: 500 -> 440
    assert any(v.payload["rule_id"] == "R-009" for v in _violations("R-009")), (
        "advisory accounts are NOT exempt from the drawdown breaker (F7) — the denial is "
        "ledgered like any other"
    )


# ===========================================================================
# 6. Kill switch  (§15 "Agent bypasses gates in-process" -> R-001)
# ===========================================================================


def test_kill_switch_halt_denies_every_mutating_action_resume_restores(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    """Gaming story: keep trading through a 'something is wrong, stop' halt.
    Gate: R-001 denies EVERY mutating action while a HaltSet is unresolved
    (verified against R-001's own applies_to set), non-mutating status() still
    works, and resume() restores the gate to passing."""
    _pin_policy_clock(monkeypatch)
    mutating = RULES_BY_ID["R-001"].applies_to  # {submit_order, cancel, promote, void}

    policy.halt("emergency: reconcile mismatch under investigation")

    for kind in sorted(mutating):
        order = _order("TH-HALT", notional=Decimal("25")) if kind == "submit_order" else None
        action = ProposedAction(kind=kind, account_ref="paper:alpha",
                                requested_by="agent:test", thesis_id="TH-HALT", order=order)
        verdict = policy.evaluate(action)
        r001 = _hit(verdict, "R-001")
        assert r001.outcome == "fail", f"R-001 must deny mutating kind {kind!r} while halted"
        assert r001.measured == "halted"
        assert verdict.allow is False

    assert any(v.payload["rule_id"] == "R-001" for v in _violations("R-001")), (
        "every halted-action denial is ledgered as a GateViolationDetected"
    )

    # Non-mutating status() is unaffected by the kill switch.
    snap = policy.status()
    assert snap["halted"] is True
    assert snap["halt_reason"] == "emergency: reconcile mismatch under investigation"

    policy.resume()

    ok = policy.evaluate(
        ProposedAction(kind="submit_order", account_ref="paper:alpha",
                       requested_by="agent:test", thesis_id="TH-HALT",
                       order=_order("TH-HALT", notional=Decimal("25")))
    )
    assert _hit(ok, "R-001").outcome == "pass", (
        "resume() clears the halt — the SAME action R-001 denied a moment ago now passes R-001"
    )


# ===========================================================================
# 7. Fabricated thesis-id  (§15 thesis prerequisites -> R-010) — closed hole
# ===========================================================================


def test_fabricated_never_drafted_thesis_id_denied_by_r010(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    """Regression-pin at ring 3 for the ASSUMPTIONS 81 hole (now closed): a
    submit_order citing a thesis_id the ledger has NEVER seen must deny via
    R-010 with insufficient_context — never a silent/vacuous pass."""
    _pin_policy_clock(monkeypatch)
    action = _submit_action("TH-GHOST-NEVER-DRAFTED", notional=Decimal("25"))
    verdict = policy.evaluate(action)

    assert verdict.allow is False
    r010 = _hit(verdict, "R-010")
    assert r010.outcome == "fail"
    assert "insufficient_context" in (r010.measured or ""), (
        "the prerequisite fields (review artifact / snapshot / EV) are absent for a "
        "never-drafted thesis — R-010 denies anti-permissively, not silently"
    )
    assert any(v.payload["rule_id"] == "R-010" for v in _violations("R-010"))


# ===========================================================================
# 8. VOID without sign-off  (§10.4 leg 2 -> void())
# ===========================================================================


def test_void_without_reviewer_signoff_refused_attestation_kept_grade_still_works(
    thesis_kwargs, monkeypatch, make_event, raw_sql
) -> None:
    """Gaming story: talk your way to a VOID on a loser using a structural
    attestation but skipping the reviewer sign-off. Gate: void() refuses
    (VoidRefused), the attestation event REMAINS as the audit trail of the
    refusal, the thesis state is unchanged (still active), and a subsequent
    HONEST grade() still produces a real outcome."""
    tid = _build_active(thesis_kwargs, monkeypatch, make_event,
                        invalidation=_STRUCTURAL_INVALIDATION)

    with pytest.raises(thesis.VoidRefused):
        thesis.void(tid, "exchange delisted BTC/USD, catalyst is structurally dead")

    attested = [e for e in default_ledger().query(EventFilter(types=["InvalidationAttested"]))
                if e.payload.get("thesis_id") == tid]
    assert len(attested) == 1, "the attestation stands as the audit trail of a REFUSED void (§10.4)"
    assert attested[0].payload["kind"] == "structural"
    assert [e for e in default_ledger().query(EventFilter(types=["ThesisGraded"]))
            if e.payload.get("thesis_id") == tid] == [], "a refused void appends no ThesisGraded"

    default_ledger().rebuild()
    rows = raw_sql("SELECT state FROM theses WHERE thesis_id = ?", tid)
    assert rows[0][0] == "active", (
        "state is unchanged by a refused void — InvalidationAttested is not a lifecycle transition"
    )

    # The honest path still works: a real grade() on the still-active thesis.
    _grade(monkeypatch, tid, _PASS_BARS, now=GRADE_NOW)
    graded = [e for e in default_ledger().query(EventFilter(types=["ThesisGraded"]))
              if e.payload.get("thesis_id") == tid]
    assert len(graded) == 1 and graded[0].payload["outcome"] == "PASS", (
        "refusing the void does not brick the thesis — it grades honestly through the frozen core"
    )


# ===========================================================================
# 9. Tamper-evidence  (§15 "Tampered history" -> verify_chain)
# ===========================================================================


def test_tampered_event_row_is_detected_by_verify_chain(
    thesis_kwargs, monkeypatch, make_event, raw_sql
) -> None:
    """Gaming story: silently rewrite a ledgered event (e.g. flip a denial into
    an allow) after the fact. Gate: the hash chain detects it — verify_chain()
    passes on an untouched history, then reports the exact broken seq after a
    raw-sqlite row edit."""
    tid = _honest_submitted(thesis_kwargs, monkeypatch, make_event)
    _pin_policy_clock(monkeypatch)
    policy.evaluate(_submit_action(tid, notional=_recorded_sizing_usd(tid)))

    assert default_ledger().verify_chain().ok, "a clean scenario history must verify"

    # Corrupt one row out-of-band (the house raw_sql tamper pattern).
    raw_sql("UPDATE events SET payload = ? WHERE seq = 2", '{"tampered": true}')

    report = default_ledger().verify_chain()
    assert report.ok is False, "a rewritten payload must break the hash chain"
    assert report.first_bad_seq == 2, "verify_chain localizes the break to the tampered seq"
