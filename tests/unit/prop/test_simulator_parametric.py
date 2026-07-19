"""Parametric-mode simulator behavior (SPRINT P5-PROP batch A;
ASSUMPTIONS 148-150): seed determinism, the zero-edge sanity envelope
(entry 149's CTO derivation), negative-edge ruin dominance, and the
recommended_max_risk_frac ladder (entry 150).

Every test here is seeded, so once green these are DETERMINISTIC —
the envelopes tolerate estimator noise + barrier-overshoot bias in the
true value, not run-to-run flakiness.
"""

from __future__ import annotations

from decimal import Decimal

from tradekit.contracts import ParametricTradeModel, PropSimSpec
from tradekit.prop import simulate_evaluation

_LADDER = (
    Decimal("0.0025"),
    Decimal("0.005"),
    Decimal("0.0075"),
    Decimal("0.010"),
    Decimal("0.0125"),
    Decimal("0.015"),
    Decimal("0.0175"),
    Decimal("0.020"),
)


def _spec(
    *,
    win_rate: float = 0.5,
    payoff_ratio: float = 1.0,
    risk_frac: str = "0.005",
    n_paths: int = 300,
    horizon_days: int = 40,
) -> PropSimSpec:
    """No fees/funding: the analytical envelopes assume a pure two-barrier
    walk (entry 149); fee drag is covered by the scripted goldens."""
    return PropSimSpec(
        starting_balance=Decimal("5000"),
        fee_side_bps=Decimal("0"),
        funding_daily_pct=Decimal("0"),
        trade_model=ParametricTradeModel(
            win_rate=win_rate,
            payoff_ratio=payoff_ratio,
            risk_frac=Decimal(risk_frac),
            notional_frac=Decimal("0.05"),
            trades_per_day=4,
            hold_hours=2.0,
        ),
        n_paths=n_paths,
        horizon_days=horizon_days,
    )


class TestSeedDeterminism:
    def test_same_seed_same_result(self) -> None:
        spec = _spec()
        assert simulate_evaluation(spec, seed=42) == simulate_evaluation(spec, seed=42)

    def test_different_seed_different_paths(self) -> None:
        spec = _spec()
        a = simulate_evaluation(spec, seed=42)
        b = simulate_evaluation(spec, seed=43)
        assert a.equity_percentiles != b.equity_percentiles


class TestResultShape:
    def test_percentiles_and_hazard_cover_the_horizon(self) -> None:
        result = simulate_evaluation(_spec(horizon_days=40), seed=7)
        assert set(result.equity_percentiles) == {"p05", "p50", "p95"}
        assert all(len(v) == 40 for v in result.equity_percentiles.values())
        assert len(result.daily_breach_hazard) == 40

    def test_probabilities_partition(self) -> None:
        result = simulate_evaluation(_spec(), seed=7)
        total = result.pass_prob + result.ruin_prob + result.survival_prob
        assert abs(total - 1.0) < 1e-9
        assert abs(result.ruin_prob - (result.ruin_prob_mdl + result.ruin_prob_mdd)) < 1e-9

    def test_scripted_only_fields_are_none(self) -> None:
        result = simulate_evaluation(_spec(), seed=7)
        assert result.final_balance is None
        assert result.first_breach_day is None
        assert result.breach_reason is None
        assert result.daily_snapshots is None


class TestZeroEdgeEnvelope:
    """Entry 149: risk 0.5%/trade, 4 trades/day -> worst daily move 2%
    can NEVER touch the 3% MDL, isolating the two-barrier gambler's-ruin
    result: log-space pass_prob = 0.06188/(0.06188+0.09531) = 0.3936."""

    def test_pass_prob_in_derived_envelope(self) -> None:
        result = simulate_evaluation(
            _spec(n_paths=4000, horizon_days=300), seed=1
        )
        assert 0.36 <= result.pass_prob <= 0.43
        # Horizon long enough that (almost) every path absorbed.
        assert result.pass_prob + result.ruin_prob >= 0.99
        # MDL provably non-binding at this sizing.
        assert result.ruin_prob_mdl == 0.0

    def test_negative_edge_is_ruin_dominated(self) -> None:
        result = simulate_evaluation(
            _spec(win_rate=0.45, n_paths=2000, horizon_days=200), seed=1
        )
        assert result.ruin_prob > result.pass_prob


class TestRecommendedMaxRiskFrac:
    """Entry 150: largest ladder rung whose MONTHLY ruin probability
    (1 - (1-ruin)^(30/horizon)) clears Q.A.8's 2% line; None when no rung
    does — fail closed, never 'least-bad rung'."""

    def test_zero_edge_recommends_nothing(self) -> None:
        # Driftless against a 6% static MDD: every rung's monthly ruin is
        # far above 2% (the 0.0025 rung still ruins >30% of paths within
        # the horizon) -> fail closed.
        result = simulate_evaluation(
            _spec(n_paths=1000, horizon_days=120), seed=5
        )
        assert result.recommended_max_risk_frac is None

    def test_strong_edge_recommends_a_ladder_rung(self) -> None:
        result = simulate_evaluation(
            _spec(win_rate=0.9, payoff_ratio=2.0, n_paths=1000, horizon_days=60),
            seed=5,
        )
        assert result.recommended_max_risk_frac in _LADDER
