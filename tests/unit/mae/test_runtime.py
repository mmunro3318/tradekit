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

import pytest

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


def test_get_daily_bars_strips_live_unclosed_bar(monkeypatch, tmp_path) -> None:
    # "Now" sits mid-day on 2026-07-16: the daily bar opening at
    # 2026-07-16T00:00Z closes at 2026-07-17T00:00Z, which is AFTER this
    # fixed "now" — that bar is still open ("live") and must be stripped.
    fixed_now = datetime(2026, 7, 16, 15, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(_runtime, "_clock", lambda: fixed_now)
    # Cache-path seam: NEVER let a test write through the real data/cache.db
    # — closed bars are never invalidated, so fake fixture bars persisted
    # there under source="kraken" would be served to REAL scans forever
    # (CTO-caught defect, P1C batch A).
    monkeypatch.setattr(_runtime, "_cache_path", tmp_path / "cache.db")

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


# ---------------------------------------------------------------------------
# get_closed_bars (SPRINT-P1C batch C, `scan_markets` story): generalizes the
# get_daily_bars strip contract to any timeframe via TIMEFRAME_SECONDS.
# STUB this batch — raises NotImplementedError unconditionally. See
# _runtime.get_closed_bars's docstring for the full equivalence pin.
# ---------------------------------------------------------------------------


def test_get_closed_bars_strips_live_unclosed_bar_1h(monkeypatch, tmp_path) -> None:
    """The genuinely NEW behavior this batch: the same live-bar-stripping
    contract get_daily_bars already has for "1d", generalized to "1h" via
    TIMEFRAME_SECONDS["1h"] = 3600. RED this batch — get_closed_bars is an
    unconditional-raise stub; the dev pass implements the real strip."""
    # "Now" sits mid-hour: the hourly bar opening at 2026-07-16T14:00Z closes
    # at 2026-07-16T15:00Z, which is AFTER this fixed "now" — that bar is
    # still open ("live") and must be stripped once implemented.
    fixed_now = datetime(2026, 7, 16, 14, 30, 0, tzinfo=UTC)
    monkeypatch.setattr(_runtime, "_clock", lambda: fixed_now)
    monkeypatch.setattr(_runtime, "_cache_path", tmp_path / "cache.db")

    closed_opens = [
        datetime(2026, 7, 16, 8, 0, 0, tzinfo=UTC) + timedelta(hours=i) for i in range(6)
    ]  # 08:00 .. 13:00Z, all closed (close time <= fixed_now)
    live_open = datetime(2026, 7, 16, 14, 0, 0, tzinfo=UTC)  # close time 15:00Z > fixed_now

    all_bars = [_bar(o) for o in closed_opens] + [_bar(live_open)]

    class FakeKrakenLikeProvider:
        def get_bars(
            self, asset: AssetRef, timeframe: str, start: datetime, end: datetime
        ) -> BarSeries:
            return BarSeries(asset=asset, timeframe=timeframe, bars=all_bars, source="fake-kraken")

    monkeypatch.setattr(_runtime, "_provider_factory", lambda symbol: FakeKrakenLikeProvider())

    result = _runtime.get_closed_bars("BTC/USD", "1h", lookback_days=1)

    result_opens = [b.ts_open for b in result.bars]
    assert result_opens == closed_opens
    assert live_open not in result_opens


def test_get_closed_bars_1d_stub_and_get_daily_bars_still_behaves(monkeypatch, tmp_path) -> None:
    """Pins the SPRINT-P1C addendum equivalence: get_daily_bars(symbol,
    lookback) must become/behave as get_closed_bars(symbol, "1d", lookback)
    once the dev pass wires get_closed_bars's real body. This batch (TDD red
    phase) leaves get_daily_bars's OWN implementation untouched — reasserted
    here, staying GREEN (same fixture/assertions as
    test_get_daily_bars_strips_live_unclosed_bar, baseline ASSUMPTIONS 45) —
    while the SAME call shape through get_closed_bars(symbol, "1d", ...) is
    RED with NotImplementedError, pinned via pytest.raises so the test as a
    whole stays GREEN (documenting the current stub state precisely, not
    just letting an uncaught exception fail the test)."""
    fixed_now = datetime(2026, 7, 16, 15, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(_runtime, "_clock", lambda: fixed_now)
    monkeypatch.setattr(_runtime, "_cache_path", tmp_path / "cache.db")

    closed_opens = [
        datetime(2026, 7, 10, 0, 0, 0, tzinfo=UTC) + timedelta(days=i) for i in range(6)
    ]
    live_open = datetime(2026, 7, 16, 0, 0, 0, tzinfo=UTC)
    all_bars = [_bar(o) for o in closed_opens] + [_bar(live_open)]

    class FakeKrakenLikeProvider:
        def get_bars(
            self, asset: AssetRef, timeframe: str, start: datetime, end: datetime
        ) -> BarSeries:
            return BarSeries(asset=asset, timeframe=timeframe, bars=all_bars, source="fake-kraken")

    monkeypatch.setattr(_runtime, "_provider_factory", lambda symbol: FakeKrakenLikeProvider())

    # get_daily_bars's own, unchanged implementation — must stay green.
    daily_result = _runtime.get_daily_bars("BTC/USD", lookback_days=10)
    assert [b.ts_open for b in daily_result.bars] == closed_opens

    # get_closed_bars("1d", ...) is the addendum's pinned equivalent call
    # shape — currently an unconditional-raise stub (dev pass implements it
    # as a delegate that get_daily_bars itself will later call).
    with pytest.raises(NotImplementedError):
        _runtime.get_closed_bars("BTC/USD", "1d", lookback_days=10)
