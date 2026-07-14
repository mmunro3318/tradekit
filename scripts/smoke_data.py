"""scripts/smoke_data.py — SPRINT-P1A Definition-of-done smoke script.

NOT a test (no pytest here; runs against the real, live Kraken API). Mike (or
any dev) runs this once by hand to confirm the KrakenProvider's normalized
output still matches the shape the respx fixtures in tests/unit/mae_data/
were captured from:

    uv run python scripts/smoke_data.py

Sprint doc's Definition of done literally asks for "30 days of BTC/USD 1h
bars from Kraken live." 30 days of 1h bars is 30 * 24 = 720 bars exactly at
the edge, but Kraken's real OHLC endpoint can return slightly MORE than 720
bars for a 30-day window depending on where `since` lands relative to the
interval grid (off-by-one bar risk), which would trip KrakenProvider's own
>720-bar range guard (see src/tradekit/mae/_data/kraken.py, ASSUMPTIONS 31)
and raise ProviderRangeError. So this script asks for the last 720 HOURS
(exactly 720 bars implied) instead of a calendar 30 days — same order of
magnitude, safely under the cap, and it still exercises the identical live
code path (pagination is explicitly out of scope this sprint).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tradekit.contracts import AssetRef
from tradekit.mae._data.kraken import KrakenProvider

BTC_USD = AssetRef(
    symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01")
)


def _fmt_bar(
    ts_open: datetime, o: Decimal, h: Decimal, low: Decimal, c: Decimal, v: Decimal
) -> str:
    return f"{ts_open.isoformat()}  O={o} H={h} L={low} C={c} V={v}"


def main() -> None:
    end = datetime.now(tz=UTC).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=720)  # exactly 720 bars implied -- at, not over, the cap

    provider = KrakenProvider()
    series = provider.get_bars(BTC_USD, "1h", start, end)

    print(f"source={series.source} asset={series.asset.symbol} timeframe={series.timeframe}")
    print(f"requested window: {start.isoformat()} -> {end.isoformat()}")
    print(f"bar count: {len(series.bars)}")

    print("\nfirst 3 bars:")
    for bar in series.bars[:3]:
        print("  " + _fmt_bar(bar.ts_open, bar.open, bar.high, bar.low, bar.close, bar.volume))

    print("\nlast 3 bars:")
    for bar in series.bars[-3:]:
        print("  " + _fmt_bar(bar.ts_open, bar.open, bar.high, bar.low, bar.close, bar.volume))

    if series.bars:
        last = series.bars[-1]
        print(
            f"\nreality matches fixtures: ohlc of last closed bar = "
            f"O={last.open} H={last.high} L={last.low} C={last.close}"
        )
    else:
        print("\nreality matches fixtures: NO BARS RETURNED — investigate before trusting cache")


if __name__ == "__main__":
    main()
