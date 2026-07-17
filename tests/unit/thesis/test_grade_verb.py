"""`thesis.grade` wiring — the public verb around the FROZEN `_grading`
arithmetic core (DESIGN §10.2/§10.3, SPRINT P2 batch B, CTO addendum story-2
pins). This is the Opus-gated grading path: `_grading.evaluate_criteria`
itself is NEVER touched here (tests/unit/thesis/test_grading_engine.py stays
the fraction-exact pin, unmodified — see the ASSUMPTIONS 23 update this batch
adds), only the VERB that fetches bars, calls the core, and ledgers the
result.

Status: `thesis.grade` is still an unconditional `NotImplementedError` stub
this batch (batch dispatch: "Failing tests + stubs only") — every test below
is RED for that reason. Assertions describe the REAL behavior the dev pass
implements next.

Runtime determinism, same pattern as `test_submit.py`: bars are faked by
monkeypatching `"tradekit.mae._runtime.get_closed_bars"` by dotted STRING
path, the clock via `"tradekit.mae._runtime._clock"`. Building a thesis up to
`active` still runs the REAL `submit()` (which internally calls
`get_closed_bars`/`mae.size_position`), so every helper here first installs a
generic ATR-friendly bar fixture for that phase, then tests that care about
grading install their OWN fake (monkeypatch stacking: the later `setattr`
wins for subsequent calls) with bars shaped for the specific rule under test.

Fixture-freeze arithmetic is shown inline, at each assertion that needs it
(fixtures here are short enough that a derivation script wasn't needed — the
sprint's "beyond two-line arithmetic" threshold).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradekit import thesis
from tradekit.contracts import AssetRef, Bar, BarSeries, EventFilter
from tradekit.ledger import default_ledger

_ASSET = AssetRef(symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))

# --- submit-phase bar fixture (reused, unmodified, from test_submit.py's
# proven ATR(14) derivation: flat high=101/low=99/open=close=100 bars -> a
# constant True Range of 2.0 on every bar -> Wilder ATR(14) = 2.0 forever) ---
_SUBMIT_BAR_START = datetime(2026, 1, 1, tzinfo=UTC)
_N_SUBMIT_BARS = 20


def _flat_atr2_price100_bars(n: int = _N_SUBMIT_BARS) -> BarSeries:
    bars = [
        Bar(
            ts_open=_SUBMIT_BAR_START + timedelta(days=i),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=Decimal("1000"),
        )
        for i in range(n)
    ]
    return BarSeries(asset=_ASSET, timeframe="1d", bars=bars, source="fake-kraken")


def _fake_submit_get_closed_bars(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
    return _flat_atr2_price100_bars()


def _fake_submit_clock() -> datetime:
    return _SUBMIT_BAR_START + timedelta(days=_N_SUBMIT_BARS + 5)  # 2026-01-25, well-formed "now"


# --- grading-phase fixtures: day-aligned so lookback-window arithmetic (test
# 13 below) is EXACT, not approximate ---
ACTIVATION_TS = datetime(2026, 3, 1, tzinfo=UTC)
GRADE_HORIZON = ACTIVATION_TS + timedelta(days=10)


def _tf1d(kind: str, cmp: str, value: str, by: datetime = GRADE_HORIZON) -> dict:
    return {"kind": kind, "cmp": cmp, "value": value, "timeframe": "1d", "by": by}


def _grade_thesis_kwargs(
    thesis_kwargs: dict,
    *,
    invalidation: dict | None = None,
    horizon: datetime = GRADE_HORIZON,
    success_criteria: list[dict] | None = None,
    failure_criteria: list[dict] | None = None,
) -> dict:
    """Override the default (1h-timeframe) thesis_kwargs fixture with a
    single 1d-timeframe predicate set (ASSUMPTIONS 24: one timeframe per
    thesis) that matches `tests/unit/thesis/test_grading_engine.py`'s own bar
    convention, so grading fixtures here read the same way as the frozen
    core's own tests. Invalidation defaults to a measurable predicate whose
    threshold (40000.00) sits comfortably below every OTHER bar fixture in
    this file (all >= 56000) so it never cross-triggers a test that isn't
    about invalidation."""
    kw = dict(thesis_kwargs)
    kw["horizon_end"] = horizon
    kw["target_price"] = Decimal("66000.00")
    kw["stop_price"] = Decimal("57000.00")
    kw["success_criteria"] = success_criteria or [
        _tf1d("price_touch", "gte", "66000.00", by=horizon)
    ]
    kw["failure_criteria"] = failure_criteria or [
        _tf1d("price_touch", "lte", "57000.00", by=horizon)
    ]
    kw["invalidation"] = invalidation or {
        "kind": "measurable",
        "predicate": _tf1d("price_close", "lte", "40000.00", by=horizon),
    }
    return kw


def _events(event_type: str):
    return default_ledger().query(EventFilter(types=[event_type]))


def _thesis_events(event_type: str, thesis_id: str):
    return [e for e in _events(event_type) if e.payload.get("thesis_id") == thesis_id]


def _build_to_state(
    thesis_kwargs, monkeypatch, make_event, state: str, *, invalidation: dict | None = None
) -> str:
    """Reach `state` ∈ {draft, submitted, reviewed, approved} via the REAL
    draft/submit/approve verbs + harness-appended ReviewCompleted (P2 has no
    review verb — CTO addendum), stopping short of ThesisActivated."""
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_submit_get_closed_bars)
    monkeypatch.setattr("tradekit.mae._runtime._clock", _fake_submit_clock)
    kw = _grade_thesis_kwargs(thesis_kwargs, invalidation=invalidation)
    thesis_id = thesis.draft(kw)
    if state == "draft":
        return thesis_id
    thesis.submit(thesis_id)
    if state == "submitted":
        return thesis_id
    default_ledger().append(
        make_event(
            type="ReviewCompleted",
            payload={"thesis_id": thesis_id, "review_artifact_id": "rev-1", "passed": True},
        )
    )
    if state == "reviewed":
        return thesis_id
    thesis.approve(thesis_id)
    if state == "approved":
        return thesis_id
    raise ValueError(f"unhandled state {state!r}")


def _build_active_thesis(
    thesis_kwargs,
    monkeypatch,
    make_event,
    *,
    invalidation: dict | None = None,
    activation_ts: datetime = ACTIVATION_TS,
    order_id: str = "ord-1",
    success_criteria: list[dict] | None = None,
    failure_criteria: list[dict] | None = None,
) -> str:
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_submit_get_closed_bars)
    monkeypatch.setattr("tradekit.mae._runtime._clock", _fake_submit_clock)
    kw = _grade_thesis_kwargs(
        thesis_kwargs,
        invalidation=invalidation,
        success_criteria=success_criteria,
        failure_criteria=failure_criteria,
    )
    thesis_id = thesis.draft(kw)
    thesis.submit(thesis_id)
    default_ledger().append(
        make_event(
            type="ReviewCompleted",
            payload={"thesis_id": thesis_id, "review_artifact_id": "rev-1", "passed": True},
        )
    )
    thesis.approve(thesis_id)
    default_ledger().append(
        make_event(
            type="ThesisActivated",
            payload={
                "thesis_id": thesis_id,
                "order_id": order_id,
                "ts_utc": activation_ts.isoformat(),
            },
            ts=activation_ts,
        )
    )
    return thesis_id


def _build_active_thesis_with_horizon(
    thesis_kwargs,
    monkeypatch,
    make_event,
    *,
    horizon: datetime,
    activation_ts: datetime = ACTIVATION_TS,
) -> str:
    """Same as `_build_active_thesis` but threads a non-default `horizon`
    through `_grade_thesis_kwargs` — split out because `_build_to_state`
    doesn't take a horizon parameter and every OTHER test in this file is
    happy with the module default `GRADE_HORIZON`."""
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_submit_get_closed_bars)
    monkeypatch.setattr("tradekit.mae._runtime._clock", _fake_submit_clock)
    kw = _grade_thesis_kwargs(thesis_kwargs, horizon=horizon)
    thesis_id = thesis.draft(kw)
    thesis.submit(thesis_id)
    default_ledger().append(
        make_event(
            type="ReviewCompleted",
            payload={"thesis_id": thesis_id, "review_artifact_id": "rev-1", "passed": True},
        )
    )
    thesis.approve(thesis_id)
    default_ledger().append(
        make_event(
            type="ThesisActivated",
            payload={
                "thesis_id": thesis_id,
                "order_id": "ord-1",
                "ts_utc": activation_ts.isoformat(),
            },
            ts=activation_ts,
        )
    )
    return thesis_id


def _fake_grade_bars(bars: list[Bar]):
    def _fake(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
        return BarSeries(asset=_ASSET, timeframe=timeframe, bars=bars, source="fake-kraken")

    return _fake


# ---------------------------------------------------------------------------
# 1. State gate
# ---------------------------------------------------------------------------


def test_grade_on_draft_raises_illegal_transition(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    thesis_id = _build_to_state(thesis_kwargs, monkeypatch, make_event, "draft")
    with pytest.raises(thesis.IllegalTransition) as exc:
        thesis.grade(thesis_id)
    assert exc.value.current_state == "draft"
    assert exc.value.verb == "grade"


def test_grade_on_submitted_raises_illegal_transition(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    thesis_id = _build_to_state(thesis_kwargs, monkeypatch, make_event, "submitted")
    with pytest.raises(thesis.IllegalTransition) as exc:
        thesis.grade(thesis_id)
    assert exc.value.current_state == "submitted"


def test_grade_on_approved_not_yet_active_raises_illegal_transition(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    # CTO addendum story-2 pin: "active only; flag if a test seems to need
    # otherwise" — approved (pre-activation) is explicitly NOT gradeable.
    thesis_id = _build_to_state(thesis_kwargs, monkeypatch, make_event, "approved")
    with pytest.raises(thesis.IllegalTransition) as exc:
        thesis.grade(thesis_id)
    assert exc.value.current_state == "approved"


def test_grade_on_already_graded_thesis_raises_illegal_transition_terminal(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    thesis_id = _build_active_thesis(thesis_kwargs, monkeypatch, make_event)
    bars = [
        Bar(
            ts_open=ACTIVATION_TS,
            open=Decimal("60000"),
            high=Decimal("61000"),
            low=Decimal("59000"),
            close=Decimal("60500"),
            volume=Decimal("10"),
        ),
        Bar(
            ts_open=ACTIVATION_TS + timedelta(days=1),
            open=Decimal("61000"),
            high=Decimal("67000"),
            low=Decimal("60500"),
            close=Decimal("66500"),
            volume=Decimal("10"),
        ),
    ]
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_grade_bars(bars))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: ACTIVATION_TS + timedelta(days=2))

    thesis.grade(thesis_id)  # first grade: PASS (see happy-path test below)

    with pytest.raises(thesis.IllegalTransition) as exc:
        thesis.grade(thesis_id)
    assert exc.value.current_state == "PASS", (
        "a graded thesis is TERMINAL — `_machine.derive_state` reads the outcome off the "
        "ThesisGraded event itself, so a second grade() must name the outcome ('PASS') as "
        "the current_state, not 'active' or 'graded'"
    )


# ---------------------------------------------------------------------------
# 2-4. Happy paths + the subtlest rule (same-bar ambiguity)
# ---------------------------------------------------------------------------


def test_happy_pass_emits_thesis_graded_with_measured_values_and_bar_refs(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    thesis_id = _build_active_thesis(thesis_kwargs, monkeypatch, make_event)
    bars = [
        Bar(  # day 0: neither target nor stop touched
            ts_open=ACTIVATION_TS,
            open=Decimal("60000"),
            high=Decimal("61000"),
            low=Decimal("59000"),
            close=Decimal("60500"),
            volume=Decimal("10"),
        ),
        Bar(  # day 1: high 67000 >= target 66000 -> PASS, deciding bar
            ts_open=ACTIVATION_TS + timedelta(days=1),
            open=Decimal("61000"),
            high=Decimal("67000"),
            low=Decimal("60500"),
            close=Decimal("66500"),
            volume=Decimal("10"),
        ),
    ]
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_grade_bars(bars))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: ACTIVATION_TS + timedelta(days=2))

    result = thesis.grade(thesis_id)

    graded = _thesis_events("ThesisGraded", thesis_id)
    assert len(graded) == 1, "grade() must append exactly one ThesisGraded event"
    payload = graded[0].payload
    assert payload["outcome"] == "PASS"
    assert payload["ambiguous_bar"] is False
    assert any(m["category"] == "success" for m in payload["measured"]), (
        "ThesisGraded.measured must carry the frozen core's per-predicate evaluated list "
        "verbatim (§10.2 'every predicate's measured value + bar refs')"
    )
    assert all("bar_ts_open" in m for m in payload["measured"]), (
        "every measured entry must carry a bar reference for auditability"
    )
    assert result["outcome"] == "PASS", (
        "grade() returns the ThesisGraded payload it just appended (same convention as "
        "draft() returning the id it just minted)"
    )

    default_ledger().rebuild()


def test_happy_fail_when_failure_predicate_triggers_first(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    thesis_id = _build_active_thesis(thesis_kwargs, monkeypatch, make_event)
    bars = [
        Bar(  # low 56500 <= stop 57000 -> FAIL; high 58500 nowhere near target
            ts_open=ACTIVATION_TS,
            open=Decimal("58000"),
            high=Decimal("58500"),
            low=Decimal("56500"),
            close=Decimal("57000"),
            volume=Decimal("10"),
        ),
    ]
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_grade_bars(bars))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: ACTIVATION_TS + timedelta(days=1))

    thesis.grade(thesis_id)

    payload = _thesis_events("ThesisGraded", thesis_id)[0].payload
    assert payload["outcome"] == "FAIL"
    assert any(m["category"] == "failure" for m in payload["measured"])


def test_same_bar_stop_and_target_grades_fail_with_ambiguous_bar_true(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    """THE subtlest rule (sprint doc: "write this test FIRST"). One bar
    sweeps both the target (high 67000 >= 66000) and the stop (low 56000 <=
    57000) -> the frozen core resolves failure > success (conservative,
    stop-first) -> FAIL with ambiguous_bar=True. This test pins that the
    VERB carries `ambiguous_bar` through into ThesisGraded, unchanged."""
    thesis_id = _build_active_thesis(thesis_kwargs, monkeypatch, make_event)
    bars = [
        Bar(
            ts_open=ACTIVATION_TS,
            open=Decimal("60000"),
            high=Decimal("67000"),
            low=Decimal("56000"),
            close=Decimal("60000"),
            volume=Decimal("10"),
        ),
    ]
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_grade_bars(bars))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: ACTIVATION_TS + timedelta(days=1))

    thesis.grade(thesis_id)

    payload = _thesis_events("ThesisGraded", thesis_id)[0].payload
    assert payload["outcome"] == "FAIL", (
        "stop+target in the SAME bar resolves to FAIL (stop-first, §10.2) — the intrabar "
        "order is unknowable from OHLC and any agent-favorable resolution gets farmed"
    )
    assert payload["ambiguous_bar"] is True, (
        "the verb must surface ambiguous_bar=True unchanged from CriteriaOutcome — this is "
        "the primary anti-gaming signal an auditor looks for"
    )


# ---------------------------------------------------------------------------
# 5. Horizon expiry
# ---------------------------------------------------------------------------


def test_horizon_expiry_with_nothing_triggered_grades_fail(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    thesis_id = _build_active_thesis(thesis_kwargs, monkeypatch, make_event)
    bars = [
        Bar(  # stays strictly between stop (57000) and target (66000) the whole time
            ts_open=ACTIVATION_TS,
            open=Decimal("60000"),
            high=Decimal("61000"),
            low=Decimal("59000"),
            close=Decimal("60000"),
            volume=Decimal("10"),
        ),
    ]
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_grade_bars(bars))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: GRADE_HORIZON)  # now >= horizon_end

    thesis.grade(thesis_id)

    payload = _thesis_events("ThesisGraded", thesis_id)[0].payload
    assert payload["outcome"] == "FAIL", (
        "horizon expiry with nothing triggered is FAIL, not VOID/PENDING (SME F1: 'horizon "
        "expired at loss = FAIL')"
    )


# ---------------------------------------------------------------------------
# 6. Measurable invalidation -> VOID (auto-eval, zero discretion)
# ---------------------------------------------------------------------------


def test_measurable_invalidation_triggers_void_via_grade(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    invalidation = {
        "kind": "measurable",
        "predicate": _tf1d("price_close", "lte", "58000.00"),
    }
    thesis_id = _build_active_thesis(
        thesis_kwargs, monkeypatch, make_event, invalidation=invalidation
    )
    bars = [
        # low 57200 > stop 57000 (failure predicate is LOW-based -> does NOT
        # trigger); close 57500 <= invalidation threshold 58000 -> VOID alone;
        # high 59500 < target 66000 -> success does not trigger either.
        Bar(
            ts_open=ACTIVATION_TS,
            open=Decimal("59000"),
            high=Decimal("59500"),
            low=Decimal("57200"),
            close=Decimal("57500"),
            volume=Decimal("10"),
        ),
    ]
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_grade_bars(bars))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: ACTIVATION_TS + timedelta(days=1))

    thesis.grade(thesis_id)

    payload = _thesis_events("ThesisGraded", thesis_id)[0].payload
    assert payload["outcome"] == "VOID", (
        "a measurable invalidation auto-evaluates inside grade() with zero discretion "
        "(§10.4 guard 1) — this is NOT the discretionary void() path"
    )
    assert any(m["category"] == "invalidation" for m in payload["measured"])


# ---------------------------------------------------------------------------
# 7. pnl from Fill events (fixture-freeze arithmetic shown inline)
# ---------------------------------------------------------------------------


def test_pnl_computed_from_fill_events_net_of_fees_long_round_trip(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    thesis_id = _build_active_thesis(thesis_kwargs, monkeypatch, make_event)

    entry_ts = ACTIVATION_TS
    exit_ts = ACTIVATION_TS + timedelta(days=1)
    default_ledger().append(
        make_event(
            type="FillRecorded",
            ts=entry_ts,
            payload={
                "order_id": "ord-entry",
                "thesis_id": thesis_id,
                "ts_utc": entry_ts.isoformat(),
                "price": "60000.00",
                "qty": "0.001",
                "fees_usd": "0.06",
            },
        )
    )
    default_ledger().append(
        make_event(
            type="FillRecorded",
            ts=exit_ts,
            payload={
                "order_id": "ord-exit",
                "thesis_id": thesis_id,
                "ts_utc": exit_ts.isoformat(),
                "price": "66000.00",
                "qty": "0.001",
                "fees_usd": "0.066",
            },
        )
    )

    bars = [
        Bar(
            ts_open=ACTIVATION_TS,
            open=Decimal("60000"),
            high=Decimal("61000"),
            low=Decimal("59000"),
            close=Decimal("60500"),
            volume=Decimal("10"),
        ),
        Bar(
            ts_open=exit_ts,
            open=Decimal("61000"),
            high=Decimal("67000"),
            low=Decimal("60500"),
            close=Decimal("66500"),
            volume=Decimal("10"),
        ),
    ]
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_grade_bars(bars))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: exit_ts + timedelta(days=1))

    thesis.grade(thesis_id)

    payload = _thesis_events("ThesisGraded", thesis_id)[0].payload
    # direction="long" (thesis_kwargs default). Fill-ordering convention
    # (ASSUMPTIONS, this batch, FLAGGED): entry = earliest-ts_utc Fill,
    # exit = latest-ts_utc Fill (contracts.Fill carries no `side` field).
    #   entry notional = 60000.00 * 0.001 =  60.00
    #   exit  notional = 66000.00 * 0.001 =  66.00
    #   gross           = 66.00 - 60.00   =   6.00
    #   fees            = 0.06 + 0.066    =   0.126
    #   pnl             = 6.00 - 0.126    =   5.874
    assert Decimal(payload["pnl_usd"]) == Decimal("5.874"), (
        "pnl = Sigma signed fill notionals net of fees (§10.2/§10.3): for a LONG round "
        "trip, pnl = (exit_price - entry_price) * qty - Sigma(fees) = "
        "(66000.00 - 60000.00) * 0.001 - (0.06 + 0.066) = 6.00 - 0.126 = 5.874"
    )


def test_pnl_with_no_fills_is_none_never_a_fabricated_zero(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    """CTO adjudication (P2 batch B, ASSUMPTIONS 71): a graded thesis with
    zero FillRecorded events has NO realized pnl — `pnl_usd` must be None
    (`ThesisGradedPayload.pnl_usd: Decimal | None`, changed this batch), not
    Decimal("0"), because a fabricated break-even datapoint would silently
    dilute batch D's series-expectancy math. Forward-pin (recorded in
    ASSUMPTIONS 71): batch D must EXCLUDE None-pnl theses from expectancy,
    never coerce them to zero."""
    thesis_id = _build_active_thesis(thesis_kwargs, monkeypatch, make_event)
    bars = [
        Bar(
            ts_open=ACTIVATION_TS,
            open=Decimal("58000"),
            high=Decimal("58500"),
            low=Decimal("56500"),
            close=Decimal("57000"),
            volume=Decimal("10"),
        ),
    ]
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_grade_bars(bars))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: ACTIVATION_TS + timedelta(days=1))

    thesis.grade(thesis_id)

    payload = _thesis_events("ThesisGraded", thesis_id)[0].payload
    assert payload["pnl_usd"] is None, (
        "no FillRecorded events -> pnl_usd is None (anti-fabrication, CTO adjudication): "
        "Decimal('0') here would inject a fake break-even trade into series expectancy"
    )


# ---------------------------------------------------------------------------
# 8. Lookahead / seam-call pin
# ---------------------------------------------------------------------------


def test_grade_passes_predicate_timeframe_and_activation_window_to_the_seam(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    """`get_closed_bars(symbol, timeframe, lookback_days)` has no explicit
    `start` parameter — grade() must derive `lookback_days` from
    (now - activation_ts) so the fetched window covers exactly
    [activation_ts, now]. Day-aligned fixture timestamps make the derivation
    checkable EXACTLY: now - timedelta(days=lookback_days) must land on
    activation_ts, not merely "close enough"."""
    short_horizon = ACTIVATION_TS + timedelta(days=3)
    thesis_id = _build_active_thesis_with_horizon(
        thesis_kwargs, monkeypatch, make_event, horizon=short_horizon
    )

    now = ACTIVATION_TS + timedelta(days=5)  # >= short_horizon -> guaranteed FAIL even w/ 0 bars
    calls: list[tuple[str, str, int]] = []

    def _recording_get_closed_bars(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
        calls.append((symbol, timeframe, lookback_days))
        return BarSeries(asset=_ASSET, timeframe=timeframe, bars=[], source="fake-kraken")

    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _recording_get_closed_bars)
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: now)

    thesis.grade(thesis_id)

    assert len(calls) >= 1, "grade() must fetch bars through the sanctioned get_closed_bars seam"
    symbol, timeframe, lookback_days = calls[0]
    assert symbol == "BTC/USD"
    assert timeframe == "1d", "must forward the thesis's OWN predicate timeframe, not a default"
    assert now - timedelta(days=lookback_days) == ACTIVATION_TS, (
        "the fetched window's implied start (now - lookback_days days) must equal "
        "activation_ts exactly — this is the 'activation->now window' the CTO addendum "
        "pins, expressed through get_closed_bars's lookback_days-only signature"
    )

    payload = _thesis_events("ThesisGraded", thesis_id)[0].payload
    assert payload["outcome"] == "FAIL", (
        "with zero bars returned and now >= horizon_end, the frozen core's horizon-expiry "
        "fallback fires regardless — this test's real job is the seam-call assertions "
        "above, this is just a sanity check that grade() completed"
    )


# ---------------------------------------------------------------------------
# 9. Quantize: no float-noise grade flips (TD-23)
# ---------------------------------------------------------------------------


def test_subtick_close_quantizes_onto_the_tick_and_still_triggers_stop(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    """stop = 57000.00, tick = 0.01, failure predicate is `price_close`
    (CLOSE-based — deliberately NOT the default `price_touch`/low-based
    failure criterion used elsewhere in this file, so the bar's LOW can be
    kept safely above the stop and only the CLOSE does the discriminating).
    Bar closes at 57000.004 — a hair ABOVE the stop, un-quantized — and must
    NOT slip through ungraded: quantize rounds it via ROUND_HALF_EVEN onto
    the tick grid — steps = 57000.004 / 0.01 = 5700000.4, which rounds DOWN
    to 5700000 (banker's rounding, ASSUMPTIONS 1) -> quantized close =
    57000.00 == stop -> lte-stop triggers. This is TD-23's whole point: a
    value that only sits above the threshold due to sub-tick noise must
    grade IDENTICALLY to its quantized value, not escape detection via a
    naive raw-Decimal comparison (57000.004 <= 57000.00 is False without
    quantization — the WRONG answer). Pin at the verb level: the RAW
    Decimal("57000.004") is passed to the frozen core unmutated (no
    premature rounding, no float round-trip) — the core itself (never
    touched by this test) does the quantizing."""
    failure = [_tf1d("price_close", "lte", "57000.00")]
    success = [_tf1d("price_touch", "gte", "66000.00")]  # unreachable by this bar; irrelevant
    thesis_id = _build_active_thesis(
        thesis_kwargs, monkeypatch, make_event, success_criteria=success, failure_criteria=failure
    )
    bars = [
        Bar(
            ts_open=ACTIVATION_TS,
            open=Decimal("57000.00"),
            high=Decimal("57000.02"),
            low=Decimal("57000.00"),  # deliberately ABOVE the stop: low-based touch would NOT fire
            close=Decimal("57000.004"),  # raw, un-quantized sub-tick value
            volume=Decimal("10"),
        ),
    ]
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_grade_bars(bars))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: ACTIVATION_TS + timedelta(days=1))

    thesis.grade(thesis_id)

    payload = _thesis_events("ThesisGraded", thesis_id)[0].payload
    assert payload["outcome"] == "FAIL", (
        "quantize(Decimal('57000.004'), Decimal('0.01')) == Decimal('57000.00') <= stop "
        "(57000.00) -> the CLOSE-based failure predicate must trigger. bar.low == "
        "57000.00 is deliberately NOT below the stop, so this can only be the CLOSE "
        "comparison firing — proof the tick-grid quantization path is exercised without a "
        "float round-trip corrupting the raw Decimal on its way into the frozen core"
    )
    assert any(m["category"] == "failure" for m in payload["measured"])
