"""PropSimSpec / PropSimResult / trade-model union contracts (SPRINT
P5-PROP batch A; ASSUMPTIONS round-26). Contract tests only — engine
behavior lives in test_scripted_goldens.py / test_simulator_parametric.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from tradekit.contracts import (
    ParametricTradeModel,
    PropSimSpec,
    ScriptedTradeModel,
    TradeRecord,
)


def _trade() -> TradeRecord:
    return TradeRecord(
        entry_ts=datetime(2026, 7, 1, 1, 0, tzinfo=UTC),
        exit_ts=datetime(2026, 7, 1, 11, 0, tzinfo=UTC),
        entry_price=Decimal("100"),
        exit_price=Decimal("102"),
        side="long",
        size_usd=Decimal("2000"),
    )


def _parametric() -> ParametricTradeModel:
    return ParametricTradeModel(
        win_rate=0.5,
        payoff_ratio=1.0,
        risk_frac=Decimal("0.005"),
        notional_frac=Decimal("0.05"),
        trades_per_day=4,
        hold_hours=2.0,
    )


class TestSpecDefaults:
    def test_starter_venue_defaults(self) -> None:
        """Kraken Prop Starter numbers are the spec defaults (Report-1
        §6/§8): 3% MDL / 6% MDD / 10% target / 4 bps side / 0.033%/day
        funding / 2%-monthly ruin line (Q.A.8) / 10k paths."""
        spec = PropSimSpec(
            starting_balance=Decimal("5000"),
            trade_model=_parametric(),
            horizon_days=30,
        )
        assert spec.mdl_pct == Decimal("0.03")
        assert spec.mdd_pct == Decimal("0.06")
        assert spec.profit_target_pct == Decimal("0.10")
        assert spec.fee_side_bps == Decimal("4")
        assert spec.funding_daily_pct == Decimal("0.00033")
        assert spec.ruin_prob_monthly_max == 0.02
        assert spec.n_paths == 10_000

    def test_funded_mode_has_no_target_barrier(self) -> None:
        """profit_target_pct=None is the funded-account variant (sprint
        §1b): legal, and distinct from any numeric target."""
        spec = PropSimSpec(
            starting_balance=Decimal("5000"),
            profit_target_pct=None,
            trade_model=_parametric(),
            horizon_days=30,
        )
        assert spec.profit_target_pct is None

    def test_spec_is_frozen(self) -> None:
        spec = PropSimSpec(
            starting_balance=Decimal("5000"),
            trade_model=_parametric(),
            horizon_days=30,
        )
        with pytest.raises(ValidationError):
            spec.starting_balance = Decimal("6000")  # type: ignore[misc]


class TestTradeModelUnion:
    def test_discriminated_by_kind(self) -> None:
        spec = PropSimSpec.model_validate(
            {
                "starting_balance": "5000",
                "horizon_days": 3,
                "trade_model": {
                    "kind": "scripted",
                    "trades": [_trade().model_dump(mode="json")],
                },
            }
        )
        assert isinstance(spec.trade_model, ScriptedTradeModel)

    def test_variant_rejects_stray_fields(self) -> None:
        """StrictFrozenModel variants: a typo'd field dies at authoring
        time, never silently ignored (ASSUMPTIONS 5 lineage)."""
        with pytest.raises(ValidationError):
            ScriptedTradeModel(trades=(_trade(),), block_len=3)  # type: ignore[call-arg]

    def test_scripted_requires_at_least_one_trade(self) -> None:
        with pytest.raises(ValidationError):
            ScriptedTradeModel(trades=())

    def test_parametric_bounds(self) -> None:
        with pytest.raises(ValidationError):
            ParametricTradeModel(
                win_rate=1.5,  # > 1
                payoff_ratio=1.0,
                risk_frac=Decimal("0.005"),
                notional_frac=Decimal("0.05"),
                trades_per_day=4,
                hold_hours=2.0,
            )
