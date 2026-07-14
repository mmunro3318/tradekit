"""CoinGecko provider — `/api/v3/global` (BTC dominance) and
`/api/v3/coins/markets` (ranked coin markets) (SPRINT-P1A story 7, DESIGN §9.1).

NOT a ``MarketDataPort``: CoinGecko supplies supplementary macro data, not
OHLCV bars, so it exposes two purpose-built verbs instead of ``get_bars``
(ASSUMPTIONS 34) — it is deliberately excluded from the story-8 conformance
suite in ``tests/contract/test_marketdata_port.py``.

Supplementary-data policy note (sprint doc trap): the sprint doc's
"stale=True on simulated provider failure (degrade, never raise, for
macro)" language describes the macro/yfinance provider, which this sprint
DEFERS. CoinGecko itself still RAISES ``ProviderUnavailable`` on HTTP
failure here — degrade-to-stale is not decided for CoinGecko in this sprint
(ASSUMPTIONS 34).

STUB (TDD red phase — story 7 not yet implemented): signatures + class
docstring only, ``NotImplementedError`` bodies. See
tests/unit/mae_data/test_coingecko.py for the full behavior pin.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from tradekit.contracts import CoinMarket, GlobalCrypto
from tradekit.mae._data.errors import ProviderRequestError, ProviderUnavailable

COINGECKO_GLOBAL_URL = "https://api.coingecko.com/api/v3/global"
COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"

# Env var name (ASSUMPTIONS 35) -- never hardcode a literal key here.
COINGECKO_API_KEY_ENV = "COINGECKO_API_KEY"

# CoinGecko's demo-tier key is sent as this query param name, not a header.
COINGECKO_API_KEY_QUERY_PARAM = "x_cg_demo_api_key"

_REQUEST_TIMEOUT_S = 10.0


class CoinGeckoProvider:
    """CoinGecko macro/supplementary data provider. Two verbs, NOT a
    ``MarketDataPort`` (ASSUMPTIONS 34).
    """

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client

    def _require_api_key(self) -> str:
        # Pre-HTTP credential guard (ASSUMPTIONS 35): reject BEFORE any network call.
        api_key = os.environ.get(COINGECKO_API_KEY_ENV)
        if not api_key:
            raise ProviderRequestError(f"missing required env var {COINGECKO_API_KEY_ENV}")
        return api_key

    def _get(self, url: str, params: dict[str, str]) -> httpx.Response:
        if self._client is not None:
            return self._client.get(url, params=params, timeout=_REQUEST_TIMEOUT_S)
        return httpx.get(url, params=params, timeout=_REQUEST_TIMEOUT_S)

    def get_global(self) -> GlobalCrypto:
        """Fetch BTC dominance + total market cap from ``/api/v3/global``.

        Raises ``ProviderRequestError`` if ``COINGECKO_API_KEY`` is missing
        from the environment (no network call), ``ProviderUnavailable`` on
        HTTP 5xx/timeout (CoinGecko never degrades to ``stale=True`` here —
        see module docstring).
        """
        api_key = self._require_api_key()
        params = {COINGECKO_API_KEY_QUERY_PARAM: api_key}

        try:
            response = self._get(COINGECKO_GLOBAL_URL, params)
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"CoinGecko /global request failed: {exc}") from exc

        if response.status_code != 200:
            raise ProviderUnavailable(
                f"CoinGecko /global returned HTTP {response.status_code}: {response.text}"
            )

        data = response.json()["data"]
        return GlobalCrypto(
            btc_dominance_pct=Decimal(str(data["market_cap_percentage"]["btc"])),
            total_market_cap_usd=Decimal(str(data["total_market_cap"]["usd"])),
            ts=datetime.fromtimestamp(data["updated_at"], tz=UTC),
        )

    def get_markets(self, *, vs: str = "usd", per_page: int = 100) -> list[CoinMarket]:
        """Fetch ranked coin markets from ``/api/v3/coins/markets``.

        Raises ``ProviderRequestError`` if ``COINGECKO_API_KEY`` is missing
        from the environment (no network call), ``ProviderUnavailable`` on
        HTTP 5xx/timeout.
        """
        api_key = self._require_api_key()
        params = {
            "vs_currency": vs,
            "per_page": str(per_page),
            COINGECKO_API_KEY_QUERY_PARAM: api_key,
        }

        try:
            response = self._get(COINGECKO_MARKETS_URL, params)
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"CoinGecko /coins/markets request failed: {exc}") from exc

        if response.status_code != 200:
            raise ProviderUnavailable(
                f"CoinGecko /coins/markets returned HTTP {response.status_code}: "
                f"{response.text}"
            )

        rows = response.json()
        return [
            CoinMarket(
                coingecko_id=row["id"],
                symbol=row["symbol"],
                price_usd=Decimal(str(row["current_price"])),
                market_cap_usd=Decimal(str(row["market_cap"])),
                rank=row["market_cap_rank"],
            )
            for row in rows
        ]
