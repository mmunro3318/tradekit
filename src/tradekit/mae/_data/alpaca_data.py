"""Alpaca market-data provider — equity `/v2/stocks/{symbol}/bars` and crypto
`/v1beta3/crypto/us/bars` (SPRINT-P1A story 6, DESIGN §9.1).

STUB (TDD red phase — story 6 not yet implemented): signatures + class
docstring only, ``NotImplementedError`` bodies. See
tests/unit/mae_data/test_alpaca.py for the full behavior pin:

- ``asset.asset_class`` routes the request: ``"equity"`` -> the per-symbol
  equity URL, ``"crypto"`` -> the shared crypto URL with a ``symbols=``
  query param (e.g. ``BTC/USD``).
- Auth comes from env vars ``ALPACA_API_KEY_ID`` / ``ALPACA_API_SECRET``,
  sent as the ``APCA-API-KEY-ID`` / ``APCA-API-SECRET-KEY`` headers. Either
  var missing must raise a typed ``ProviderRequestError`` naming the missing
  var, with NO network call made (same "fail before the request" pattern as
  Kraken's range guard, ASSUMPTIONS 31).
- Timeframe map: ``"1m"`` -> ``"1Min"``, ``"1h"`` -> ``"1Hour"``,
  ``"1d"`` -> ``"1Day"`` (ASSUMPTIONS 33).
- Alpaca's bar prices are JSON NUMBERS, not strings (unlike Kraken) — the
  real implementation must convert via ``Decimal(str(x))``, never
  ``Decimal(x)`` on the float directly, or binary float noise becomes
  spurious price precision (ASSUMPTIONS 32).
- A non-null ``next_page_token`` in the response must raise
  ``ProviderRangeError`` — pagination is out of scope this sprint, same
  policy as Kraken's 720-bar cap (ASSUMPTIONS 33).
- HTTP 5xx/timeout -> ``ProviderUnavailable``; primary OHLCV never degrades
  to ``stale=True`` (sprint doc trap, same as Kraken).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from tradekit.contracts import AssetRef, Bar, BarSeries
from tradekit.mae._data.errors import ProviderRangeError, ProviderRequestError, ProviderUnavailable

ALPACA_EQUITY_BARS_URL_TEMPLATE = "https://data.alpaca.markets/v2/stocks/{symbol}/bars"
ALPACA_CRYPTO_BARS_URL = "https://data.alpaca.markets/v1beta3/crypto/us/bars"

# Env var names (ASSUMPTIONS 35) -- never hardcode a literal key/secret here.
ALPACA_API_KEY_ID_ENV = "ALPACA_API_KEY_ID"
ALPACA_API_SECRET_ENV = "ALPACA_API_SECRET"

ALPACA_TIMEFRAME_MAP: dict[str, str] = {
    "1m": "1Min",
    "1h": "1Hour",
    "1d": "1Day",
}

_REQUEST_TIMEOUT_S = 10.0


def _rfc3339(dt: datetime) -> str:
    """RFC-3339 UTC, "Z" suffix — Alpaca's own start/end query-param spelling."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_alpaca_ts(t: str) -> datetime:
    """Alpaca bar timestamps are ISO-8601 with a trailing "Z" — normalize to
    aware-UTC via fromisoformat (handles fractional seconds too)."""
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    return datetime.fromisoformat(t)


class AlpacaDataProvider:
    """Alpaca equity + crypto bars provider. Implements ``MarketDataPort``."""

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client

    def _get(
        self, url: str, params: dict[str, str], headers: dict[str, str]
    ) -> httpx.Response:
        if self._client is not None:
            return self._client.get(
                url, params=params, headers=headers, timeout=_REQUEST_TIMEOUT_S
            )
        return httpx.get(url, params=params, headers=headers, timeout=_REQUEST_TIMEOUT_S)

    def get_bars(
        self, asset: AssetRef, timeframe: str, start: datetime, end: datetime
    ) -> BarSeries:
        """Fetch and normalize Alpaca bars for [start, end).

        Raises ``ProviderRequestError`` if ``ALPACA_API_KEY_ID`` /
        ``ALPACA_API_SECRET`` are missing from the environment (no network
        call), ``ProviderRangeError`` if the response's ``next_page_token``
        is non-null, ``ProviderUnavailable`` on HTTP 5xx/timeout.
        """
        # Pre-HTTP credential guard (ASSUMPTIONS 35): reject BEFORE any network call.
        api_key_id = os.environ.get(ALPACA_API_KEY_ID_ENV)
        if not api_key_id:
            raise ProviderRequestError(f"missing required env var {ALPACA_API_KEY_ID_ENV}")
        api_secret = os.environ.get(ALPACA_API_SECRET_ENV)
        if not api_secret:
            raise ProviderRequestError(f"missing required env var {ALPACA_API_SECRET_ENV}")

        headers = {
            "APCA-API-KEY-ID": api_key_id,
            "APCA-API-SECRET-KEY": api_secret,
        }
        params: dict[str, str] = {
            "timeframe": ALPACA_TIMEFRAME_MAP[timeframe],
            "start": _rfc3339(start),
            "end": _rfc3339(end),
        }

        if asset.asset_class == "crypto":
            url = ALPACA_CRYPTO_BARS_URL
            params["symbols"] = asset.symbol
        else:
            url = ALPACA_EQUITY_BARS_URL_TEMPLATE.format(symbol=asset.symbol)

        try:
            response = self._get(url, params, headers)
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"Alpaca bars request failed: {exc}") from exc

        if response.status_code != 200:
            raise ProviderUnavailable(
                f"Alpaca bars returned HTTP {response.status_code}: {response.text}"
            )

        body = response.json()
        if body.get("next_page_token") is not None:
            raise ProviderRangeError(
                "Alpaca bars response carries a non-null next_page_token; "
                "pagination is out of scope this sprint (ASSUMPTIONS 33)"
            )

        rows = body.get("bars", [])
        bars = [
            Bar(
                ts_open=_parse_alpaca_ts(row["t"]),
                open=Decimal(str(row["o"])),
                high=Decimal(str(row["h"])),
                low=Decimal(str(row["l"])),
                close=Decimal(str(row["c"])),
                volume=Decimal(str(row["v"])),
            )
            for row in rows
        ]
        bars = [b for b in bars if start <= b.ts_open < end]
        bars.sort(key=lambda b: b.ts_open)

        return BarSeries(asset=asset, timeframe=timeframe, bars=bars, source="alpaca")
