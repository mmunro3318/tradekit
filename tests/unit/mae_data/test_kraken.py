"""tests/unit/mae_data/test_kraken.py — story 4: Kraken public OHLC provider
(`/0/public/OHLC`, no key).

Fixtures below mirror Kraken's REAL response shape: `result` is keyed by the
venue's own pair spelling ("XXBTZUSD"), rows are
[ts_sec, open, high, low, close, vwap, volume, count] with STRING prices, the
LAST row is the still-open bar, and a top-level "last" field (next `since`
cursor) sits alongside the pair key inside `result`.

Kraken's cursed pair-spelling split (request param "XBTUSD" vs response key
"XXBTZUSD") is normalized INSIDE KrakenProvider — nothing outside
tradekit.mae._data ever sees either spelling (sprint doc trap).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from tradekit.contracts import AssetRef
from tradekit.mae._data.errors import ProviderRangeError, ProviderUnavailable
from tradekit.mae._data.kraken import KRAKEN_OHLC_URL, KrakenProvider

BTC_USD = AssetRef(
    symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01")
)


def _kraken_ohlc_fixture(rows: list[list]) -> dict:
    """Realistic /0/public/OHLC success body."""
    return {
        "error": [],
        "result": {
            "XXBTZUSD": rows,
            "last": rows[-1][0] if rows else 0,
        },
    }


def _row(ts_sec: int, o: str, h: str, low: str, c: str, vwap: str, vol: str, count: int) -> list:
    return [ts_sec, o, h, low, c, vwap, vol, count]


@pytest.fixture
def provider() -> KrakenProvider:
    return KrakenProvider()


def test_symbol_mapping_btcusd_to_xbtusd_request_and_xxbtzusd_response(
    provider, respx_mock
) -> None:
    """BTC/USD -> request param pair=XBTUSD; response result key XXBTZUSD is
    the one read back. Both mappings live inside the provider."""
    t0 = int(datetime(2026, 1, 1, 0, 0, tzinfo=UTC).timestamp())
    rows = [
        _row(t0, "68100.0", "68150.0", "68050.0", "68123.4", "68110.0", "12.5", 50),
        _row(t0 + 3600, "68123.4", "68300.0", "68100.0", "68250.0", "68200.0", "9.1", 40),
    ]
    route = respx_mock.get(KRAKEN_OHLC_URL).mock(
        return_value=httpx.Response(200, json=_kraken_ohlc_fixture(rows))
    )

    start = datetime.fromtimestamp(t0, tz=UTC)
    end = datetime.fromtimestamp(t0 + 7200, tz=UTC)
    series = provider.get_bars(BTC_USD, "1h", start, end)

    assert route.call_count == 1
    sent_params = route.calls.last.request.url.params
    assert sent_params["pair"] == "XBTUSD", (
        f"expected the venue-spelled request param 'XBTUSD' for BTC/USD, got "
        f"{sent_params.get('pair')!r} — symbol mapping must happen inside KrakenProvider"
    )
    assert len(series.bars) == 2, "must read the XXBTZUSD response key, not fail to find data"


def test_prices_parsed_as_decimal_from_kraken_strings_exactly(provider, respx_mock) -> None:
    t0 = int(datetime(2026, 1, 1, 0, 0, tzinfo=UTC).timestamp())
    rows = [_row(t0, "68123.4", "68200.0", "68100.0", "68150.0", "68140.0", "5.0", 10)]
    respx_mock.get(KRAKEN_OHLC_URL).mock(
        return_value=httpx.Response(200, json=_kraken_ohlc_fixture(rows))
    )

    start = datetime.fromtimestamp(t0, tz=UTC)
    end = datetime.fromtimestamp(t0 + 3600, tz=UTC)
    series = provider.get_bars(BTC_USD, "1h", start, end)

    bar = series.bars[0]
    assert bar.open == Decimal("68123.4"), (
        f"got {bar.open!r} — Kraken's OHLC strings must parse via Decimal(str), never via "
        "float(...), or prices silently corrupt (repo-wide rule)"
    )
    assert isinstance(bar.open, Decimal)
    assert bar.high == Decimal("68200.0")
    assert bar.low == Decimal("68100.0")
    assert bar.close == Decimal("68150.0")


def test_ts_seconds_become_aware_utc_ts_open(provider, respx_mock) -> None:
    t0 = int(datetime(2026, 3, 5, 12, 30, 0, tzinfo=UTC).timestamp())
    rows = [_row(t0, "1", "1", "1", "1", "1", "1", 1)]
    respx_mock.get(KRAKEN_OHLC_URL).mock(
        return_value=httpx.Response(200, json=_kraken_ohlc_fixture(rows))
    )
    start = datetime.fromtimestamp(t0, tz=UTC)
    end = datetime.fromtimestamp(t0 + 3600, tz=UTC)
    series = provider.get_bars(BTC_USD, "1h", start, end)

    assert series.bars[0].ts_open == datetime(2026, 3, 5, 12, 30, 0, tzinfo=UTC)
    assert series.bars[0].ts_open.tzinfo is not None, (
        "epoch seconds must become aware-UTC, never naive"
    )


def test_bars_ascending_and_source_is_kraken(provider, respx_mock) -> None:
    t0 = int(datetime(2026, 1, 1, 0, 0, tzinfo=UTC).timestamp())
    rows = [
        _row(t0, "1", "1", "1", "1", "1", "1", 1),
        _row(t0 + 3600, "1", "1", "1", "1", "1", "1", 1),
        _row(t0 + 7200, "1", "1", "1", "1", "1", "1", 1),
    ]
    respx_mock.get(KRAKEN_OHLC_URL).mock(
        return_value=httpx.Response(200, json=_kraken_ohlc_fixture(rows))
    )
    start = datetime.fromtimestamp(t0, tz=UTC)
    end = datetime.fromtimestamp(t0 + 10800, tz=UTC)
    series = provider.get_bars(BTC_USD, "1h", start, end)

    opens = [b.ts_open for b in series.bars]
    assert opens == sorted(opens), "bars must come back strictly ascending by ts_open"
    assert series.source == "kraken", "BarSeries.source must always be the literal 'kraken'"


def test_range_over_720_bars_raises_provider_range_error_no_http_call(provider, respx_mock) -> None:
    """Kraken OHLC returns at most ~720 bars per call; a wider request must
    raise BEFORE hitting the network, not silently truncate or paginate
    (pagination's `since` semantics are a known trap, out of scope)."""
    route = respx_mock.get(KRAKEN_OHLC_URL).mock(
        return_value=httpx.Response(200, json=_kraken_ohlc_fixture([]))
    )
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(minutes=721)  # 721 one-minute bars > 720 cap

    with pytest.raises(ProviderRangeError):
        provider.get_bars(BTC_USD, "1m", start, end)
    assert route.call_count == 0, (
        "an over-range request must be rejected before any HTTP call is made — "
        f"got {route.call_count} calls"
    )


def test_http_failure_raises_provider_unavailable_never_stale(provider, respx_mock) -> None:
    """Primary OHLCV data never degrades silently: an HTTP failure must
    raise ProviderUnavailable, never return a stale=True BarSeries."""
    respx_mock.get(KRAKEN_OHLC_URL).mock(return_value=httpx.Response(500, text="upstream error"))
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)

    with pytest.raises(ProviderUnavailable):
        provider.get_bars(BTC_USD, "1h", start, end)
