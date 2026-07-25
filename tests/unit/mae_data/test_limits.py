"""Contract + derivation tests for the pinned MTF-SCAN lookback table
(T-MTF-1, docs/design/MTF-SCAN.md lines 7-26).

TIMEFRAME_MAX_LOOKBACK_DAYS is the single source of truth for scan
lookback; these tests pin its exact contents and prove each entry leaves
headroom under Kraken's verified 720-bar retention wall (ASSUMPTIONS 161).
"""

from __future__ import annotations

from tradekit.mae._data.limits import TIMEFRAME_MAX_LOOKBACK_DAYS

# timeframe -> hours per bar, used to hand-derive the 720-bar retention
# ceiling for the headroom check below (design doc table, "720-bar
# retention" column).
_HOURS_PER_BAR = {"15m": 0.25, "1h": 1, "4h": 4, "1d": 24}


def test_table_has_exactly_the_pinned_four_entries() -> None:
    assert TIMEFRAME_MAX_LOOKBACK_DAYS == {
        "15m": 6,
        "1h": 25,
        "4h": 90,
        "1d": 365,
    }


def test_pinned_lookback_leaves_headroom_under_720_bar_retention() -> None:
    # 720 bars * hours/bar / 24 = raw retention in days (design doc
    # derivation); the pinned value must stay strictly under that so a
    # scan never requests more than Kraken actually retains.
    for timeframe, pinned_days in TIMEFRAME_MAX_LOOKBACK_DAYS.items():
        retention_days = 720 * _HOURS_PER_BAR[timeframe] / 24
        assert pinned_days < retention_days
