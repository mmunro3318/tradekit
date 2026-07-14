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

import httpx

from tradekit.contracts import CoinMarket, GlobalCrypto

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

    STUB: real implementation lands in the story-7 green commit — see
    ``tests/unit/mae_data/test_coingecko.py`` for the pinned behavior.
    """

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client

    def get_global(self) -> GlobalCrypto:
        """Fetch BTC dominance + total market cap from ``/api/v3/global``.

        Raises ``ProviderRequestError`` if ``COINGECKO_API_KEY`` is missing
        from the environment (no network call), ``ProviderUnavailable`` on
        HTTP 5xx/timeout (CoinGecko never degrades to ``stale=True`` here —
        see module docstring).
        """
        raise NotImplementedError("SPRINT-P1A story 7 — docs/handoff/SPRINT-P1A-data-layer.md")

    def get_markets(self, *, vs: str = "usd", per_page: int = 100) -> list[CoinMarket]:
        """Fetch ranked coin markets from ``/api/v3/coins/markets``.

        Raises ``ProviderRequestError`` if ``COINGECKO_API_KEY`` is missing
        from the environment (no network call), ``ProviderUnavailable`` on
        HTTP 5xx/timeout.
        """
        raise NotImplementedError("SPRINT-P1A story 7 — docs/handoff/SPRINT-P1A-data-layer.md")
