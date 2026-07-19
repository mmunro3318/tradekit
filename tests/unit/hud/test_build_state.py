"""BEHAVIOR/SEAM tests for hud.build_state (SPEC-hud-orderbook T3, AC-4..8).

Determinism seams (sanctioned, per DESIGN §Test seams): monkeypatch ONLY
``mae._runtime.get_closed_bars`` and ``mae._runtime.clock`` — never mock
tradekit internals directly.

Sanctioned module-level seams on ``tradekit.hud._build`` (RATIFIED,
tests/ASSUMPTIONS.md 157a/158):

  - ``evaluate_policy(proposal)`` -> object with ``.allowed: bool``,
    ``.verdict_id: str | None``, ``.rationale: str``.
  - ``open_position_symbols() -> set[str]``
  - ``size_qty(symbol, limit_price) -> Decimal`` (real-sizing default is
    loud-until-wired per ASSUMPTIONS 158; tests always patch it).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tradekit.hud import build_state

CAPTURED_AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

# AC-4 golden arithmetic (CTO-derived, frozen — buy LINK/USD limit 8.30000
# qty 12 tp 8.71500 sl 8.05100):
EXPECTED_EST_TOTAL_USD = Decimal("99.60")
EXPECTED_EST_FEE_USD = Decimal("0.04")
EXPECTED_EST_PNL_TP_USD = Decimal("4.90")
EXPECTED_EST_PNL_SL_USD = Decimal("-3.07")
EXPECTED_TP_DISTANCE_PCT = Decimal("5.00")
EXPECTED_SL_DISTANCE_PCT = Decimal("-3.00")


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
    AC-4 golden entry price (limit = last close, pinned)."""
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
    series (last close 8.30000) and the sanctioned sizing seam
    ``tradekit.hud._build.size_qty`` returns qty 12, driving the funnel to
    the AC-4 golden setup (buy LINK/USD limit 8.30000 tp 8.71500 sl
    8.05100 qty 12)."""
    import tradekit.hud._build as hud_build
    import tradekit.mae._runtime as mae_runtime

    monkeypatch.setattr(
        mae_runtime,
        "get_closed_bars",
        lambda symbol, timeframe, lookback_days: _fixture_series(symbol, 24),
    )
    monkeypatch.setattr(hud_build, "size_qty", lambda symbol, limit_price: Decimal("12"))


class TestAC4AllowedProposalBuildsTicketWithGoldenArithmetic:
    def test_allow_verdict_produces_one_ticket_with_pinned_arithmetic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-4: funnel passes all gates AND policy allows -> exactly one
        AdvisoryTicket for that symbol; verdict_id equals the ledgered
        verdict; est-P&L/fee/distance fields match the pinned arithmetic
        exactly (worked example independently hand-derived, not from the
        code under test)."""
        import tradekit.hud._build as hud_build

        monkeypatch.setattr(hud_build, "evaluate_policy", lambda proposal: _AllowDecision())
        monkeypatch.setattr(hud_build, "open_position_symbols", lambda: set())
        _patch_setup_sufficient(monkeypatch)

        state = build_state(["LINK/USD"], captured_at=CAPTURED_AT)

        assert len(state.tickets) == 1
        ticket = state.tickets[0]
        assert ticket.verdict_id == "verdict-link-1"
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

        state = build_state(["LINK/USD"], captured_at=CAPTURED_AT)

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

        state = build_state(["LINK/USD"], captured_at=CAPTURED_AT)

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

        state = build_state(["LINK/USD"], captured_at=CAPTURED_AT)

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

        state_1 = build_state(["LINK/USD"], captured_at=CAPTURED_AT)
        state_2 = build_state(["LINK/USD"], captured_at=CAPTURED_AT)

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

        state = build_state(["LINK/USD"], captured_at=CAPTURED_AT)

        assert state.tickets == ()
        entry = next(e for e in state.report if e.symbol == "LINK/USD")
        assert entry.grade == "wait"
        gate = next(g for g in entry.gates if g.name == "data_integrity")
        assert gate.passed is False
        assert "RuntimeError" in gate.observed
