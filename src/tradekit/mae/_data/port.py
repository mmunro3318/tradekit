"""MarketDataPort — the venue-swap seam (DESIGN §9.1, TD-18 ring 2).

Interface pin verbatim from docs/handoff/SPRINT-P1A-data-layer.md. Every
provider (Kraken, Alpaca, CoinGecko, macro) and the cache wrapper implement
this Protocol; nothing outside tradekit.mae._data ever imports a specific
provider module directly (that would defeat the venue-swap point of a port).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from tradekit.contracts import AssetRef, BarSeries


class MarketDataPort(Protocol):
    def get_bars(
        self, asset: AssetRef, timeframe: str, start: datetime, end: datetime
    ) -> BarSeries: ...
