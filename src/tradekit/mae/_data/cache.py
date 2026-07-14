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

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from tradekit.contracts import TIMEFRAME_SECONDS, AssetRef, Bar, BarSeries

ProviderFn = Callable[[AssetRef, str, datetime, datetime], BarSeries]

# bars table keyed (source, symbol, timeframe, ts_open); OHLCV stored as TEXT
# so Decimal round-trips via str, never float (repo-wide rule).
_SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
  source     TEXT NOT NULL,
  symbol     TEXT NOT NULL,
  timeframe  TEXT NOT NULL,
  ts_open    TEXT NOT NULL,
  open_p     TEXT NOT NULL,
  high_p     TEXT NOT NULL,
  low_p      TEXT NOT NULL,
  close_p    TEXT NOT NULL,
  volume     TEXT NOT NULL,
  PRIMARY KEY (source, symbol, timeframe, ts_open)
)
"""


def _to_stored_ts(ts: datetime) -> str:
    """Fixed-width ISO-8601 UTC — mirrors ledger._db's own convention
    (TD-16/22) so lexicographic text comparison equals chronological order
    and the value parses straight back via ``datetime.fromisoformat``."""
    return ts.astimezone(UTC).isoformat(timespec="microseconds")


class BarCache:
    """SQLite-backed cache for closed bars, keyed (source, symbol, timeframe,
    ts_open). Deleting the cache file must never crash a subsequent call —
    it just means every bar refetches (pinned by test_cache.py).

    Every operation opens its own connection and closes it before returning
    (no connection held across calls): on Windows an open sqlite3 handle
    prevents the underlying file from being deleted, and the cache-file-
    deleted-mid-run test relies on being able to unlink it between calls.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._with_connection(lambda con: None)

    def _with_connection(self, fn: Callable[[sqlite3.Connection], object]) -> object:
        """Open a fresh connection (creating the file/schema if missing —
        self-heals a deleted db file), run `fn`, then always close before
        returning so the file is never held open across calls."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self._db_path)
        try:
            con.execute(_SCHEMA)
            result = fn(con)
            con.commit()
            return result
        finally:
            con.close()

    def _read_cached(
        self,
        source: str,
        symbol: str,
        timeframe: str,
        expected_opens: list[datetime],
    ) -> list[Bar] | None:
        """Return the bars for `expected_opens` if EVERY one is cached,
        else None (a partial hit is treated as a miss — the caller then
        refetches the whole range from the provider)."""

        def _query(con: sqlite3.Connection) -> dict[str, Bar]:
            rows = con.execute(
                "SELECT ts_open, open_p, high_p, low_p, close_p, volume FROM bars "
                "WHERE source = ? AND symbol = ? AND timeframe = ?",
                (source, symbol, timeframe),
            ).fetchall()
            return {
                ts_open: Bar(
                    ts_open=datetime.fromisoformat(ts_open),
                    open=Decimal(o),
                    high=Decimal(h),
                    low=Decimal(low),
                    close=Decimal(c),
                    volume=Decimal(vol),
                )
                for ts_open, o, h, low, c, vol in rows
            }

        by_ts = self._with_connection(_query)
        assert isinstance(by_ts, dict)  # narrows for mypy; _query always returns a dict

        keys = [_to_stored_ts(ts) for ts in expected_opens]
        if not all(k in by_ts for k in keys):
            return None
        return [by_ts[k] for k in keys]

    def _upsert_closed(
        self,
        source: str,
        symbol: str,
        timeframe: str,
        tf_seconds: int,
        end: datetime,
        bars: list[Bar],
    ) -> None:
        closed = [b for b in bars if (b.ts_open + timedelta(seconds=tf_seconds)) <= end]
        if not closed:
            return

        def _write(con: sqlite3.Connection) -> None:
            con.executemany(
                "INSERT OR REPLACE INTO bars "
                "(source, symbol, timeframe, ts_open, open_p, high_p, low_p, close_p, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        source,
                        symbol,
                        timeframe,
                        _to_stored_ts(b.ts_open),
                        str(b.open),
                        str(b.high),
                        str(b.low),
                        str(b.close),
                        str(b.volume),
                    )
                    for b in closed
                ],
            )

        self._with_connection(_write)

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
        tf_seconds = TIMEFRAME_SECONDS[timeframe]
        total_seconds = (end - start).total_seconds()
        full_periods = int(total_seconds // tf_seconds)
        remainder = total_seconds - full_periods * tf_seconds
        has_live_bar = remainder > 1e-9  # end falls strictly inside a bar's window

        expected_opens = [start + timedelta(seconds=i * tf_seconds) for i in range(full_periods)]

        if not has_live_bar and expected_opens:
            cached_bars = self._read_cached(source, asset.symbol, timeframe, expected_opens)
            if cached_bars is not None:
                return BarSeries(asset=asset, timeframe=timeframe, bars=cached_bars, source=source)

        series = provider_fn(asset, timeframe, start, end)
        self._upsert_closed(source, asset.symbol, timeframe, tf_seconds, end, series.bars)
        return series
