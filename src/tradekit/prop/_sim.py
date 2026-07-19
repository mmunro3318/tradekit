"""Prop evaluation barrier simulator — engine (SPRINT P5-PROP §1b;
ASSUMPTIONS round-26, entries 145-150).

Two engines behind one verb, `simulate_evaluation`:

* **Scripted** (`ScriptedTradeModel`, entries 145-147): replays a fixed
  `TradeRecord` sequence as ONE deterministic ledger walk. Every fee/
  funding/P&L application is Decimal, cent-quantized ROUND_HALF_EVEN at
  application time (entry 146c) — this is the golden/replay seam, money
  math end to end. Barriers (MDL/MDD/target) are absorbing and checked
  after every ledger event in timestamp order; the MDL floor for a given
  moment is whichever daily 00:30-UTC snapshot has most recently been
  established (day 1's snapshot is the starting balance by definition,
  entry 145a) — equivalent to "the day the checked event's own calendar
  date falls in" for every scenario this batch's goldens exercise (no
  two same-day pre-mark events probe the ambiguous case of a floor
  depending on a not-yet-applied same-day event).

* **Parametric** (`ParametricTradeModel`, entries 148-150): numpy-
  vectorized Monte Carlo over `spec.n_paths`, float internally (this is
  statistics, not ledger money — §13 convention). Independent per-trade
  Bernoulli draws (no serial correlation this batch, entry 148); barriers
  are checked after EVERY trade (intraday granularity), the MDL floor for
  a day is fixed at that day's OPEN balance, the MDD floor is static over
  the account's life. `recommended_max_risk_frac` (entry 150) re-runs the
  same spec across a fixed risk-fraction ladder with deterministically
  derived per-rung RNGs.

Empirical mode (`EmpiricalTradeModel`) is out of scope this batch — its
block-bootstrap serial-dependence machinery lands in a later batch;
calling `simulate_evaluation` with it raises `NotImplementedError` rather
than improvising untested behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal, cast

import numpy as np

from tradekit.contracts._metrics import TradeRecord
from tradekit.contracts._prop import (
    EmpiricalTradeModel,
    ParametricTradeModel,
    PropSimResult,
    PropSimSpec,
    ScriptedTradeModel,
)

_FUNDING_MARK_HOURS = (0, 4, 8, 12, 16, 20)
_CENT = Decimal("0.01")
_RISK_LADDER: tuple[Decimal, ...] = (
    Decimal("0.0025"),
    Decimal("0.005"),
    Decimal("0.0075"),
    Decimal("0.010"),
    Decimal("0.0125"),
    Decimal("0.015"),
    Decimal("0.0175"),
    Decimal("0.020"),
)


def _cents(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_EVEN)


def simulate_evaluation(spec: PropSimSpec, *, seed: int) -> PropSimResult:
    """Monte Carlo (or scripted single-path replay) of one prop evaluation
    against the absorbing MDL/MDD/target barriers. Deterministic for a
    given (spec, seed) — no wall clock, no global RNG."""
    if isinstance(spec.trade_model, ScriptedTradeModel):
        return _simulate_scripted(spec)
    if isinstance(spec.trade_model, ParametricTradeModel):
        return _simulate_parametric(spec, seed=seed)
    if isinstance(spec.trade_model, EmpiricalTradeModel):
        raise NotImplementedError("EmpiricalTradeModel is pinned in a later batch")
    raise TypeError(f"unknown trade model kind: {spec.trade_model!r}")


# --------------------------------------------------------------------------
# Scripted mode
# --------------------------------------------------------------------------


@dataclass
class _LedgerEvent:
    ts: datetime
    priority: int
    delta: Decimal


@dataclass
class _Mark:
    ts: datetime
    priority: int
    day: int


def _funding_marks(entry_ts: datetime, exit_ts: datetime) -> list[datetime]:
    marks: list[datetime] = []
    day = entry_ts.date()
    end_day = exit_ts.date()
    while day <= end_day:
        for hour in _FUNDING_MARK_HOURS:
            candidate = datetime.combine(day, time(hour, 0), tzinfo=UTC)
            if entry_ts < candidate < exit_ts:
                marks.append(candidate)
        day = day + timedelta(days=1)
    return marks


def _trade_events(
    trade: TradeRecord, fee_side_bps: Decimal, funding_daily_pct: Decimal
) -> list[_LedgerEvent]:
    entry_notional = trade.size_usd
    exit_notional = trade.size_usd * trade.exit_price / trade.entry_price
    entry_fee = entry_notional * fee_side_bps / Decimal(10_000)
    exit_fee = exit_notional * fee_side_bps / Decimal(10_000)
    move = (trade.exit_price - trade.entry_price) / trade.entry_price
    pnl = move * trade.size_usd if trade.side == "long" else -move * trade.size_usd

    events = [_LedgerEvent(ts=trade.entry_ts, priority=0, delta=-entry_fee)]
    funding_delta = -(entry_notional * funding_daily_pct / Decimal(6))
    for mark_ts in _funding_marks(trade.entry_ts, trade.exit_ts):
        events.append(_LedgerEvent(ts=mark_ts, priority=1, delta=funding_delta))
    events.append(_LedgerEvent(ts=trade.exit_ts, priority=2, delta=pnl))
    events.append(_LedgerEvent(ts=trade.exit_ts, priority=3, delta=-exit_fee))
    return events


def _day_index(ts: datetime, start_date: date) -> int:
    return (ts.date() - start_date).days + 1


def _simulate_scripted(spec: PropSimSpec) -> PropSimResult:
    model = spec.trade_model
    assert isinstance(model, ScriptedTradeModel)

    events: list[_LedgerEvent] = []
    for trade in model.trades:
        events.extend(_trade_events(trade, spec.fee_side_bps, spec.funding_daily_pct))
    events.sort(key=lambda e: (e.ts, e.priority))

    start_date = min(e.ts.date() for e in events)
    # Entry 152: a scripted event past the horizon would silently use a
    # stale MDL snapshot and report a breach outside the evaluation window
    # (internally inconsistent result) — fail loud instead.
    last_date = max(e.ts.date() for e in events)
    if (last_date - start_date).days + 1 > spec.horizon_days:
        raise ValueError(
            f"scripted trades span {(last_date - start_date).days + 1} days "
            f"but horizon_days={spec.horizon_days} — extend the horizon or "
            "trim the trade list (ASSUMPTIONS 152: never simulated silently)"
        )
    marks = [
        _Mark(
            ts=datetime.combine(
                start_date + timedelta(days=d - 1), time(0, 30), tzinfo=UTC
            ),
            priority=-1,
            day=d,
        )
        for d in range(2, spec.horizon_days + 1)
    ]

    timeline: list[tuple[datetime, int, str, object]] = [
        (e.ts, e.priority, "event", e) for e in events
    ] + [(m.ts, m.priority, "mark", m) for m in marks]
    timeline.sort(key=lambda item: (item[0], item[1]))

    starting_balance = _cents(spec.starting_balance)
    balance = starting_balance
    current_snapshot = starting_balance  # last established MDL floor reference
    # Entry 152: barrier levels stay unquantized (see MDL floor note below).
    mdd_floor = spec.starting_balance * (Decimal("1") - spec.mdd_pct)
    target_level = (
        spec.starting_balance * (Decimal("1") + spec.profit_target_pct)
        if spec.profit_target_pct is not None
        else None
    )

    daily_snapshots: list[Decimal] = [starting_balance] + [Decimal("0")] * (
        spec.horizon_days - 1
    )
    daily_breach_hazard = [0.0] * spec.horizon_days

    outcome: str | None = None
    absorption_day: int | None = None

    for _ts, _priority, kind, payload in timeline:
        if kind == "mark":
            mark = payload
            assert isinstance(mark, _Mark)
            if not outcome:
                current_snapshot = balance
            if 1 <= mark.day <= spec.horizon_days:
                daily_snapshots[mark.day - 1] = balance
            continue

        event = payload
        assert isinstance(event, _LedgerEvent)
        if outcome:
            continue

        balance = _cents(balance + event.delta)
        day = _day_index(event.ts, start_date)

        if target_level is not None and balance >= target_level:
            outcome = "passed"
            absorption_day = day
            continue

        # Entry 152: floors stay UNQUANTIZED for the compare — rounding a
        # half-cent floor down would be permissive at the boundary,
        # against entry 145b's anti-permissive direction.
        mdl_floor = current_snapshot * (Decimal("1") - spec.mdl_pct)
        hit_mdl = balance <= mdl_floor
        hit_mdd = balance <= mdd_floor
        if hit_mdl or hit_mdd:
            if hit_mdl and hit_mdd:
                reason = "mdl" if mdl_floor >= mdd_floor else "mdd"
            elif hit_mdl:
                reason = "mdl"
            else:
                reason = "mdd"
            outcome = reason
            absorption_day = day
            if 1 <= day <= spec.horizon_days:
                daily_breach_hazard[day - 1] = 1.0

    final_balance = balance

    pass_prob = 1.0 if outcome == "passed" else 0.0
    ruin_mdl = 1.0 if outcome == "mdl" else 0.0
    ruin_mdd = 1.0 if outcome == "mdd" else 0.0
    ruin_prob = ruin_mdl + ruin_mdd
    survival_prob = 1.0 if outcome is None else 0.0
    breach_reason = cast(
        "Literal['mdl', 'mdd'] | None", outcome if outcome in ("mdl", "mdd") else None
    )
    first_breach_day = absorption_day if breach_reason is not None else None
    expected_days = float(absorption_day) if absorption_day is not None else None

    equity_floats = [float(v) for v in daily_snapshots]

    return PropSimResult(
        pass_prob=pass_prob,
        ruin_prob=ruin_prob,
        ruin_prob_mdl=ruin_mdl,
        ruin_prob_mdd=ruin_mdd,
        survival_prob=survival_prob,
        expected_days_to_outcome=expected_days,
        equity_percentiles={
            "p05": list(equity_floats),
            "p50": list(equity_floats),
            "p95": list(equity_floats),
        },
        daily_breach_hazard=daily_breach_hazard,
        recommended_max_risk_frac=None,
        final_balance=final_balance,
        first_breach_day=first_breach_day,
        breach_reason=breach_reason,
        daily_snapshots=daily_snapshots,
    )


# --------------------------------------------------------------------------
# Parametric mode
# --------------------------------------------------------------------------


@dataclass
class _ParametricRunStats:
    pass_prob: float
    ruin_prob: float
    ruin_prob_mdl: float
    ruin_prob_mdd: float
    survival_prob: float
    expected_days_to_outcome: float | None
    equity_by_day: np.ndarray  # shape (horizon_days, n_paths)
    daily_breach_hazard: list[float]


def _run_parametric_paths(spec: PropSimSpec, rng: np.random.Generator) -> _ParametricRunStats:
    model = spec.trade_model
    assert isinstance(model, ParametricTradeModel)

    n_paths = spec.n_paths
    horizon_days = spec.horizon_days
    starting_balance = float(spec.starting_balance)
    mdl_pct = float(spec.mdl_pct)
    mdd_pct = float(spec.mdd_pct)
    target = (
        starting_balance * (1.0 + float(spec.profit_target_pct))
        if spec.profit_target_pct is not None
        else None
    )
    mdd_floor = starting_balance * (1.0 - mdd_pct)
    fee_side_bps = float(spec.fee_side_bps)
    funding_daily_pct = float(spec.funding_daily_pct)
    risk_frac = float(model.risk_frac)
    notional_frac = float(model.notional_frac)
    win_rate = model.win_rate
    payoff_ratio = model.payoff_ratio
    trades_per_day = model.trades_per_day
    hold_hours = model.hold_hours

    balance = np.full(n_paths, starting_balance, dtype=float)
    alive = np.ones(n_paths, dtype=bool)
    # 0 = still alive/never absorbed, 1 = mdl, 2 = mdd, 3 = passed
    absorbed_type = np.zeros(n_paths, dtype=np.int8)
    absorbed_day = np.zeros(n_paths, dtype=float)

    equity_by_day = np.empty((horizon_days, n_paths), dtype=float)
    daily_breach_hazard = [0.0] * horizon_days

    for day_idx in range(horizon_days):
        day_open_balance = balance.copy()
        mdl_floor_day = day_open_balance * (1.0 - mdl_pct)
        alive_at_open = alive.copy()
        ruined_today = np.zeros(n_paths, dtype=bool)

        for _trade_idx in range(trades_per_day):
            wins = rng.random(n_paths) < win_rate
            fee = 2.0 * notional_frac * balance * (fee_side_bps / 10_000.0)
            funding = notional_frac * balance * funding_daily_pct * (hold_hours / 24.0)
            pnl = np.where(wins, balance * risk_frac * payoff_ratio, -balance * risk_frac)
            new_balance = balance + pnl - fee - funding
            balance = np.where(alive, new_balance, balance)

            hit_target = (
                alive & (balance >= target)
                if target is not None
                else np.zeros(n_paths, dtype=bool)
            )
            hit_mdd = alive & (balance <= mdd_floor)
            hit_mdl = alive & (balance <= mdl_floor_day)

            newly_passed = hit_target
            newly_ruined = alive & (hit_mdd | hit_mdl) & ~hit_target
            use_mdl = newly_ruined & hit_mdl & (~hit_mdd | (mdl_floor_day >= mdd_floor))
            use_mdd = newly_ruined & ~use_mdl

            absorbed_type = np.where(newly_passed, 3, absorbed_type)
            absorbed_type = np.where(use_mdl, 1, absorbed_type)
            absorbed_type = np.where(use_mdd, 2, absorbed_type)
            day_number = float(day_idx + 1)
            absorbed_day = np.where(newly_passed | newly_ruined, day_number, absorbed_day)

            ruined_today |= newly_ruined
            alive = alive & ~(newly_passed | newly_ruined)

        equity_by_day[day_idx, :] = balance
        alive_open_count = int(alive_at_open.sum())
        daily_breach_hazard[day_idx] = (
            float(ruined_today.sum()) / alive_open_count if alive_open_count > 0 else 0.0
        )

    pass_count = int((absorbed_type == 3).sum())
    mdl_count = int((absorbed_type == 1).sum())
    mdd_count = int((absorbed_type == 2).sum())

    pass_prob = pass_count / n_paths
    ruin_prob_mdl = mdl_count / n_paths
    ruin_prob_mdd = mdd_count / n_paths
    ruin_prob = ruin_prob_mdl + ruin_prob_mdd
    survival_prob = 1.0 - pass_prob - ruin_prob

    absorbed_mask = absorbed_type != 0
    expected_days_to_outcome = (
        float(absorbed_day[absorbed_mask].mean()) if absorbed_mask.any() else None
    )

    return _ParametricRunStats(
        pass_prob=pass_prob,
        ruin_prob=ruin_prob,
        ruin_prob_mdl=ruin_prob_mdl,
        ruin_prob_mdd=ruin_prob_mdd,
        survival_prob=survival_prob,
        expected_days_to_outcome=expected_days_to_outcome,
        equity_by_day=equity_by_day,
        daily_breach_hazard=daily_breach_hazard,
    )


def _simulate_parametric(spec: PropSimSpec, *, seed: int) -> PropSimResult:
    rng = np.random.default_rng(seed)
    stats = _run_parametric_paths(spec, rng)
    horizon_days = spec.horizon_days

    equity_percentiles = {
        "p05": [float(np.percentile(stats.equity_by_day[d], 5)) for d in range(horizon_days)],
        "p50": [float(np.percentile(stats.equity_by_day[d], 50)) for d in range(horizon_days)],
        "p95": [float(np.percentile(stats.equity_by_day[d], 95)) for d in range(horizon_days)],
    }

    recommended_max_risk_frac = _recommend_max_risk_frac(spec, seed=seed)

    return PropSimResult(
        pass_prob=stats.pass_prob,
        ruin_prob=stats.ruin_prob,
        ruin_prob_mdl=stats.ruin_prob_mdl,
        ruin_prob_mdd=stats.ruin_prob_mdd,
        survival_prob=stats.survival_prob,
        expected_days_to_outcome=stats.expected_days_to_outcome,
        equity_percentiles=equity_percentiles,
        daily_breach_hazard=list(stats.daily_breach_hazard),
        recommended_max_risk_frac=recommended_max_risk_frac,
        final_balance=None,
        first_breach_day=None,
        breach_reason=None,
        daily_snapshots=None,
    )


def _recommend_max_risk_frac(spec: PropSimSpec, *, seed: int) -> Decimal | None:
    """Ladder scan (entry 150): largest rung with monthly ruin
    `<= spec.ruin_prob_monthly_max`, `None` if no rung clears (fail
    closed, never "the least-bad rung")."""
    model = spec.trade_model
    assert isinstance(model, ParametricTradeModel)

    best: Decimal | None = None
    for idx, rung in enumerate(_RISK_LADDER):
        rung_model = model.model_copy(update={"risk_frac": rung})
        rung_spec = spec.model_copy(update={"trade_model": rung_model})
        rng = np.random.default_rng([seed, idx])
        stats = _run_parametric_paths(rung_spec, rng)
        monthly_ruin = 1.0 - (1.0 - stats.ruin_prob) ** (30.0 / spec.horizon_days)
        if monthly_ruin <= spec.ruin_prob_monthly_max:
            best = rung
    return best


__all__ = ["simulate_evaluation"]
