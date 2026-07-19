"""Scripted-mode barrier-semantics goldens (SPRINT P5-PROP batch A;
ASSUMPTIONS 145-147). Every expected number below is HAND-DERIVED from
Report-1 §6/§8 semantics before any implementation existed — the CTO
freeze gate re-derives them independently before they are frozen.

Golden ledger walk for the fee/funding scenario (G1), starting balance
$5,000, 4 bps/side, funding 0.033%/day charged at UTC marks
{00,04,08,12,16,20}h strictly inside (entry_ts, exit_ts), every
application cent-quantized ROUND_HALF_EVEN (ASSUMPTIONS 146):

  T1 long  $2,000 D1 01:00 @100 -> D1 11:00 @102  (gross +40.00)
    entry fee  2000 * 0.0004            = 0.80
    funding    D1 04:00, 08:00: 2 * (2000 * 0.00033/6 = 0.11) = 0.22
    exit fee   2000 * 102/100 * 0.0004  = 0.816 -> 0.82
  T2 short $3,000 D1 23:00 @200 -> D3 06:00 @204  (gross -60.00)
    entry fee  3000 * 0.0004            = 1.20
    funding    D2 00,04,08,12,16,20 + D3 00,04: 8 marks,
               3000 * 0.00033/6 = 0.165 -> 0.16 each = 1.28
    exit fee   3000 * 204/200 * 0.0004  = 1.224 -> 1.22

  balance: 5000 -0.80 +40 -0.82 -0.22 (T1 net, in ts order)
           -1.20 (T2 entry) -0.16 (D2 00:00 funding)
           = 5036.80 at the D2 00:30 snapshot
           -0.16*5 (D2 04..20) -0.16 (D3 00:00)
           = 5035.84 at the D3 00:30 snapshot
           -0.16 (D3 04:00) -60 -1.22 (T2 exit) = 4974.46 final.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar

import pytest

from tradekit.contracts import PropSimSpec, ScriptedTradeModel, TradeRecord
from tradekit.prop import simulate_evaluation

D1 = datetime(2026, 7, 1, tzinfo=UTC)


def _ts(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, day, hour, minute, tzinfo=UTC)


def _trade(
    *,
    side: str,
    size: str,
    entry_price: str,
    exit_price: str,
    entry: datetime,
    exit: datetime,
) -> TradeRecord:
    return TradeRecord(
        entry_ts=entry,
        exit_ts=exit,
        entry_price=Decimal(entry_price),
        exit_price=Decimal(exit_price),
        side=side,  # type: ignore[arg-type]
        size_usd=Decimal(size),
    )


def _spec(
    trades: tuple[TradeRecord, ...],
    *,
    starting_balance: str = "5000",
    horizon_days: int,
    mdl_pct: str = "0.03",
    mdd_pct: str = "0.06",
    profit_target_pct: str | None = "0.10",
    fee_side_bps: str = "0",
    funding_daily_pct: str = "0",
) -> PropSimSpec:
    return PropSimSpec(
        starting_balance=Decimal(starting_balance),
        mdl_pct=Decimal(mdl_pct),
        mdd_pct=Decimal(mdd_pct),
        profit_target_pct=(None if profit_target_pct is None else Decimal(profit_target_pct)),
        fee_side_bps=Decimal(fee_side_bps),
        funding_daily_pct=Decimal(funding_daily_pct),
        trade_model=ScriptedTradeModel(trades=trades),
        horizon_days=horizon_days,
    )


class TestFeeFundingAccrual:
    """G1 — the 3-day 2-position cent-exact scenario (module docstring)."""

    def _result(self):
        trades = (
            _trade(
                side="long",
                size="2000",
                entry_price="100",
                exit_price="102",
                entry=_ts(1, 1),
                exit=_ts(1, 11),
            ),
            _trade(
                side="short",
                size="3000",
                entry_price="200",
                exit_price="204",
                entry=_ts(1, 23),
                exit=_ts(3, 6),
            ),
        )
        spec = _spec(
            trades,
            horizon_days=3,
            fee_side_bps="4",
            funding_daily_pct="0.00033",
        )
        return simulate_evaluation(spec, seed=1)

    def test_final_balance_to_the_cent(self) -> None:
        assert self._result().final_balance == Decimal("4974.46")

    def test_daily_snapshots_are_balance_at_0030_utc(self) -> None:
        """Day 1's reference is the starting balance; D2/D3 snapshots
        include exactly the ledger events with ts strictly BEFORE 00:30
        that day (ASSUMPTIONS 145a/146d/153)."""
        assert self._result().daily_snapshots == [
            Decimal("5000.00"),
            Decimal("5036.80"),
            Decimal("5035.84"),
        ]

    def test_no_barrier_hit(self) -> None:
        result = self._result()
        assert result.survival_prob == 1.0
        assert result.pass_prob == 0.0
        assert result.ruin_prob == 0.0
        assert result.breach_reason is None
        assert result.first_breach_day is None


class TestMdlBoundary:
    """G2 — equality at the MDL floor breaches (anti-permissive,
    ASSUMPTIONS 145b): floor = 5000 * 0.97 = 4850."""

    def _run(self, exit_price: str):
        trades = (
            _trade(
                side="long",
                size="5000",
                entry_price="100",
                exit_price=exit_price,
                entry=_ts(1, 9),
                exit=_ts(1, 15),
            ),
        )
        return simulate_evaluation(_spec(trades, horizon_days=1), seed=1)

    def test_loss_exactly_at_floor_breaches(self) -> None:
        # 100 -> 97 on $5,000 = -150.00 -> balance 4850 == floor -> breach.
        result = self._run("97")
        assert result.ruin_prob == 1.0
        assert result.ruin_prob_mdl == 1.0
        assert result.ruin_prob_mdd == 0.0
        assert result.breach_reason == "mdl"
        assert result.first_breach_day == 1
        assert result.expected_days_to_outcome == 1.0

    def test_loss_one_dollar_inside_survives(self) -> None:
        # 100 -> 97.02 on $5,000 = -149.00 -> balance 4851 > 4850.
        result = self._run("97.02")
        assert result.survival_prob == 1.0
        assert result.ruin_prob == 0.0
        assert result.breach_reason is None


class TestSnapshotUsesBalanceNotEquity:
    """G3 — Report-1 §6's decisive point, transcribed at its own $100k
    scale: the 00:30 UTC snapshot is BALANCE only; an open position does
    not move it (ASSUMPTIONS 145a)."""

    def test_open_position_does_not_move_the_snapshot(self) -> None:
        # Open D1 10:00, closed D2 10:00 at -2,900: D2's snapshot is still
        # 100,000 (floor 97,000); the realized 97,100 stays above it.
        trades = (
            _trade(
                side="long",
                size="100000",
                entry_price="100",
                exit_price="97.1",
                entry=_ts(1, 10),
                exit=_ts(2, 10),
            ),
        )
        result = simulate_evaluation(
            _spec(trades, starting_balance="100000", horizon_days=2), seed=1
        )
        assert result.daily_snapshots == [
            Decimal("100000.00"),
            Decimal("100000.00"),
        ]
        assert result.survival_prob == 1.0
        assert result.breach_reason is None

    def test_official_worked_example_3000_loss_breaches(self) -> None:
        # "On a $100,000 account, MDL = $3,000. If equity falls $3,000 or
        # more from the day's starting point, breach triggers" (§6).
        trades = (
            _trade(
                side="long",
                size="100000",
                entry_price="100",
                exit_price="97",
                entry=_ts(1, 10),
                exit=_ts(1, 20),
            ),
        )
        result = simulate_evaluation(
            _spec(trades, starting_balance="100000", horizon_days=1), seed=1
        )
        assert result.breach_reason == "mdl"
        assert result.first_breach_day == 1


class TestMddStaticNotTrailing:
    """G4 — MDD floor is starting_balance * 0.94 = 4700, STATIC: a gain
    to 5,600 then a give-back to 4,750 must NOT breach (a trailing-peak
    implementation would put the floor at 5,264 and wrongly kill it);
    grinding on to exactly 4,700 breaches (ASSUMPTIONS 145b/c).

    MDL is parked at 99% and the target at 50% so only MDD is in play.
    """

    _T1: ClassVar[dict[str, str]] = dict(
        side="long", size="6000", entry_price="100", exit_price="110"
    )
    _T2: ClassVar[dict[str, str]] = dict(
        side="long", size="8500", entry_price="100", exit_price="90"
    )
    _T3: ClassVar[dict[str, str]] = dict(
        side="long", size="5000", entry_price="100", exit_price="99"
    )

    def _run(self, n_trades: int):
        raw = [self._T1, self._T2, self._T3][:n_trades]
        trades = tuple(
            _trade(entry=_ts(day, 9), exit=_ts(day, 15), **kw)  # type: ignore[arg-type]
            for day, kw in enumerate(raw, start=1)
        )
        spec = _spec(
            trades,
            horizon_days=n_trades,
            mdl_pct="0.99",
            profit_target_pct="0.50",
        )
        return simulate_evaluation(spec, seed=1)

    def test_giveback_above_static_floor_survives(self) -> None:
        # +600 -> 5600, then -850 -> 4750 > 4700: no breach.
        result = self._run(2)
        assert result.survival_prob == 1.0
        assert result.breach_reason is None
        assert result.final_balance == Decimal("4750.00")

    def test_equality_at_static_floor_breaches(self) -> None:
        # ... then -50 -> 4700 == floor -> breach, MDD, day 3.
        result = self._run(3)
        assert result.breach_reason == "mdd"
        assert result.ruin_prob_mdd == 1.0
        assert result.ruin_prob_mdl == 0.0
        assert result.first_breach_day == 3

    def test_scripted_mode_reports_no_risk_recommendation(self) -> None:
        # recommended_max_risk_frac is parametric-mode-only (entry 150).
        assert self._run(2).recommended_max_risk_frac is None


class TestTargetAbsorbs:
    """G5 — equity >= starting * 1.10 absorbs into 'passed' (venue
    force-flattens, ASSUMPTIONS 145d); later scripted trades are ignored.
    """

    def _run(self):
        trades = (
            # +500 -> 5500 == target: passed.
            _trade(
                side="long",
                size="5000",
                entry_price="100",
                exit_price="110",
                entry=_ts(1, 9),
                exit=_ts(1, 15),
            ),
            # A later catastrophic loss that must NOT be applied.
            _trade(
                side="long",
                size="5000",
                entry_price="100",
                exit_price="50",
                entry=_ts(2, 9),
                exit=_ts(2, 15),
            ),
        )
        return simulate_evaluation(_spec(trades, horizon_days=2), seed=1)

    def test_pass_is_absorbing(self) -> None:
        result = self._run()
        assert result.pass_prob == 1.0
        assert result.ruin_prob == 0.0
        assert result.final_balance == Decimal("5500.00")
        assert result.expected_days_to_outcome == 1.0


class TestTimelineGuards:
    """Review-round pins (ASSUMPTIONS 152/153)."""

    def test_trades_past_horizon_raise(self) -> None:
        # Entry 152a: a day-5 trade under horizon_days=2 must fail loud,
        # never report a breach outside the evaluation window.
        trades = (
            _trade(
                side="long",
                size="1000",
                entry_price="100",
                exit_price="101",
                entry=_ts(1, 9),
                exit=_ts(1, 15),
            ),
            _trade(
                side="long",
                size="1000",
                entry_price="100",
                exit_price="101",
                entry=_ts(5, 9),
                exit=_ts(5, 15),
            ),
        )
        with pytest.raises(ValueError, match="horizon"):
            simulate_evaluation(_spec(trades, horizon_days=2), seed=1)

    def test_event_at_exactly_0030_lands_in_the_new_day(self) -> None:
        # Entry 153: an exit stamped exactly D2 00:30 is EXCLUDED from
        # D2's snapshot — the snapshot is computed at the instant, the
        # same-instant fill settles after it.
        trades = (
            _trade(
                side="long",
                size="5000",
                entry_price="100",
                exit_price="110",
                entry=_ts(1, 9),
                exit=_ts(2, 0, 30),
            ),
        )
        result = simulate_evaluation(
            _spec(trades, horizon_days=2, profit_target_pct="0.50"), seed=1
        )
        assert result.daily_snapshots == [
            Decimal("5000.00"),
            Decimal("5000.00"),
        ]
        assert result.final_balance == Decimal("5500.00")
