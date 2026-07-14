"""Kraken public OHLC provider (`/0/public/OHLC`, no key) — DESIGN §9.1.

Implements MarketDataPort. All Kraken-specific ugliness is normalized INSIDE
this module (sprint doc trap): callers never see venue pair spellings
(XBTUSD request param vs XXBTZUSD response key), never see Kraken's raw
string prices, never see epoch seconds. `get_bars` returns a canonical
BarSeries with source="kraken".
"""

from __future__ import annotations

from datetime import datetime

import httpx

from tradekit.contracts import AssetRef, BarSeries

KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"

# Kraken's own pair spelling is cursed: request param uses one alphabet
# (XBTUSD), the response `result` dict key uses another (XXBTZUSD). Both
# directions of this mapping live here, nowhere else (sprint doc trap).
_SYMBOL_TO_KRAKEN_PAIR: dict[str, str] = {
    "BTC/USD": "XBTUSD",
}
_KRAKEN_RESULT_KEY: dict[str, str] = {
    "XBTUSD": "XXBTZUSD",
}

# Kraken OHLC returns at most this many bars per call; beyond it callers must
# page themselves (ProviderRangeError) — pagination is out of scope this
# sprint (its `since` semantics are a known trap, do not improvise).
MAX_BARS_PER_CALL = 720


class KrakenProvider:
    """Public, keyless Kraken OHLC provider. One instance per process is
    fine; no auth state to hold."""

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        raise NotImplementedError("P1A story 4 — docs/handoff/SPRINT-P1A-data-layer.md")

    def get_bars(
        self, asset: AssetRef, timeframe: str, start: datetime, end: datetime
    ) -> BarSeries:
        """Fetch and normalize OHLC bars for [start, end).

        Raises ProviderRangeError if the implied bar count exceeds
        MAX_BARS_PER_CALL, ProviderRequestError on HTTP 4xx, ProviderUnavailable
        on HTTP 5xx/timeout/malformed response (never returns stale=True —
        primary OHLCV never degrades silently, sprint doc trap).
        """
        raise NotImplementedError("P1A story 4 — docs/handoff/SPRINT-P1A-data-layer.md")
