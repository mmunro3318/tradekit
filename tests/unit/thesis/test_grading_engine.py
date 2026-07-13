"""Grading-engine core (DESIGN §10.2, TD-9) — the arithmetic that decides
PASS/FAIL/VOID. Pre-built by Fable; P2 wires it into thesis.grade().

TEST-PATH EXCEPTION (ASSUMPTIONS 23): these tests import
tradekit.thesis._grading directly because the public verb doesn't exist yet.
When P2 lands grade(), re-point these through the public surface and add
_grading to the TID251 ban list — same commit.

Every rule here resolves ambiguity AGAINST the agent. That's not pessimism,
it's anti-gaming: any rule that can favor the agent in a corner case WILL be
farmed by an optimizing agent (§15 threat table).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradekit.contracts import Bar
from tradekit.thesis._grading import evaluate_criteria

T0 = datetime(2026, 3, 1, tzinfo=UTC)
TICK = Decimal("0.01")
HORIZON = T0 + timedelta(days=10)


def bar(day: int, o, h, lo, c) -> Bar:
    return Bar(
        ts_open=T0 + timedelta(days=day),
        open=Decimal(o), high=Decimal(h), low=Decimal(lo), close=Decimal(c),
        volume=Decimal("100"),
    )


def touch(cmp: str, value: str, by=HORIZON):
    return {"kind": "price_touch", "cmp": cmp, "value": value, "timeframe": "1d", "by": by}


def close_pred(cmp: str, value: str, by=HORIZON):
    return {"kind": "price_close", "cmp": cmp, "value": value, "timeframe": "1d", "by": by}


def run(bars, success, failure, invalidation=None, now=HORIZON, horizon=HORIZON):
    return evaluate_criteria(
        bars=bars, timeframe="1d", tick_size=TICK,
        success=success, failure=failure, invalidation=invalidation,
        horizon_end=horizon, now=now,
    )


# --- happy paths ---------------------------------------------------------


def test_target_touch_passes_at_first_trigger_bar() -> None:
    bars = [bar(0, "100", "102", "99", "101"), bar(1, "101", "106", "100", "104")]
    out = run(bars, [touch("gte", "105")], [touch("lte", "95")])
    assert out.result == "PASS" and out.triggered == "success"
    assert out.trigger_ts == T0 + timedelta(days=1), (
        "the DECIDING bar is day 1 (high 106 >= 105); grading must localize the trigger "
        "for audit (§10.2 'a grade is an auditable computation')"
    )


def test_stop_touch_fails() -> None:
    bars = [bar(0, "100", "101", "94", "95")]
    out = run(bars, [touch("gte", "105")], [touch("lte", "95")])
    assert out.result == "FAIL" and out.triggered == "failure"


# --- the conservative same-bar rules (the whole point) -------------------


def test_stop_and_target_same_bar_resolves_to_stop() -> None:
    # One huge bar sweeps both 95 and 105.
    bars = [bar(0, "100", "106", "94", "100")]
    out = run(bars, [touch("gte", "105")], [touch("lte", "95")])
    assert out.result == "FAIL", (
        "stop and target in the SAME bar must grade FAIL (stop-first, §10.2): intrabar "
        "order is unknowable from OHLC, and any agent-favorable resolution gets farmed"
    )
    assert out.ambiguous_bar is True


def test_invalidation_and_stop_same_bar_resolves_to_fail_not_void() -> None:
    invalidation = {"kind": "measurable", "predicate": close_pred("lte", "96")}
    bars = [bar(0, "100", "101", "94", "95")]  # close 95: stop touch AND invalidation close
    out = run(bars, [touch("gte", "105")], [touch("lte", "95")], invalidation=invalidation)
    assert out.result == "FAIL", (
        "same-bar failure+invalidation must FAIL, not VOID: VOID removes a loss from the "
        "win-rate stats — resolving toward VOID here is a free loss-eraser (§10.4)"
    )
    assert out.ambiguous_bar is True


def test_measurable_invalidation_alone_voids() -> None:
    invalidation = {"kind": "measurable", "predicate": close_pred("lte", "97")}
    bars = [bar(0, "100", "101", "96.5", "96.8")]  # closes 96.8: invalidation, stop(95) NOT touched
    out = run(bars, [touch("gte", "105")], [touch("lte", "95")], invalidation=invalidation)
    assert out.result == "VOID" and out.triggered == "invalidation"


# --- touch vs close semantics ---------------------------------------------


def test_wick_through_target_triggers_touch_but_not_close() -> None:
    bars = [bar(0, "100", "106", "99", "102")]  # wick to 106, closes 102
    assert run(bars, [touch("gte", "105")], []).result == "PASS"
    assert run(bars, [close_pred("gte", "105")], []).result == "FAIL", (
        "price_close must ignore the wick: high 106 but close 102 < 105 — horizon then "
        "expires -> FAIL. Conflating touch/close semantics regrades every wick"
    )


# --- time discipline -------------------------------------------------------


def test_pending_before_horizon_fail_after() -> None:
    bars = [bar(0, "100", "101", "99", "100")]
    mid = T0 + timedelta(days=2)
    assert run(bars, [touch("gte", "105")], [], now=mid).result == "PENDING"
    out = run(bars, [touch("gte", "105")], [], now=HORIZON)
    assert out.result == "FAIL" and out.triggered == "horizon_expiry", (
        "horizon expiry with no trigger is FAIL, not VOID (SME F1: 'horizon expired at "
        "loss = FAIL') — the prediction had its window and was wrong"
    )


def test_lookahead_guard_unclosed_bar_never_triggers() -> None:
    bars = [bar(0, "100", "106", "99", "104")]  # 1d bar closes at day 1
    during = T0 + timedelta(hours=12)  # bar still open
    out = run(bars, [touch("gte", "105")], [], now=during)
    assert out.result == "PENDING", (
        "a bar that hasn't CLOSED yet must not grade anything (§10.2 lookahead guard): "
        "its high/low/close are still moving — grading it is trading on the future"
    )


def test_predicate_level_deadline_expires_independently() -> None:
    early = T0 + timedelta(days=1)  # target only valid through day-0 bar (closes day 1)
    bars = [bar(0, "100", "101", "99", "100"), bar(3, "100", "106", "99", "104")]
    out = run(bars, [touch("gte", "105", by=early)], [])
    assert out.result == "FAIL" and out.triggered == "horizon_expiry", (
        "target touched on day 3 but its `by` deadline was day 1 — a dead predicate must "
        "not resurrect (per-predicate deadlines, §5.2)"
    )


def test_time_expiry_fires_when_deadline_reached_not_before() -> None:
    # `by` alone — the DSL forbids stray fields on time_expiry (§5.2)
    expiry = {"kind": "time_expiry", "by": T0 + timedelta(days=2)}
    bars = [bar(0, "100", "101", "99", "100"), bar(2, "100", "101", "99", "100")]
    out = run(bars, [touch("gte", "105")], [expiry])
    assert out.result == "FAIL" and out.triggered == "failure"
    assert out.trigger_ts == T0 + timedelta(days=2), (
        f"time_expiry fired at {out.trigger_ts}: it must trigger on the first bar CLOSING "
        "at/after its deadline (day-2 bar closes day 3 >= day 2) and never earlier — "
        "inverted deadline logic turns every timed exit into a dead predicate (§5.2)"
    )


# --- input validation -------------------------------------------------------


def test_mixed_timeframes_rejected() -> None:
    hourly = {"kind": "price_touch", "cmp": "gte", "value": "105", "timeframe": "1h", "by": HORIZON}
    with pytest.raises(ValueError, match="timeframe"):
        run([bar(0, "100", "101", "99", "100")], [hourly], [])


def test_unsorted_bars_rejected() -> None:
    bars = [bar(1, "100", "101", "99", "100"), bar(0, "100", "101", "99", "100")]
    with pytest.raises(ValueError, match="ascending"):
        run(bars, [touch("gte", "105")], [])
