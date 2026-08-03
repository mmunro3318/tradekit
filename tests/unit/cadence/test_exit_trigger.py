"""`tradekit.cadence.exit_trigger` -- T2's pure exit-trigger evaluation
(SPEC-cadence.md T2, "Exit TRIGGER evaluation"). NOT part of the gated
broker pipeline (`broker._pipeline.execute_exit` decides HOW to close a
position; this function only decides WHEN to flatten one, on the last
CLOSED bar / clock) -- see docs/specs/SPEC-cadence.md:98-104 for the
pinned semantics this file tests verbatim.

RED this batch: `tradekit.cadence` does not exist yet (T3 is the module's
producing task; T2 only needs this ONE pure function out of it, per the
spec's own scope note: "the trigger lives in the cadence module"). The
module-level import below is EXPECTED to fail -- ImportError/ModuleNotFound
is the correct red reason for every test in this file, not a stub-body
NotImplementedError (there is no stub; the module is simply absent).

ASSUMPTIONS FLAG (T2 dispatch escape hatch, flagged here per the RED-stage
protocol -- never improvised; CTO adjudicates into tests/ASSUMPTIONS.md,
next free entry 177 as of this red pass):
    The spec pins the trigger's THREE conditions (close<=stop -> "stop",
    close>=target -> "target", clock>=horizon_end -> "horizon") and the
    stop-vs-target tie-break ("stop wins"), but does NOT pin an exact
    function signature or parameter names/order. This file pins the
    MINIMAL pure form the spec's own prose implies -- five keyword
    parameters (`close`, `stop_price`, `target_price`, `now`,
    `horizon_end`), Decimal for the three prices, aware datetime for the
    two instants, returning `Literal["stop", "target", "horizon"] | None`
    -- no `long`/`short` direction parameter (SPEC-cadence.md's Scope
    explicitly excludes "short direction" this batch, 172/175 pins stand)
    and no `Bar`/`ThesisContract` object parameter (the spec's own
    algorithm only ever reads `close`, `stop_price`, `target_price`,
    `clock()`, and `horizon_end` -- a bar/contract parameter would be a
    wider surface than the three comparisons the spec actually performs).
    A GREEN dev pass that instead pins e.g. positional args, a
    `bar: Bar` parameter, or an explicit `long`/`short` `direction`
    parameter should update this file's calls to match, then note the
    reconciliation in tests/ASSUMPTIONS.md 177 -- not silently diverge.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tradekit.cadence import exit_trigger

_STOP = Decimal("57000.00")
_TARGET = Decimal("66000.00")
_MID = Decimal("60000.00")  # strictly between stop and target -- neither fires
_HORIZON_END = datetime(2026, 2, 15, tzinfo=UTC)
_BEFORE_HORIZON = datetime(2026, 2, 10, tzinfo=UTC)


def test_close_equal_to_stop_price_triggers_stop_inclusive_touch() -> None:
    """CONTRACT (T2-AC-4): close==stop_price is an INCLUSIVE touch, not a
    strict breach -> reason "stop"."""
    reason = exit_trigger(
        close=_STOP,
        stop_price=_STOP,
        target_price=_TARGET,
        now=_BEFORE_HORIZON,
        horizon_end=_HORIZON_END,
    )
    assert reason == "stop"


def test_close_equal_to_target_price_triggers_target_inclusive_touch() -> None:
    """CONTRACT (T2-AC-4): close==target_price is an INCLUSIVE touch ->
    reason "target"."""
    reason = exit_trigger(
        close=_TARGET,
        stop_price=_STOP,
        target_price=_TARGET,
        now=_BEFORE_HORIZON,
        horizon_end=_HORIZON_END,
    )
    assert reason == "target"


def test_close_hitting_both_stop_and_target_the_same_bar_prefers_stop() -> None:
    """CONTRACT (T2-AC-4): a degenerate bracket (stop==target==close, both
    conditions true simultaneously) resolves to "stop" -- conservative,
    mirroring grading's own ambiguous-bar stop-first doctrine (the spec's
    explicit worked case, not an inferred one)."""
    degenerate = Decimal("60000.00")
    reason = exit_trigger(
        close=degenerate,
        stop_price=degenerate,
        target_price=degenerate,
        now=_BEFORE_HORIZON,
        horizon_end=_HORIZON_END,
    )
    assert reason == "stop"


def test_clock_exactly_at_horizon_end_triggers_horizon() -> None:
    """CONTRACT (T2-AC-4): clock()==horizon_end exactly (inclusive) ->
    reason "horizon", when neither stop nor target has fired."""
    reason = exit_trigger(
        close=_MID,
        stop_price=_STOP,
        target_price=_TARGET,
        now=_HORIZON_END,
        horizon_end=_HORIZON_END,
    )
    assert reason == "horizon"


def test_no_trigger_condition_met_returns_none() -> None:
    """CONTRACT (T2-AC-4): a mid-band close, before horizon -> None (no
    trigger this bar)."""
    reason = exit_trigger(
        close=_MID,
        stop_price=_STOP,
        target_price=_TARGET,
        now=_BEFORE_HORIZON,
        horizon_end=_HORIZON_END,
    )
    assert reason is None


# --- Round-21 CTO additions (review finding 1): the boundary table above
# tests only EQUALITY touches -- an ==-mutant of the <=/>= comparisons
# survived it. These three pin the gap-through cases (the common
# real-world stop: a bar CLOSING strictly beyond the level).


def test_close_strictly_below_stop_gap_through_triggers_stop() -> None:
    """CONTRACT (T2-AC-4, round-21): a close that gaps THROUGH the stop
    (strictly below) must trigger -- an ==-only implementation would
    return None and the autonomous runner would never flatten."""
    reason = exit_trigger(
        close=_STOP - Decimal("500"),
        stop_price=_STOP,
        target_price=_TARGET,
        now=_BEFORE_HORIZON,
        horizon_end=_HORIZON_END,
    )
    assert reason == "stop"


def test_close_strictly_above_target_gap_through_triggers_target() -> None:
    """CONTRACT (T2-AC-4, round-21): mirror gap-through on the target side."""
    reason = exit_trigger(
        close=_TARGET + Decimal("500"),
        stop_price=_STOP,
        target_price=_TARGET,
        now=_BEFORE_HORIZON,
        horizon_end=_HORIZON_END,
    )
    assert reason == "target"


def test_now_strictly_past_horizon_end_triggers_horizon() -> None:
    """CONTRACT (T2-AC-4, round-21): a clock already PAST horizon_end (the
    normal case for an hourly runner waking up late) triggers, not just
    the exact-equality instant."""
    from datetime import timedelta

    reason = exit_trigger(
        close=_MID,
        stop_price=_STOP,
        target_price=_TARGET,
        now=_HORIZON_END + timedelta(hours=3),
        horizon_end=_HORIZON_END,
    )
    assert reason == "horizon"
