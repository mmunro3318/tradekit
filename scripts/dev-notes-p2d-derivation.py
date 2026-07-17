"""FIXTURE-FREEZE derivation script — SPRINT P2 batch D (series accounting).

Run with `uv run python <this file>` from the repo root. Every number
transcribed into tests/unit/policy/test_series.py's comments is copy-pasted
verbatim from this script's output — nothing is hand-computed in the test
file itself.

Equity base for every scenario: paper_starting_equity_usd = Decimal("500")
(PolicyDials default), zero realized pnl entering the window (first series
for the account, series_index=0 — "equity entering the window" is the dial
default with no prior graded history).

MDD walk convention (CTO addendum, story-4 pins): cumulative pnl path over
the in-window graded theses in graded_ts order, starting from
equity_entering_window; mdd_pct = max over the walk of (peak - equity) / peak
at that point (peak-to-trough as a fraction of the running peak, not of the
starting base alone — this matters once a series is up before it draws down).
"""

from decimal import Decimal, getcontext

getcontext().prec = 50

BASE_EQUITY = Decimal("500")


def walk(pnls: list[Decimal], base: Decimal = BASE_EQUITY) -> None:
    equity = base
    peak = equity
    mdd_usd = Decimal("0")
    mdd_pct = Decimal("0")
    curve = [equity]
    for p in pnls:
        equity += p
        curve.append(equity)
        if equity > peak:
            peak = equity
        dd_usd = peak - equity
        if dd_usd > mdd_usd:
            mdd_usd = dd_usd
        if peak > 0:
            dd_pct = dd_usd / peak
            if dd_pct > mdd_pct:
                mdd_pct = dd_pct
    total = sum(pnls)
    n = len(pnls)
    expectancy = total / n if n else None
    print(f"  pnls: {pnls}")
    print(f"  equity curve: {curve}")
    print(f"  total pnl: {total}")
    print(f"  expectancy (n={n}): {expectancy}")
    print(f"  mdd_usd: {mdd_usd}")
    print(f"  mdd_pct: {mdd_pct}  (= {float(mdd_pct) * 100:.6f}%)")
    print()


print("=== Scenario 1: three-pnl freeze (CTO's own worked example) ===")
print("test_series_stats_expectancy_and_mdd_arithmetic_three_trade_freeze")
walk([Decimal("5.874"), Decimal("-2.10"), Decimal("1.00")])

print("=== Scenario 2: 10-thesis CLEAN series (same 3 pnls + 7 flat zeros) ===")
print("test_series_stats_clean_ten_graded_positive_expectancy_low_mdd")
walk([Decimal("5.874"), Decimal("-2.10"), Decimal("1.00")] + [Decimal("0")] * 7)

print("=== Scenario 3: 10-thesis NOT-clean via MDD >= 15% (expectancy stays positive) ===")
print("test_series_stats_not_clean_when_mdd_pct_at_or_above_15_pct")
walk([Decimal("250"), Decimal("-130"), Decimal("40")] + [Decimal("0")] * 7)

print("=== Scenario 4: 10-thesis NOT-clean via expectancy <= 0 (mdd stays low) ===")
print("test_series_stats_not_clean_when_expectancy_not_positive")
walk([Decimal("-5")] * 10)

print("=== Scenario 5: 9 graded non-void -> INCOMPLETE (count boundary, one below 10) ===")
print("test_series_stats_nine_graded_is_incomplete_boundary")
walk([Decimal("1")] * 9)

print("=== Scenario 6: 10 graded non-void -> COMPLETE (count boundary, exactly 10) ===")
print("test_series_stats_ten_graded_is_complete_boundary (reuses scenario 2's pnls)")
# same as scenario 2 — complete AND clean; the boundary-count test only checks
# graded_count == 10 and complete == True, not the clean flag.

print("=== Scenario 7: T1->T2 aggregate — 3 clean series @ 10 graded each ===")
print("(demonstrates the >=30 non-void conjunct's floor: 3 complete series")
print(" each >=10 graded non-void sums to >=30 by construction — see")
print(" ASSUMPTIONS flag on this conjunct's redundancy given the >=10 floor)")
total_3x10 = 10 + 10 + 10
print(f"  3 x 10 = {total_3x10} (>= 30, boundary exactly met)")
