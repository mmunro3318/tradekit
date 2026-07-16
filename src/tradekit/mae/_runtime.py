"""tradekit.mae's ambient data-access seam (SPRINT-P1C addendum, "the
runtime data seam" — the sprint's one new design).

The four MAE verb signatures (`mae/__init__.py`) are pinned and take NO
port/provider argument — TD-18's venue-swap point already lives inside
`tradekit.mae._data`, and the verbs themselves must stay data-source
agnostic. Provider resolution and "now" are therefore ambient, funneled
through exactly the three functions below. This is the ONLY module in
`tradekit.mae` permitted to call `datetime.now(UTC)` — every other module
takes time as an explicit argument (TD-17 "no real clock").

Routing (addendum): "/" in `symbol` -> `KrakenProvider` (crypto pairs are
always spelled "BASE/QUOTE"); anything else -> `AlpacaDataProvider`
(equity). Macro tickers (^GSPC, ^VIX, DX-Y.NYB, GLD, TLT, ...) NEVER route
through here — only `tradekit.mae._data.macro` handles them; a caller that
passes a macro ticker to `provider_for`/`get_daily_bars` gets ordinary
equity routing, which is a caller bug, not something this seam detects.

Lookahead trap (SPRINT-P1C "Traps" section): `get_daily_bars` returns
CLOSED daily bars only. The still-open "live" bar is stripped HERE, so no
verb downstream (`size_position`, `get_correlation_matrix`, `get_regime`,
`scan_markets`) can ever leak today's incomplete bar into an indicator or a
sizing/correlation computation. `BarCache.get_or_fetch`'s own freshness
rule already keeps the live bar OUT of the persisted cache (a bar is
cacheable only once its close time <= the query's `end`), but
`get_or_fetch` still hands the live bar back in its returned `BarSeries`
on a mixed closed+live range (ASSUMPTIONS 38) — trimming that trailing
live bar before returning is this function's job.

Test seam: `_clock` and `_provider_factory` are module-level indirections
that tests monkeypatch (e.g. ``monkeypatch.setattr(
"tradekit.mae._runtime._clock", fake_clock)`` /
``"tradekit.mae._runtime._provider_factory"``) rather than patching
`clock`/`provider_for` themselves, so the public functions keep their real
bodies under test once implemented. `tests/unit/mae/test_runtime.py`
exercises this module directly — an ASSUMPTIONS internal-import exception
(extends entry 39's pattern: no public verb re-exports `_runtime`, same
shape as the `mae._data` / `mae._indicators` exceptions). Verb-level tests
(`test_size_position_verb.py`, `test_correlation_verb.py`) instead
monkeypatch ``"tradekit.mae._runtime.get_daily_bars"`` by dotted string
path, which does not require importing this module — string-path
monkeypatching is not a Python import statement and stays outside
`tests/ASSUMPTIONS.md` entry 23/29/39's internal-import exception.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from tradekit.contracts import TIMEFRAME_SECONDS, AssetRef, BarSeries
from tradekit.mae._data.alpaca_data import AlpacaDataProvider
from tradekit.mae._data.cache import BarCache
from tradekit.mae._data.kraken import KrakenProvider
from tradekit.mae._data.port import MarketDataPort

_DEFAULT_CACHE_PATH = Path("data/cache.db")
_DEFAULT_TICK_SIZE = Decimal("0.01")


def _default_clock() -> datetime:
    """Real "now" — aware UTC. The only call site in mae/ per TD-17."""
    return datetime.now(UTC)


def _default_provider_factory(symbol: str) -> MarketDataPort:
    """"/" in `symbol` -> `KrakenProvider()`; else -> `AlpacaDataProvider()`.
    One provider instance per call is acceptable here (providers hold only a
    rate-limit bucket, no per-request state); a future optimization may
    cache instances per symbol/venue, not pinned this batch."""
    if "/" in symbol:
        return KrakenProvider()
    return AlpacaDataProvider()


# Test seams (P1C addendum). Tests monkeypatch these two names directly —
# never the private helpers above, which exist only as their default values.
_clock: Callable[[], datetime] = _default_clock
_provider_factory: Callable[[str], MarketDataPort] = _default_provider_factory
# Cache-path seam: tests MUST monkeypatch this to a tmp_path — a test that
# writes through the real data/cache.db poisons production state (closed
# bars are never invalidated, so fake fixture bars would be served to real
# scans forever). Caught by the CTO gate in P1C batch A.
_cache_path: Path = _DEFAULT_CACHE_PATH


def clock() -> datetime:
    """Aware-UTC "now" via the `_clock` seam."""
    return _clock()


def provider_for(symbol: str) -> MarketDataPort:
    """Resolve the `MarketDataPort` for `symbol` via the `_provider_factory`
    seam. See module docstring for the "/" routing rule."""
    return _provider_factory(symbol)


def get_daily_bars(symbol: str, lookback_days: int) -> BarSeries:
    """CLOSED daily bars only for `symbol` over the trailing `lookback_days`,
    ending at `clock()`.

    Routes `provider_for(symbol).get_bars` through a `BarCache` (backed by
    `data/cache.db`) via `BarCache.get_or_fetch`, then trims any trailing
    bar whose close time (`ts_open + 86400s`) is strictly after `clock()`'s
    "now" — that bar is the still-open live daily candle and must never
    reach a caller of this function (the sprint's pinned lookahead trap,
    see module docstring). `lookback_days` maps to `start = end -
    timedelta(days=lookback_days)`.
    """
    is_crypto = "/" in symbol
    asset = AssetRef(
        symbol=symbol,
        venue="kraken" if is_crypto else "alpaca",
        asset_class="crypto" if is_crypto else "equity",
        tick_size=_DEFAULT_TICK_SIZE,
    )
    source = asset.venue

    now = clock()
    start = now - timedelta(days=lookback_days)

    provider = provider_for(symbol)
    cache = BarCache(_cache_path)
    series = cache.get_or_fetch(
        provider.get_bars,
        source=source,
        asset=asset,
        timeframe="1d",
        start=start,
        end=now,
    )

    tf_seconds = TIMEFRAME_SECONDS["1d"]
    closed_bars = [b for b in series.bars if (b.ts_open + timedelta(seconds=tf_seconds)) <= now]
    return BarSeries(
        asset=series.asset, timeframe=series.timeframe, bars=closed_bars, source=series.source
    )
