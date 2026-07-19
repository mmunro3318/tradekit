"""BEHAVIOR/SEAM tests for hud.build_state (SPEC-hud-orderbook T3/T5,
AC-4..8, AC-11..13).

Determinism seams (sanctioned, per DESIGN §Test seams): monkeypatch ONLY
``mae._runtime.get_closed_bars`` and ``mae._runtime.clock`` — never mock
tradekit internals directly.

Sanctioned module-level seams on ``tradekit.hud._build`` (RATIFIED,
tests/ASSUMPTIONS.md 157a/158, RENAMED/ADDED per T5 addendum — see
ASSUMPTIONS flag in this batch's report):

  - ``evaluate_policy(proposal)`` -> object with ``.allowed: bool``,
    ``.verdict_id: str | None``, ``.rationale: str``.
  - ``open_position_symbols() -> set[str]``
  - ``sizing_info(symbol, limit_price, equity_usd) -> SizingInfo`` — REPLACES
    the T3/batch-1 ``size_qty(symbol, limit_price) -> Decimal`` seam. One
    real ``mae.size_position`` call now powers BOTH qty and the ATR bracket
    (stop_distance_usd, r_multiple_target), per the T5 addendum's literal
    text: "the DEFAULT size_qty calls mae.size_position once and the module
    keeps (qty, stop_distance, r_multiple) from that call." Tests provide a
    duck-typed fake exposing ``.qty``, ``.stop_distance_usd``,
    ``.r_multiple_target`` (ASSUMPTIONS flag #1, CTO to ratify).
  - ``scan_setup(symbol) -> object`` with ``.signal_tags: list[str]`` — NEW
    4th sanctioned seam (T5 addendum); default is the real
    ``mae.scan_markets("crypto", ["1h"], filters={...}, symbols=[symbol],
    regime_gate=True)`` call, PASSING iff a match for the symbol survives
    with >= 1 signal_tag after the regime gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar

import pytest

from tradekit.hud import build_state

CAPTURED_AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
EQUITY_USD = Decimal("5000")

# AC-11 golden arithmetic (CTO-derived, frozen — buy LINK/USD limit 8.30000
# qty 12, stop_distance_usd 0.24900, r_multiple_target 2 -> ATR bracket
# SL = 8.30000 - 0.24900 = 8.05100; TP = 8.30000 + 2*0.24900 = 8.79800):
EXPECTED_TP_PRICE = Decimal("8.79800")
EXPECTED_SL_PRICE = Decimal("8.05100")
EXPECTED_EST_TOTAL_USD = Decimal("99.60")
EXPECTED_EST_FEE_USD = Decimal("0.04")
EXPECTED_EST_PNL_TP_USD = Decimal("5.90")
EXPECTED_EST_PNL_SL_USD = Decimal("-3.07")
EXPECTED_TP_DISTANCE_PCT = Decimal("6.00")
EXPECTED_SL_DISTANCE_PCT = Decimal("-3.00")


@dataclass(frozen=True)
class _FakeSizingInfo:
    """Duck-typed stand-in for the addendum's ``SizingInfo`` — tests never
    import the real dataclass (green-stage internal); they only rely on the
    three field names the addendum pins."""

    qty: Decimal
    stop_distance_usd: Decimal
    r_multiple_target: Decimal


class _PassingSetup:
    signal_tags: ClassVar[list[str]] = ["macd_bullish", "volume_spike"]


class _FailingSetup:
    signal_tags: ClassVar[list[str]] = []


class _AllowDecision:
    allowed = True
    verdict_id = "verdict-link-1"
    rationale = "all gates passed"


class _RefuseDecision:
    allowed = False
    verdict_id = None
    rationale = "R-rule breach: daily loss limit near"


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEAM: mae._runtime.clock frozen so no test can pass by accident via
    real wall-clock reads leaking into build_state (AC-8)."""
    import tradekit.mae._runtime as mae_runtime

    monkeypatch.setattr(mae_runtime, "clock", lambda: CAPTURED_AT)


def _fixture_series(symbol: str, n_bars: int):
    """Valid ascending hourly BarSeries whose last close is 8.30000 — the
    AC-11 golden entry price (limit = last close, pinned)."""
    from datetime import timedelta

    from tradekit.contracts import AssetRef, Bar, BarSeries

    bars = [
        Bar(
            ts_open=CAPTURED_AT - timedelta(hours=n_bars - i),
            open=Decimal("8.30000"),
            high=Decimal("8.40000"),
            low=Decimal("8.20000"),
            close=Decimal("8.30000"),
            volume=Decimal("1000"),
        )
        for i in range(n_bars)
    ]
    return BarSeries(
        asset=AssetRef(
            symbol=symbol,
            venue="kraken",
            asset_class="crypto",
            tick_size=Decimal("0.00001"),
        ),
        timeframe="1h",
        bars=bars,
        source="test-fixture",
    )


