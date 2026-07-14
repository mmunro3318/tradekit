"""Bar cache — `data/cache.db`, SEPARATE from `ledger.db` (TD-22).

DESIGN CHOICE (pin this — see test_cache.py's docstring for the test-facing
half of the same decision): ``BarCache.get_or_fetch`` wraps a provider
CALLABLE, not a ``MarketDataPort`` object. cache.py therefore has zero import
dependency on any specific provider module (kraken.py, alpaca_data.py, ...);
callers pass ``provider_fn(asset, timeframe, start, end) -> BarSeries``,
typically a bound ``SomeProvider().get_bars``. This keeps the cache a small,
provider-agnostic decorator rather than growing into a second port hierarchy.

Freshness rule (no injected clock object needed — TD-17 "no real clock" is
satisfied by making time an explicit argument, not a callable): a bar is
CLOSED, hence cacheable and immutable, when its close time
(``ts_open + TIMEFRAME_SECONDS[timeframe]``) is <= the query's own ``end``.
``end`` doubles as the caller's freshness cutoff ("now"). The most recent bar
in a response whose close time is > ``end`` is the still-open "live" bar: it
is never persisted and is refetched from the provider on every call.

Key: (source, symbol, timeframe, ts_open). ``source`` comes from the
provider's own ``BarSeries.source`` (provenance always visible, §9.1).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from tradekit.contracts import AssetRef, BarSeries

ProviderFn = Callable[[AssetRef, str, datetime, datetime], BarSeries]


class BarCache:
    """SQLite-backed cache for closed bars, keyed (source, symbol, timeframe,
    ts_open). Deleting the cache file must never crash a subsequent call —
    it just means every bar refetches (pinned by test_cache.py)."""

    def __init__(self, db_path: Path) -> None:
        raise NotImplementedError("P1A story 3 — docs/handoff/SPRINT-P1A-data-layer.md")

    def get_or_fetch(
        self,
        provider_fn: ProviderFn,
        *,
        source: str,
        asset: AssetRef,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> BarSeries:
        """Return bars for [start, end), serving closed bars from the cache
        and always refetching the still-open live bar (and any bars missing
        from the cache) via ``provider_fn``. Prices/timestamps pass through
        losslessly (Decimal via str, aware-UTC datetimes)."""
        raise NotImplementedError("P1A story 3 — docs/handoff/SPRINT-P1A-data-layer.md")
