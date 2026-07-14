"""Kraken public OHLC provider (`/0/public/OHLC`, no key) — DESIGN §9.1.

Implements MarketDataPort. All Kraken-specific ugliness is normalized INSIDE
this module (sprint doc trap): callers never see venue pair spellings
(XBTUSD request param vs XXBTZUSD response key), never see Kraken's raw
string prices, never see epoch seconds. `get_bars` returns a canonical
BarSeries with source="kraken".
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx

from tradekit.contracts import TIMEFRAME_SECONDS, AssetRef, Bar, BarSeries
from tradekit.mae._data.errors import ProviderRangeError, ProviderRequestError, ProviderUnavailable

KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"

# Kraken's own pair spelling is cursed: request param uses one alphabet
# (XBTUSD/ETHUSD), the response `result` dict key uses another
# (XXBTZUSD/XETHZUSD). Both directions of this mapping live here, nowhere
# else (sprint doc trap).
_SYMBOL_TO_KRAKEN_PAIR: dict[str, str] = {
    "BTC/USD": "XBTUSD",
    "ETH/USD": "ETHUSD",
}
_KRAKEN_RESULT_KEY: dict[str, str] = {
    "XBTUSD": "XXBTZUSD",
    "ETHUSD": "XETHZUSD",
}

# Kraken OHLC returns at most this many bars per call; beyond it callers must
# page themselves (ProviderRangeError) — pagination is out of scope this
# sprint (its `since` semantics are a known trap, do not improvise).
MAX_BARS_PER_CALL = 720

_REQUEST_TIMEOUT_S = 10.0


class KrakenProvider:
    """Public, keyless Kraken OHLC provider. One instance per process is
    fine; no auth state to hold."""

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client

    def _get(self, params: dict[str, str | int]) -> httpx.Response:
        if self._client is not None:
            return self._client.get(KRAKEN_OHLC_URL, params=params, timeout=_REQUEST_TIMEOUT_S)
        return httpx.get(KRAKEN_OHLC_URL, params=params, timeout=_REQUEST_TIMEOUT_S)

    def get_bars(
        self, asset: AssetRef, timeframe: str, start: datetime, end: datetime
    ) -> BarSeries:
        """Fetch and normalize OHLC bars for [start, end).

        Raises ProviderRangeError if the implied bar count exceeds
        MAX_BARS_PER_CALL, ProviderRequestError on HTTP 4xx, ProviderUnavailable
        on HTTP 5xx/timeout/malformed response (never returns stale=True —
        primary OHLCV never degrades silently, sprint doc trap).
        """
        tf_seconds = TIMEFRAME_SECONDS[timeframe]

        # Pre-HTTP range guard (ASSUMPTIONS 31): reject BEFORE any network call.
        implied_bars = (end - start).total_seconds() / tf_seconds
        if implied_bars > MAX_BARS_PER_CALL:
            raise ProviderRangeError(
                f"requested range implies {implied_bars:.0f} bars > "
                f"{MAX_BARS_PER_CALL} bar cap per Kraken OHLC call"
            )

        kraken_pair = _SYMBOL_TO_KRAKEN_PAIR.get(asset.symbol)
        if kraken_pair is None:
            raise ProviderRequestError(
                f"unknown symbol {asset.symbol!r}; no Kraken pair mapping configured"
            )
        result_key = _KRAKEN_RESULT_KEY[kraken_pair]

        params: dict[str, str | int] = {
            "pair": kraken_pair,
            "interval": tf_seconds // 60,
            "since": int(start.timestamp()),
        }

        try:
            response = self._get(params)
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"Kraken OHLC request failed: {exc}") from exc

        if response.status_code != 200:
            raise ProviderUnavailable(
                f"Kraken OHLC returned HTTP {response.status_code}: {response.text}"
            )

        body = response.json()
        errors = body.get("error") or []
        if errors:
            raise ProviderUnavailable(f"Kraken OHLC error response: {errors}")

        rows = body.get("result", {}).get(result_key, [])
        bars = [
            Bar(
                ts_open=datetime.fromtimestamp(row[0], tz=UTC),
                open=Decimal(row[1]),
                high=Decimal(row[2]),
                low=Decimal(row[3]),
                close=Decimal(row[4]),
                volume=Decimal(row[6]),
            )
            for row in rows
        ]
        bars = [b for b in bars if start <= b.ts_open < end]
        bars.sort(key=lambda b: b.ts_open)

        return BarSeries(asset=asset, timeframe=timeframe, bars=bars, source="kraken")
