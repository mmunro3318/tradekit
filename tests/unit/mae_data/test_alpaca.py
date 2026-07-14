"""tests/unit/mae_data/test_alpaca.py — story 6: Alpaca market-data provider
(raw httpx against `https://data.alpaca.markets/v2/stocks/{symbol}/bars` for
equity and `https://data.alpaca.markets/v1beta3/crypto/us/bars` for crypto,
no SDK).

Fixtures mirror Alpaca's real response shape: `{"bars": [{"t": <ISO-8601
UTC "Z">, "o":, "h":, "l":, "c":, "v":}], "next_page_token": null}`.

PRECISION CAVEAT (pinned by
`test_prices_converted_via_decimal_str_from_json_numbers`, ASSUMPTIONS 32):
unlike Kraken, Alpaca's bar prices are JSON NUMBERS, not strings. The
provider must convert every price via `Decimal(str(x))`, never `Decimal(x)`
on the raw float — `Decimal(189.43)` captures the float's binary
representation noise (`Decimal('189.4299999999999997157829...')`), silently
corrupting every price downstream. `Decimal(str(189.43))` == `Decimal(
"189.43")` is the only correct conversion. The test below asserts both
forms directly to make the failure mode undeniable.

TDD status: this test file targets `AlpacaDataProvider`, currently a
`NotImplementedError` stub (`src/tradekit/mae/_data/alpaca_data.py`) — every
test here is expected RED until story 6 is implemented.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from tradekit.contracts import AssetRef
from tradekit.mae._data.alpaca_data import (
    ALPACA_API_KEY_ID_ENV,
    ALPACA_API_SECRET_ENV,
    ALPACA_CRYPTO_BARS_URL,
    ALPACA_EQUITY_BARS_URL_TEMPLATE,
    ALPACA_TIMEFRAME_MAP,
    AlpacaDataProvider,
)
from tradekit.mae._data.errors import ProviderRangeError, ProviderRequestError, ProviderUnavailable

AAPL_EQUITY = AssetRef(
    symbol="AAPL", venue="alpaca", asset_class="equity", tick_size=Decimal("0.01")
)
BTC_USD_CRYPTO = AssetRef(
    symbol="BTC/USD", venue="alpaca", asset_class="crypto", tick_size=Decimal("0.01")
)

AAPL_EQUITY_URL = ALPACA_EQUITY_BARS_URL_TEMPLATE.format(symbol="AAPL")


def _iso_z(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _alpaca_bar(t: datetime, o: float, h: float, low: float, c: float, v: float) -> dict:
    return {"t": _iso_z(t), "o": o, "h": h, "l": low, "c": c, "v": v}


def _alpaca_bars_fixture(bars: list[dict], next_page_token: str | None = None) -> dict:
    """Realistic Alpaca bars success body (both equity and crypto share this
    flat shape)."""
    return {"bars": bars, "next_page_token": next_page_token}


@pytest.fixture
def provider() -> AlpacaDataProvider:
    return AlpacaDataProvider()


@pytest.fixture(autouse=True)
def _alpaca_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default happy-path credentials; individual tests override/delete."""
    monkeypatch.setenv(ALPACA_API_KEY_ID_ENV, "AKFAKE00000000000000")
    monkeypatch.setenv(ALPACA_API_SECRET_ENV, "fakeSecretValueXYZ")


def test_equity_route_uses_symbol_path_and_sends_auth_headers_from_env(
    provider, respx_mock
) -> None:
    """asset_class="equity" -> GET .../v2/stocks/{symbol}/bars, with the
    APCA-API-KEY-ID / APCA-API-SECRET-KEY headers populated from env."""
    t0 = datetime(2026, 1, 2, 14, 0, 0, tzinfo=UTC)
    rows = [
        _alpaca_bar(t0, 189.43, 189.90, 189.10, 189.75, 1_500_000),
        _alpaca_bar(t0 + timedelta(hours=1), 189.75, 190.20, 189.60, 190.05, 1_200_000),
    ]
    route = respx_mock.get(AAPL_EQUITY_URL).mock(
        return_value=httpx.Response(200, json=_alpaca_bars_fixture(rows))
    )

    series = provider.get_bars(AAPL_EQUITY, "1h", t0, t0 + timedelta(hours=2))

    assert route.call_count == 1
    sent = route.calls.last.request
    assert sent.headers["APCA-API-KEY-ID"] == "AKFAKE00000000000000"
    assert sent.headers["APCA-API-SECRET-KEY"] == "fakeSecretValueXYZ"
    assert len(series.bars) == 2


