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
- A non-null ``next_page_token`` triggers a REAL second request carrying
  ``page_token=<token>`` (T-PAGE-1, ASSUMPTIONS 161 — supersedes
  ASSUMPTIONS 33's raise-on-token policy; Alpaca's cursor is a live opaque
  token, unlike Kraken's impossible-to-page retention wall). The loop is
  capped at ``_MAX_PAGES`` pages — exceeding it raises ``ProviderRangeError``
  naming the cap (a runaway token, not a normal fetch). An empty page stops
  the loop even if it still carries a token (never spin chasing a token past
  the data). Duplicate/overlapping bar timestamps across a page boundary
  fail loudly via ``BarSeries``'s own strict-ascending-and-unique validator
  (``contracts/_marketdata.py``) — never a silent dedupe.
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

# Hard cap on pages followed via next_page_token (T-PAGE-1) — guards against
# a runaway/looping token (upstream bug or caller typo) spinning forever.
# Exceeding it raises ProviderRangeError naming the cap; it is not a limit
# any normal fetch should approach.
_MAX_PAGES = 20


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
        """Fetch and normalize Alpaca bars for [start, end), paging
        internally while the response carries a non-null ``next_page_token``
        (T-PAGE-1).

        Raises ``ProviderRequestError`` if ``ALPACA_API_KEY_ID`` /
        ``ALPACA_API_SECRET`` are missing from the environment (no network
        call) or on HTTP 4xx (never retried, applies to every page).
        ``ProviderRangeError`` if pagination exceeds ``_MAX_PAGES`` (a
        runaway token, not a normal fetch). ``ProviderUnavailable`` on HTTP
        5xx/timeout after retries, a malformed response body, or
        duplicate/overlapping bar timestamps across a page boundary (never
        silently deduped — ``BarSeries``'s own strict-ascending validator
        catches it).
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
        base_params: dict[str, str] = {
            "timeframe": ALPACA_TIMEFRAME_MAP[timeframe],
            "start": _rfc3339(start),
            "end": _rfc3339(end),
        }

        is_crypto = asset.asset_class == "crypto"
        if is_crypto:
            url = ALPACA_CRYPTO_BARS_URL
            base_params["symbols"] = asset.symbol
        else:
            url = ALPACA_EQUITY_BARS_URL_TEMPLATE.format(symbol=asset.symbol)

        all_bars: list[Bar] = []
        page_token: str | None = None
        pages_fetched = 0
        while True:
            if pages_fetched >= _MAX_PAGES:
                raise ProviderRangeError(
                    f"Alpaca bars pagination exceeded the {_MAX_PAGES}-page cap "
                    "(a runaway next_page_token — this is not a normal fetch)"
                )
            params = dict(base_params)
            if page_token is not None:
                params["page_token"] = page_token

            def _fetch_page(p: dict[str, str] = params) -> httpx.Response:
                # Bound as a default arg (not a closure read) so each loop
                # iteration's own `params` is captured, not whatever the
                # loop variable holds when call_with_retry later calls this.
                return self._get(url, p, headers)

            acquire_blocking(self._bucket, self._sleeper)
            try:
                response = call_with_retry(
                    _fetch_page, max_attempts=3, sleeper=self._sleeper
                )
            except httpx.HTTPError as exc:
                # Non-timeout transport failures (timeouts are retried inside
                # call_with_retry and surface as ProviderUnavailable there).
                raise ProviderUnavailable(f"Alpaca bars request failed: {exc}") from exc
            pages_fetched += 1

            # M4: any structural failure while parsing a 200 body is a typed,
            # provider-named ProviderUnavailable — never a bare KeyError etc.
            try:
                body = response.json()
                if is_crypto:
                    # H1: the multi-symbol crypto endpoint keys `bars` BY SYMBOL;
                    # a missing symbol key means zero bars in the window.
                    rows = body["bars"].get(asset.symbol, [])
                else:
                    rows = body.get("bars", [])
                page_bars = [
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
            except (ValueError, KeyError, TypeError, IndexError, ArithmeticError) as exc:
                raise ProviderUnavailable(
                    f"Alpaca bars returned a malformed response body: {exc!r}"
                ) from exc

            if not page_bars:
                # Empty page: stop and treat as end-of-data even if a token
                # is still present — never spin chasing a token past the data.
                break
            all_bars.extend(page_bars)
            page_token = body.get("next_page_token")
            if page_token is None:
                break

        # BarSeries itself enforces strictly-ascending, unique ts_open
        # (contracts/_marketdata.py) — a duplicate/overlapping timestamp
        # across a page boundary raises pydantic's ValidationError (a
        # ValueError subclass), caught below and wrapped the same as any
        # other malformed body. Never silently deduped.
        try:
            all_bars = [b for b in all_bars if start <= b.ts_open < end]
            all_bars.sort(key=lambda b: b.ts_open)
            return BarSeries(asset=asset, timeframe=timeframe, bars=all_bars, source="alpaca")
        except (ValueError, KeyError, TypeError, IndexError, ArithmeticError) as exc:
            raise ProviderUnavailable(
                f"Alpaca bars returned a malformed response body: {exc!r}"
            ) from exc
