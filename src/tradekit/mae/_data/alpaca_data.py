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

from datetime import datetime

import httpx

from tradekit.contracts import AssetRef, BarSeries

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


class AlpacaDataProvider:
    """Alpaca equity + crypto bars provider. Implements ``MarketDataPort``.

    STUB: real implementation lands in the story-6 green commit — see
    ``tests/unit/mae_data/test_alpaca.py`` for the pinned behavior.
    """

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client

    def get_bars(
        self, asset: AssetRef, timeframe: str, start: datetime, end: datetime
    ) -> BarSeries:
        """Fetch and normalize Alpaca bars for [start, end).

        Raises ``ProviderRequestError`` if ``ALPACA_API_KEY_ID`` /
        ``ALPACA_API_SECRET`` are missing from the environment (no network
        call), ``ProviderRangeError`` if the response's ``next_page_token``
        is non-null, ``ProviderUnavailable`` on HTTP 5xx/timeout.
        """
        raise NotImplementedError("SPRINT-P1A story 6 — docs/handoff/SPRINT-P1A-data-layer.md")