def test_crypto_route_uses_symbols_query_param_btcusd(provider, respx_mock) -> None:
    """asset_class="crypto" (BTC/USD) -> GET .../v1beta3/crypto/us/bars with
    a symbols=BTC/USD query param, NOT the equity path."""
    t0 = datetime(2026, 1, 2, 14, 0, 0, tzinfo=UTC)
    rows = [
        _alpaca_bar(t0, 68123.4, 68300.0, 68050.0, 68210.5, 12.5),
        _alpaca_bar(t0 + timedelta(hours=1), 68210.5, 68400.0, 68150.0, 68300.0, 9.1),
    ]
    route = respx_mock.get(ALPACA_CRYPTO_BARS_URL).mock(
        return_value=httpx.Response(200, json=_alpaca_bars_fixture(rows))
    )

    series = provider.get_bars(BTC_USD_CRYPTO, "1h", t0, t0 + timedelta(hours=2))

    assert route.call_count == 1
    sent_params = route.calls.last.request.url.params
    assert sent_params["symbols"] == "BTC/USD", (
        f"expected symbols=BTC/USD on the crypto endpoint, got {sent_params.get('symbols')!r}"
    )
    assert len(series.bars) == 2


def test_prices_converted_via_decimal_str_from_json_numbers(provider, respx_mock) -> None:
    """See module docstring: Alpaca prices are JSON numbers, so the provider
    must route them through Decimal(str(x)), never Decimal(x) directly."""
    # Demonstrate the failure mode this test guards against: Decimal on the
    # raw float captures binary-representation noise that Decimal(str(...))
    # does not.
    assert Decimal(189.43) != Decimal("189.43"), (  # noqa: RUF032 -- demonstrating the trap
        "sanity check on the precision trap itself -- if this ever becomes "
        "equal, the rest of this test's premise is void"
    )

    t0 = datetime(2026, 1, 2, 14, 0, 0, tzinfo=UTC)
    rows = [_alpaca_bar(t0, 189.43, 189.90, 189.10, 189.75, 1_500_000)]
    respx_mock.get(AAPL_EQUITY_URL).mock(
        return_value=httpx.Response(200, json=_alpaca_bars_fixture(rows))
    )

    series = provider.get_bars(AAPL_EQUITY, "1h", t0, t0 + timedelta(hours=1))

    bar = series.bars[0]
    assert isinstance(bar.open, Decimal)
    assert bar.open == Decimal("189.43"), (
        f"got {bar.open!r} — Alpaca's numeric prices must parse via Decimal(str(x)), "
        "never Decimal(x) on the raw float, or precision silently corrupts"
    )
    assert bar.high == Decimal("189.90")
    assert bar.low == Decimal("189.10")
    assert bar.close == Decimal("189.75")


@pytest.mark.parametrize(
    "canonical_tf,alpaca_tf",
    [("1m", "1Min"), ("1h", "1Hour"), ("1d", "1Day")],
    ids=["1m-to-1Min", "1h-to-1Hour", "1d-to-1Day"],
)
def test_timeframe_map_sends_alpaca_spelling(
    provider, respx_mock, canonical_tf, alpaca_tf
) -> None:
    assert ALPACA_TIMEFRAME_MAP[canonical_tf] == alpaca_tf
    t0 = datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC)
    from tradekit.contracts import TIMEFRAME_SECONDS

    end = t0 + timedelta(seconds=TIMEFRAME_SECONDS[canonical_tf])
    rows = [_alpaca_bar(t0, 100.0, 101.0, 99.0, 100.5, 10.0)]
    route = respx_mock.get(AAPL_EQUITY_URL).mock(
        return_value=httpx.Response(200, json=_alpaca_bars_fixture(rows))
    )

    provider.get_bars(AAPL_EQUITY, canonical_tf, t0, end)

    sent_params = route.calls.last.request.url.params
    assert sent_params["timeframe"] == alpaca_tf


