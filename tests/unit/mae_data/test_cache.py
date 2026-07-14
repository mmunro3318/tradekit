"""tests/unit/mae_data/test_cache.py — story 3: bar cache (`data/cache.db`,
SEPARATE file from `ledger.db`, TD-22).

DESIGN CHOICE PINNED HERE (mirrors src/tradekit/mae/_data/cache.py's own
docstring): ``BarCache.get_or_fetch`` wraps a provider CALLABLE
(``provider_fn(asset, timeframe, start, end) -> BarSeries``), not a
``MarketDataPort`` object — the cache has zero import dependency on any
specific provider module. A bar is CLOSED (cacheable, immutable) when its
close time (``ts_open + TIMEFRAME_SECONDS[timeframe]``) is <= the query's
``end``; ``end`` doubles as the caller's freshness cutoff, so no separate
injected clock object is needed (TD-17: time is always an explicit argument,
never ``datetime.now()``). The most recent bar whose close time is > ``end``
is the still-open "live" bar: never persisted, always refetched.

Provider calls in these tests go over real ``httpx`` (mocked by respx) so
respx's own route ``call_count`` IS the "provider calls" counter the sprint
doc pins against (`"second fetch = zero provider calls, respx call_count==1"`)
— this module does not need the Kraken provider (story 4) to prove cache
behavior; a tiny fake HTTP-backed provider stands in.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import respx

from tradekit.contracts import TIMEFRAME_SECONDS, AssetRef
from tradekit.mae._data.cache import BarCache

FAKE_URL = "https://fake-provider.test/ohlc"
ASSET = AssetRef(symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))
TF = "1h"
TF_SECONDS = TIMEFRAME_SECONDS[TF]


def _bar_payload(ts_open: datetime, price: str) -> dict:
    return {
        "ts_open": ts_open.isoformat(),
        "open": price,
        "high": price,
        "low": price,
        "close": price,
        "volume": "1.5",
    }


def _make_provider_fn(route: respx.Route):
    """A provider_fn that fetches from FAKE_URL (mocked by `route`) and
    builds a BarSeries from the JSON body. This is the thing under test's
    call-counting: every invocation of the returned callable makes exactly
    one HTTP GET, so route.call_count == number of provider calls made."""
    from tradekit.contracts import Bar, BarSeries

    def _fn(asset, timeframe, start, end):
        resp = httpx.get(FAKE_URL, params={"start": start.isoformat(), "end": end.isoformat()})
        resp.raise_for_status()
        body = resp.json()
        bars = [
            Bar(
                ts_open=datetime.fromisoformat(b["ts_open"]),
                open=Decimal(b["open"]),
                high=Decimal(b["high"]),
                low=Decimal(b["low"]),
                close=Decimal(b["close"]),
                volume=Decimal(b["volume"]),
            )
            for b in body["bars"]
        ]
        return BarSeries(asset=asset, timeframe=timeframe, bars=bars, source="fake-provider")

    return _fn


@pytest.fixture
def cache(tmp_path):
    return BarCache(tmp_path / "cache.db")


def test_closed_bars_are_immutable_second_fetch_hits_cache(cache, respx_mock, tmp_path) -> None:
    """Two fully-closed bars, both fetches for the SAME range: the second
    call must make ZERO provider calls (respx route call_count stays 1)."""
    t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    t1 = t0 + timedelta(seconds=TF_SECONDS)
    end = t1 + timedelta(seconds=TF_SECONDS)  # both bars' close time <= end -> both CLOSED

    route = respx_mock.get(FAKE_URL).mock(
        return_value=httpx.Response(
            200,
            json={"bars": [_bar_payload(t0, "68123.45"), _bar_payload(t1, "68200.00")]},
        )
    )
    provider_fn = _make_provider_fn(route)

    first = cache.get_or_fetch(
        provider_fn, source="fake-provider", asset=ASSET, timeframe=TF, start=t0, end=end
    )
    assert len(first.bars) == 2
    assert route.call_count == 1, "first fetch must hit the provider exactly once"

    second = cache.get_or_fetch(
        provider_fn, source="fake-provider", asset=ASSET, timeframe=TF, start=t0, end=end
    )
    assert route.call_count == 1, (
        "second fetch of the SAME fully-closed range must be served entirely from "
        f"cache.db — provider was called again (call_count={route.call_count}); closed "
        "bars are supposed to be immutable"
    )
    assert second.bars == first.bars, "cache must return byte-identical bars, not a refetch"


def test_still_open_live_bar_always_refetches(cache, respx_mock) -> None:
    """The most recent bar's close time is AFTER the query's `end` -> it is
    the live bar and must be refetched on every call, never cached."""
    t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    # end sits strictly inside the bar's [open, close) window -> bar is "open".
    end = t0 + timedelta(seconds=TF_SECONDS // 2)

    route = respx_mock.get(FAKE_URL).mock(
        return_value=httpx.Response(200, json={"bars": [_bar_payload(t0, "68123.45")]})
    )
    provider_fn = _make_provider_fn(route)

    cache.get_or_fetch(
        provider_fn, source="fake-provider", asset=ASSET, timeframe=TF, start=t0, end=end
    )
    cache.get_or_fetch(
        provider_fn, source="fake-provider", asset=ASSET, timeframe=TF, start=t0, end=end
    )
    assert route.call_count == 2, (
        "the still-open bar must be refetched EVERY call — a live bar's close/high/low "
        f"can still change; got call_count={route.call_count}, expected 2"
    )


def test_deleting_cache_file_between_calls_just_causes_a_refetch(
    cache, respx_mock, tmp_path
) -> None:
    """Corrupting/removing the cache DB out from under the cache object must
    never crash — the next call just refetches from the provider."""
    t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    end = t0 + timedelta(seconds=2 * TF_SECONDS)

    route = respx_mock.get(FAKE_URL).mock(
        return_value=httpx.Response(200, json={"bars": [_bar_payload(t0, "68123.45")]})
    )
    provider_fn = _make_provider_fn(route)

    cache.get_or_fetch(
        provider_fn, source="fake-provider", asset=ASSET, timeframe=TF, start=t0, end=end
    )
    assert route.call_count == 1

    db_path = tmp_path / "cache.db"
    assert db_path.exists(), "BarCache must persist to the tmp_path db file it was given"
    db_path.unlink()

    result = cache.get_or_fetch(
        provider_fn, source="fake-provider", asset=ASSET, timeframe=TF, start=t0, end=end
    )
    assert route.call_count == 2, "missing cache file must cause a clean refetch, not a crash"
    assert len(result.bars) == 1


def test_prices_round_trip_losslessly_as_decimal(cache, respx_mock) -> None:
    """A price string that is NOT exactly representable as a binary float
    (e.g. "68123.45") must survive the cache round trip bit-for-bit."""
    t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    end = t0 + timedelta(seconds=TF_SECONDS)  # closed -> cacheable

    route = respx_mock.get(FAKE_URL).mock(
        return_value=httpx.Response(200, json={"bars": [_bar_payload(t0, "68123.45")]})
    )
    provider_fn = _make_provider_fn(route)

    cache.get_or_fetch(
        provider_fn, source="fake-provider", asset=ASSET, timeframe=TF, start=t0, end=end
    )
    from_cache = cache.get_or_fetch(
        provider_fn, source="fake-provider", asset=ASSET, timeframe=TF, start=t0, end=end
    )
    assert route.call_count == 1, "second call must be a cache hit (see immutability test)"
    bar = from_cache.bars[0]
    assert bar.open == Decimal("68123.45"), (
        f"got {bar.open!r} (type {type(bar.open).__name__}); Decimal must be parsed via str, "
        "never via float, or the cache silently corrupts prices on round-trip"
    )
    assert isinstance(bar.open, Decimal)


def test_aware_utc_datetimes_in_and_out(cache, respx_mock) -> None:
    """ts_open must remain an aware-UTC datetime after a cache round trip —
    no naive-datetime leakage through SQLite storage."""
    t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    end = t0 + timedelta(seconds=TF_SECONDS)

    route = respx_mock.get(FAKE_URL).mock(
        return_value=httpx.Response(200, json={"bars": [_bar_payload(t0, "68123.45")]})
    )
    provider_fn = _make_provider_fn(route)

    cache.get_or_fetch(
        provider_fn, source="fake-provider", asset=ASSET, timeframe=TF, start=t0, end=end
    )
    from_cache = cache.get_or_fetch(
        provider_fn, source="fake-provider", asset=ASSET, timeframe=TF, start=t0, end=end
    )
    bar = from_cache.bars[0]
    assert bar.ts_open.tzinfo is not None, "ts_open must be tz-aware coming out of the cache"
    assert bar.ts_open == t0, "ts_open value must be preserved exactly across the round trip"