def _patch_setup_sufficient(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEAM: mae._runtime.get_closed_bars returns a real, valid 24-bar
    series (last close 8.30000), ``scan_setup`` passes with surviving
    signal_tags, and the sanctioned sizing seam
    ``tradekit.hud._build.sizing_info`` returns the AC-11 golden sizing
    (qty 12, stop_distance_usd 0.24900, r_multiple_target 2) — driving the
    funnel to the AC-11 golden ticket (buy LINK/USD limit 8.30000
    tp 8.79800 sl 8.05100 qty 12)."""
    import tradekit.hud._build as hud_build
    import tradekit.mae._runtime as mae_runtime

    monkeypatch.setattr(
        mae_runtime,
        "get_closed_bars",
        lambda symbol, timeframe, lookback_days: _fixture_series(symbol, 24),
    )
    monkeypatch.setattr(hud_build, "scan_setup", lambda symbol: _PassingSetup())
    monkeypatch.setattr(
        hud_build,
        "sizing_info",
        lambda symbol, limit_price, equity_usd: _FakeSizingInfo(
            qty=Decimal("12"),
            stop_distance_usd=Decimal("0.24900"),
            r_multiple_target=Decimal("2"),
        ),
    )


class TestAC11AllowedProposalBuildsTicketWithGoldenAtrBracketArithmetic:
    def test_allow_verdict_produces_one_ticket_with_pinned_atr_bracket_arithmetic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-11: seams driving a symbol through setup+sizing+policy allow
        -> the ticket's SL/TP equal the pinned ATR-bracket arithmetic
        (worked example frozen in this test) and qty equals the seamed
        sizing_info result."""
        import tradekit.hud._build as hud_build

        monkeypatch.setattr(hud_build, "evaluate_policy", lambda proposal: _AllowDecision())
        monkeypatch.setattr(hud_build, "open_position_symbols", lambda: set())
        _patch_setup_sufficient(monkeypatch)

        state = build_state(["LINK/USD"], captured_at=CAPTURED_AT, equity_usd=EQUITY_USD)

        assert len(state.tickets) == 1
        ticket = state.tickets[0]
        assert ticket.verdict_id == "verdict-link-1"
        assert ticket.quantity == Decimal("12")
        assert ticket.tp_price == EXPECTED_TP_PRICE
        assert ticket.sl_price == EXPECTED_SL_PRICE
        assert ticket.est_total_usd == EXPECTED_EST_TOTAL_USD
        assert ticket.est_fee_usd == EXPECTED_EST_FEE_USD
        assert ticket.est_pnl_tp_usd == EXPECTED_EST_PNL_TP_USD
        assert ticket.est_pnl_sl_usd == EXPECTED_EST_PNL_SL_USD
        assert ticket.tp_distance_pct == EXPECTED_TP_DISTANCE_PCT
        assert ticket.sl_distance_pct == EXPECTED_SL_DISTANCE_PCT


class TestAC5PolicyRefusalYieldsNoTicketAndFailedGate:
    def test_refused_verdict_produces_no_ticket_wait_grade_and_failed_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-5: every gate passes EXCEPT policy refuses -> no ticket built;
        report entry grade is "wait"; a failed GateResult named
        "policy_verdict" carries the refusal rationale."""
        import tradekit.hud._build as hud_build

        monkeypatch.setattr(hud_build, "evaluate_policy", lambda proposal: _RefuseDecision())
        monkeypatch.setattr(hud_build, "open_position_symbols", lambda: set())
        _patch_setup_sufficient(monkeypatch)

        state = build_state(["LINK/USD"], captured_at=CAPTURED_AT, equity_usd=EQUITY_USD)

        assert state.tickets == ()
        entry = next(e for e in state.report if e.symbol == "LINK/USD")
        assert entry.grade == "wait"
        policy_gates = [g for g in entry.gates if g.name == "policy_verdict"]
        assert len(policy_gates) == 1
        assert policy_gates[0].passed is False
        assert "daily loss limit" in policy_gates[0].rationale


class TestAC6InsufficientBarsYieldsWaitNoException:
    def test_insufficient_bars_produces_wait_grade_and_data_integrity_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-6: bar fetch yields insufficient data -> grade "wait" with a
        failed "data_integrity" gate naming the gap; no exception escapes
        build_state."""
        import tradekit.hud._build as hud_build
        import tradekit.mae._runtime as mae_runtime

        def _too_few_bars(symbol: str, timeframe: str, lookback_days: int):
            return _fixture_series(symbol, 3)

        monkeypatch.setattr(mae_runtime, "get_closed_bars", _too_few_bars)
        monkeypatch.setattr(hud_build, "evaluate_policy", lambda proposal: _AllowDecision())
        monkeypatch.setattr(hud_build, "open_position_symbols", lambda: set())

        state = build_state(["LINK/USD"], captured_at=CAPTURED_AT, equity_usd=EQUITY_USD)

        assert state.tickets == ()
        entry = next(e for e in state.report if e.symbol == "LINK/USD")
        assert entry.grade == "wait"
        integrity_gates = [g for g in entry.gates if g.name == "data_integrity"]
        assert len(integrity_gates) == 1
        assert integrity_gates[0].passed is False


class TestAC7OpenPositionYieldsHoldNoTicket:
    def test_open_position_symbol_produces_hold_grade_and_no_ticket(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-7: symbol has an open thesis/position and no exit signal ->
        grade "hold" and no ticket is built — even though the funnel and
        policy would otherwise allow (position safety trumps, per the
        wait-vs-hold tie resolution in SPEC §Unknowns register)."""
        import tradekit.hud._build as hud_build

        monkeypatch.setattr(hud_build, "evaluate_policy", lambda proposal: _AllowDecision())
        monkeypatch.setattr(hud_build, "open_position_symbols", lambda: {"LINK/USD"})
        _patch_setup_sufficient(monkeypatch)

        state = build_state(["LINK/USD"], captured_at=CAPTURED_AT, equity_usd=EQUITY_USD)

        assert state.tickets == ()
        entry = next(e for e in state.report if e.symbol == "LINK/USD")
        assert entry.grade == "hold"


class TestAC8Determinism:
    def test_same_seamed_inputs_and_captured_at_produce_equal_states(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-8: build_state called twice with identical seamed inputs and
        the same captured_at -> the two HudStates are equal; generated_at
        equals captured_at (no wall-clock reads inside)."""
        import tradekit.hud._build as hud_build

        monkeypatch.setattr(hud_build, "evaluate_policy", lambda proposal: _AllowDecision())
        monkeypatch.setattr(hud_build, "open_position_symbols", lambda: set())
        _patch_setup_sufficient(monkeypatch)

        state_1 = build_state(["LINK/USD"], captured_at=CAPTURED_AT, equity_usd=EQUITY_USD)
        state_2 = build_state(["LINK/USD"], captured_at=CAPTURED_AT, equity_usd=EQUITY_USD)

        assert state_1 == state_2
        assert state_1.generated_at == CAPTURED_AT


class TestAC6ProviderExceptionDegradesToWait:
    def test_provider_exception_produces_wait_grade_never_escapes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-6 / ASSUMPTIONS 158d: a raising bar provider degrades to a
        failed data_integrity gate (grade "wait") naming the error class —
        the exception never escapes build_state."""
        import tradekit.hud._build as hud_build
        import tradekit.mae._runtime as mae_runtime

        def _boom(symbol: str, timeframe: str, lookback_days: int):
            raise RuntimeError("feed down")

        monkeypatch.setattr(mae_runtime, "get_closed_bars", _boom)
        monkeypatch.setattr(hud_build, "evaluate_policy", lambda proposal: _AllowDecision())
        monkeypatch.setattr(hud_build, "open_position_symbols", lambda: set())

        state = build_state(["LINK/USD"], captured_at=CAPTURED_AT, equity_usd=EQUITY_USD)

        assert state.tickets == ()
        entry = next(e for e in state.report if e.symbol == "LINK/USD")
        assert entry.grade == "wait"
        gate = next(g for g in entry.gates if g.name == "data_integrity")
        assert gate.passed is False
        assert "RuntimeError" in gate.observed


class TestAC12SetupFailureYieldsWaitAndSkipsPolicy:
    def test_no_surviving_signal_tags_produces_wait_failed_setup_gate_no_policy_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-12: scan_markets/scan_setup yields no surviving signal_tags ->
        grade "wait" with a failed "setup" gate and NO policy evaluation
        occurs at all — no "policy_verdict" gate row present, and the
        policy seam is never invoked (short-circuit before policy, per the
        T5 addendum's pinned gate order)."""
        import tradekit.hud._build as hud_build
        import tradekit.mae._runtime as mae_runtime

        policy_calls: list[object] = []

        def _recording_policy(proposal: object) -> _AllowDecision:
            policy_calls.append(proposal)
            return _AllowDecision()

        monkeypatch.setattr(
            mae_runtime,
            "get_closed_bars",
            lambda symbol, timeframe, lookback_days: _fixture_series(symbol, 24),
        )
        monkeypatch.setattr(hud_build, "scan_setup", lambda symbol: _FailingSetup())
        monkeypatch.setattr(hud_build, "evaluate_policy", _recording_policy)
        monkeypatch.setattr(hud_build, "open_position_symbols", lambda: set())

        state = build_state(["LINK/USD"], captured_at=CAPTURED_AT, equity_usd=EQUITY_USD)

        assert state.tickets == ()
        entry = next(e for e in state.report if e.symbol == "LINK/USD")
        assert entry.grade == "wait"
        setup_gates = [g for g in entry.gates if g.name == "setup"]
        assert len(setup_gates) == 1
        assert setup_gates[0].passed is False
        policy_gates = [g for g in entry.gates if g.name == "policy_verdict"]
        assert policy_gates == []
        assert policy_calls == []


class TestSizingGateZeroQtyYieldsWaitNoTicket:
    def test_zero_qty_sizing_result_produces_wait_and_failed_sizing_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """T5 addendum: sizing_info returning a zero/negative qty -> no
        ticket, a failed "sizing" gate, grade "wait" (conservative — never
        oversize, and a zero recommendation is a refusal to trade, not a
        degenerate ticket)."""
        import tradekit.hud._build as hud_build
        import tradekit.mae._runtime as mae_runtime

        monkeypatch.setattr(
            mae_runtime,
            "get_closed_bars",
            lambda symbol, timeframe, lookback_days: _fixture_series(symbol, 24),
        )
        monkeypatch.setattr(hud_build, "scan_setup", lambda symbol: _PassingSetup())
        monkeypatch.setattr(
            hud_build,
            "sizing_info",
            lambda symbol, limit_price, equity_usd: _FakeSizingInfo(
                qty=Decimal("0"),
                stop_distance_usd=Decimal("0.24900"),
                r_multiple_target=Decimal("2"),
            ),
        )
        monkeypatch.setattr(hud_build, "evaluate_policy", lambda proposal: _AllowDecision())
        monkeypatch.setattr(hud_build, "open_position_symbols", lambda: set())

        state = build_state(["LINK/USD"], captured_at=CAPTURED_AT, equity_usd=EQUITY_USD)

        assert state.tickets == ()
        entry = next(e for e in state.report if e.symbol == "LINK/USD")
        assert entry.grade == "wait"
        sizing_gates = [g for g in entry.gates if g.name == "sizing"]
        assert len(sizing_gates) == 1
        assert sizing_gates[0].passed is False


class TestGateOrderMatchesPinnedSequence:
    def test_allow_path_gate_names_appear_in_pinned_relative_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """T5 addendum: gate order per symbol is data_integrity -> setup ->
        sizing -> policy_verdict (open-position/hold is checked earlier and
        short-circuits, per AC-7, so it never coexists with these gates in
        one report entry). Assert the RELATIVE order of the named gates
        that appear — this stays true regardless of whether the
        implementer also emits a passing "sizing" row alongside the others."""
        import tradekit.hud._build as hud_build

        monkeypatch.setattr(hud_build, "evaluate_policy", lambda proposal: _AllowDecision())
        monkeypatch.setattr(hud_build, "open_position_symbols", lambda: set())
        _patch_setup_sufficient(monkeypatch)

        state = build_state(["LINK/USD"], captured_at=CAPTURED_AT, equity_usd=EQUITY_USD)

        entry = next(e for e in state.report if e.symbol == "LINK/USD")
        gate_names = [g.name for g in entry.gates]
        pinned_order = ["data_integrity", "setup", "sizing", "policy_verdict"]
        present_in_pinned_order = [name for name in pinned_order if name in gate_names]
        observed_positions = [gate_names.index(name) for name in present_in_pinned_order]
        assert observed_positions == sorted(observed_positions), (
            f"gate order {gate_names} does not respect pinned sequence {pinned_order}"
        )