def test_bars_ascending_aware_utc_and_source_is_alpaca(provider, respx_mock) -> None:
    t0 = datetime(2026, 1, 2, 14, 0, 0, tzinfo=UTC)
    rows = [
        _alpaca_bar(t0, 1, 1, 1, 1, 1),
        _alpaca_bar(t0 + timedelta(hours=1), 1, 1, 1, 1, 1),
        _alpaca_bar(t0 + timedelta(hours=2), 1, 1, 1, 1, 1),
    ]
    respx_mock.get(AAPL_EQUITY_URL).mock(
        return_value=httpx.Response(200, json=_alpaca_bars_fixture(rows))
    )

    series = provider.get_bars(AAPL_EQUITY, "1h", t0, t0 + timedelta(hours=3))

    opens = [b.ts_open for b in series.bars]
    assert opens == sorted(opens), "bars must come back ascending by ts_open"
    assert all(o.tzinfo is not None for o in opens), "ts_open must be aware-UTC, never naive"
    assert series.source == "alpaca", "BarSeries.source must always be the literal 'alpaca'"


def test_missing_api_key_id_env_raises_provider_request_error_no_network_call(
    provider, respx_mock, monkeypatch
) -> None:
    monkeypatch.delenv(ALPACA_API_KEY_ID_ENV, raising=False)
    t0 = datetime(2026, 1, 2, 14, 0, 0, tzinfo=UTC)
    route = respx_mock.get(AAPL_EQUITY_URL).mock(
        return_value=httpx.Response(200, json=_alpaca_bars_fixture([]))
    )

    with pytest.raises(ProviderRequestError, match="ALPACA_API_KEY_ID"):
        provider.get_bars(AAPL_EQUITY, "1h", t0, t0 + timedelta(hours=1))
    assert route.call_count == 0, (
        f"missing ALPACA_API_KEY_ID must be rejected before any HTTP call — got "
        f"{route.call_count} calls"
    )


def test_missing_api_secret_env_raises_provider_request_error_no_network_call(
    provider, respx_mock, monkeypatch
) -> None:
    monkeypatch.delenv(ALPACA_API_SECRET_ENV, raising=False)
    t0 = datetime(2026, 1, 2, 14, 0, 0, tzinfo=UTC)
    route = respx_mock.get(AAPL_EQUITY_URL).mock(
        return_value=httpx.Response(200, json=_alpaca_bars_fixture([]))
    )

    with pytest.raises(ProviderRequestError, match="ALPACA_API_SECRET"):
        provider.get_bars(AAPL_EQUITY, "1h", t0, t0 + timedelta(hours=1))
    assert route.call_count == 0, (
        f"missing ALPACA_API_SECRET must be rejected before any HTTP call — got "
        f"{route.call_count} calls"
    )


def test_http_failure_raises_provider_unavailable_never_stale(provider, respx_mock) -> None:
    """Primary OHLCV data never degrades silently (same policy as Kraken)."""
    respx_mock.get(AAPL_EQUITY_URL).mock(return_value=httpx.Response(500, text="upstream error"))
    t0 = datetime(2026, 1, 2, 14, 0, 0, tzinfo=UTC)

    with pytest.raises(ProviderUnavailable):
        provider.get_bars(AAPL_EQUITY, "1h", t0, t0 + timedelta(hours=1))


def test_next_page_token_non_null_raises_provider_range_error(provider, respx_mock) -> None:
    """Pagination is out of scope this sprint — same policy as Kraken's
    720-bar cap (ASSUMPTIONS 31/33): a non-null next_page_token must raise,
    never silently return a partial page."""
    t0 = datetime(2026, 1, 2, 14, 0, 0, tzinfo=UTC)
    rows = [_alpaca_bar(t0, 189.43, 189.90, 189.10, 189.75, 1_500_000)]
    route = respx_mock.get(AAPL_EQUITY_URL).mock(
        return_value=httpx.Response(
            200, json=_alpaca_bars_fixture(rows, next_page_token="opaque-cursor-abc123")
        )
    )

    with pytest.raises(ProviderRangeError):
        provider.get_bars(AAPL_EQUITY, "1h", t0, t0 + timedelta(hours=1))
    assert route.call_count == 1, "the call happens; it's the response that must be rejected"
