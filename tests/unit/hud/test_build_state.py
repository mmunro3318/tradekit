"""BEHAVIOR/SEAM tests for hud.build_state (SPEC-hud-orderbook T3, AC-4..8).

Determinism seams (sanctioned, per DESIGN §Test seams): monkeypatch ONLY
``mae._runtime.get_closed_bars`` and ``mae._runtime.clock`` — never mock
tradekit internals directly.

ASSUMPTION-CANDIDATE (flagged for CTO ratification, see report): the
funnel→policy wiring does not exist yet, so this dispatch pins two new
module-level seams on the not-yet-written ``tradekit.hud._build`` module
for these tests to monkeypatch:

  - ``tradekit.hud._build.evaluate_policy(proposal) -> _PolicyDecision``
    where ``_PolicyDecision`` has ``.allowed: bool``, ``.verdict_id: str | None``,
    ``.rationale: str``.
  - ``tradekit.hud._build.open_position_symbols() -> set[str]``

These are NOT in SPEC-hud-orderbook.md's interface pins — they are the
test-writer's best-effort expression of AC-5/AC-7 given the funnel wiring
is unbuilt. Implementer may rename/reshape at green stage only via CTO
ratification; flagged as ASSUMPTIONS-candidate #1 in the batch report.
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


def _patch_bars_sufficient(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEAM: mae._runtime.get_closed_bars returns enough bars for the
    funnel to produce a passing setup for LINK/USD (buy, limit 8.30000,
    tp 8.71500, sl 8.05100, qty 12)."""
    import tradekit.mae._runtime as mae_runtime

    def _fake_get_closed_bars(symbol: str, timeframe: str, lookback_days: int):
        raise NotImplementedError(
            "test seam stub — implementer wires real BarSeries fixture"
        )

    monkeypatch.setattr(mae_runtime, "get_closed_bars", _fake_get_closed_bars)


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
        _patch_bars_sufficient(monkeypatch)

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
        _patch_bars_sufficient(monkeypatch)

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
            from tradekit.contracts import BarSeries

            return BarSeries(symbol=symbol, timeframe=timeframe, bars=())

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
        _patch_bars_sufficient(monkeypatch)

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
        _patch_bars_sufficient(monkeypatch)

        state_1 = build_state(["LINK/USD"], captured_at=CAPTURED_AT)
        state_2 = build_state(["LINK/USD"], captured_at=CAPTURED_AT)

        assert state_1 == state_2
        assert state_1.generated_at == CAPTURED_AT
