"""Alpaca market-data provider — equity `/v2/stocks/{symbol}/bars` and crypto
`/v1beta3/crypto/us/bars` (SPRINT-P1A story 6, DESIGN §9.1).

Behavior pins (see tests/unit/mae_data/test_alpaca.py):

- ``asset.asset_class`` routes the request: ``"equity"`` -> the per-symbol
  equity URL, ``"crypto"`` -> the shared crypto URL with a ``symbols=``
  query param (e.g. ``BTC/USD``).
- RESPONSE SHAPES DIFFER PER ENDPOINT (H1 review fix): the single-symbol
  equity endpoint returns ``{"bars": [...]}`` (flat list), but the
  multi-symbol crypto endpoint returns ``{"bars": {"BTC/USD": [...]}}`` —
  an object KEYED BY SYMBOL (Alpaca OpenAPI MultiBarsResponse). The crypto
  path reads ``body["bars"][asset.symbol]``; a missing symbol key means
  zero bars in the window, not an error.
- Auth comes from env vars ``ALPACA_API_KEY_ID`` / ``ALPACA_API_SECRET``,
  sent as the ``APCA-API-KEY-ID`` / ``APCA-API-SECRET-KEY`` headers. Either
  var missing must raise a typed ``ProviderRequestError`` naming the missing
  var, with NO network call made (same "fail before the request" pattern as
  Kraken's range guard, ASSUMPTIONS 31).
- Timeframe map: ``"1m"`` -> ``"1Min"``, ``"1h"`` -> ``"1Hour"``,
  ``"1d"`` -> ``"1Day"`` (ASSUMPTIONS 33).
- Alpaca's bar prices are JSON NUMBERS, not strings (unlike Kraken) — every
  price converts via ``Decimal(str(x))``, never ``Decimal(x)`` on the float
  directly, or binary float noise becomes spurious price precision
  (ASSUMPTIONS 32).
- A non-null ``next_page_token`` in the response must raise
  ``ProviderRangeError`` — pagination is out of scope this sprint, same
  policy as Kraken's 720-bar cap (ASSUMPTIONS 33).
- Rate limiting + retry (H2): per-instance ``bucket_for("alpaca")`` +
  ``acquire_blocking`` + ``call_with_retry``; ``clock``/``sleeper`` are
  injectable keyword-only constructor args (ASSUMPTIONS 30). Taxonomy
  (M3/M4): 4xx -> ``ProviderRequestError`` (never retried), 5xx/timeout
  after retries -> ``ProviderUnavailable``, malformed 200 body ->
  ``ProviderUnavailable`` naming Alpaca; primary OHLCV never degrades to
  ``stale=True`` (sprint doc trap, same as Kraken).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from tradekit.contracts import AssetRef, Bar, BarSeries
from tradekit.mae._data.errors import ProviderRangeError, ProviderRequestError, ProviderUnavailable
from tradekit.mae._data.ratelimit import acquire_blocking, bucket_for, call_with_retry

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

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._sleeper = sleeper
        self._bucket = bucket_for("alpaca", clock=clock)

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
        call) or on HTTP 4xx (never retried), ``ProviderRangeError`` if the
        response's ``next_page_token`` is non-null, ``ProviderUnavailable``
        on HTTP 5xx/timeout after retries or a malformed response body.
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

        is_crypto = asset.asset_class == "crypto"
        if is_crypto:
            url = ALPACA_CRYPTO_BARS_URL
            params["symbols"] = asset.symbol
        else:
            url = ALPACA_EQUITY_BARS_URL_TEMPLATE.format(symbol=asset.symbol)

        acquire_blocking(self._bucket, self._sleeper)
        try:
            response = call_with_retry(
                lambda: self._get(url, params, headers), max_attempts=3, sleeper=self._sleeper
            )
        except httpx.HTTPError as exc:
            # Non-timeout transport failures (timeouts are retried inside
            # call_with_retry and surface as ProviderUnavailable there).
            raise ProviderUnavailable(f"Alpaca bars request failed: {exc}") from exc

        # M4: any structural failure while parsing a 200 body is a typed,
        # provider-named ProviderUnavailable — never a bare KeyError etc.
        # (ProviderRangeError for pagination is a ProviderError subclass and
        # passes through the except clause below untouched.)
        try:
            body = response.json()
            if body.get("next_page_token") is not None:
                raise ProviderRangeError(
                    "Alpaca bars response carries a non-null next_page_token; "
                    "pagination is out of scope this sprint (ASSUMPTIONS 33)"
                )

            if is_crypto:
                # H1: the multi-symbol crypto endpoint keys `bars` BY SYMBOL;
                # a missing symbol key means zero bars in the window.
                rows = body["bars"].get(asset.symbol, [])
            else:
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
        except (ValueError, KeyError, TypeError, IndexError, ArithmeticError) as exc:
            raise ProviderUnavailable(
                f"Alpaca bars returned a malformed response body: {exc!r}"
            ) from exc
