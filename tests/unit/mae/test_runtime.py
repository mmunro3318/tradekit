"""tests for tradekit.mae._runtime (SPRINT-P1C addendum "the runtime data
seam").

TEST-PATH EXCEPTION (extends ASSUMPTIONS 23/29/39): this file imports
`tradekit.mae._runtime` directly — no public verb re-exports it, same shape
as the `mae._data` / `mae._indicators` exceptions. Verb-level tests
(test_size_position_verb.py, test_correlation_verb.py) instead monkeypatch
`"tradekit.mae._runtime.get_daily_bars"` by dotted STRING path, which is not
a Python import statement and does not need this exception.

Status: `_runtime.py` is a P1C batch A STUB (every public function raises
NotImplementedError) — every test below currently fails with
NotImplementedError, which is the expected red state for this batch. The
assertions describe the REAL behavior the dev agent implements next.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tradekit.contracts import AssetRef, Bar, BarSeries
from tradekit.mae import _runtime
from tradekit.mae._data.alpaca_data import AlpacaDataProvider
from tradekit.mae._data.kraken import KrakenProvider


def _bar(ts_open: datetime, price: str = "100") -> Bar:
    return Bar(
        ts_open=ts_open,
        open=Decimal(price),
        high=Decimal(price),
        low=Decimal(price),
        close=Decimal(price),
        volume=Decimal("1000"),
    )


# ---------------------------------------------------------------------------
# provider_for routing (addendum: "/" in symbol -> Kraken; else -> Alpaca)
# ---------------------------------------------------------------------------


def test_provider_for_routes_crypto_pair_to_kraken() -> None:
    provider = _runtime.provider_for("ETH/USD")
    assert isinstance(provider, KrakenProvider), (
        "a symbol containing '/' is a crypto pair (BASE/QUOTE spelling) and must "
        "route to KrakenProvider per the addendum's routing rule"
    )


def test_provider_for_routes_equity_symbol_to_alpaca() -> None:
    provider = _runtime.provider_for("SPY")
    assert isinstance(provider, AlpacaDataProvider), (
        "a symbol without '/' is equity and must route to AlpacaDataProvider "
        "(macro tickers like ^GSPC never reach provider_for at all — only "
        "mae._data.macro handles those, per the addendum)"
    )


# ---------------------------------------------------------------------------
# clock() seam
# ---------------------------------------------------------------------------


def test_clock_seam_is_monkeypatchable(monkeypatch) -> None:
    fixed = datetime(2026, 7, 16, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(_runtime, "_clock", lambda: fixed)
    assert _runtime.clock() == fixed, (
        "clock() must delegate to the module-level _clock seam, not call "
        "datetime.now(UTC) itself — TD-17 'no real clock' in tests"
    )


# ---------------------------------------------------------------------------
# get_daily_bars: the sprint's pinned lookahead trap — live bar must be
# stripped before returning, even though the fake provider hands it back.
# ---------------------------------------------------------------------------


def test_get_daily_bars_strips_live_unclosed_bar(monkeypatch) -> None:
    # "Now" sits mid-day on 2026-07-16: the daily bar opening at
    # 2026-07-16T00:00Z closes at 2026-07-17T00:00Z, which is AFTER this
    # fixed "now" — that bar is still open ("live") and must be stripped.
    fixed_now = datetime(2026, 7, 16, 15, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(_runtime, "_clock", lambda: fixed_now)

    closed_opens = [
        datetime(2026, 7, 10, 0, 0, 0, tzinfo=UTC) + timedelta(days=i) for i in range(6)
    ]  # 07-10 .. 07-15, all closed (close time <= fixed_now)
    live_open = datetime(2026, 7, 16, 0, 0, 0, tzinfo=UTC)  # close time 07-17T00:00 > fixed_now

    all_bars = [_bar(o) for o in closed_opens] + [_bar(live_open)]

    class FakeKrakenLikeProvider:
        def get_bars(
            self, asset: AssetRef, timeframe: str, start: datetime, end: datetime
        ) -> BarSeries:
            return BarSeries(asset=asset, timeframe=timeframe, bars=all_bars, source="fake-kraken")

    monkeypatch.setattr(_runtime, "_provider_factory", lambda symbol: FakeKrakenLikeProvider())

    result = _runtime.get_daily_bars("BTC/USD", lookback_days=10)

    result_opens = [b.ts_open for b in result.bars]
    assert result_opens == closed_opens, (
        f"get_daily_bars must strip the live (unclosed) bar at {live_open!r} — "
        f"the sprint's pinned lookahead trap. Got opens: {result_opens!r}, "
        f"expected exactly the closed prefix: {closed_opens!r}"
    )
    assert live_open not in result_opens, "the live bar's ts_open must never appear in the output"
