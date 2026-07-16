"""yfinance macro/supplementary daily-bar provider (SPRINT-P1C story 0,
Mike-approved 2026-07-16; DESIGN §2.6 / §9.1 supplementary-data degradation
rules).

Completes M1.1's deferred box. Daily batch ONLY (yfinance macro tickers are
never used intraday here). `yfinance` (and pandas, which it pulls in) stay
INSIDE `tradekit.mae`, same policy as `numpy`/`hmmlearn` — never a top-level
tradekit dependency leak (the dev agent runs `uv add yfinance`; this stub
adds nothing to pyproject).

`MacroProvider` implements `MarketDataPort.get_bars` exactly like
`KrakenProvider`/`AlpacaDataProvider` do — same "raise, never degrade"
contract (ASSUMPTIONS errors.py docstring), so it composes with
`BarCache.get_or_fetch` UNMODIFIED. The degradation behavior mandated for
*supplementary* data (never for primary OHLCV, P1A conformance rule) lives
one layer up, in `get_macro_bars`: it NEVER raises. On any failure from the
cached-fetch path it returns whatever is already cached for this ticker
with `stale=True`, or `BarSeries(bars=[], stale=True, source="yfinance")`
when nothing is cached yet. Callers must branch on `.stale`, never assume a
successful call.

Tickers (MACRO_TICKERS): ^GSPC (SPX), ^VIX, DX-Y.NYB (DXY), GLD, TLT.

Test seam: `_fetch_rows` isolates the actual `yfinance.download()` /
`yfinance.Ticker.history()` call — all pandas MultiIndex-frame parsing
lives entirely inside it, so nothing else in this module touches pandas
directly. Tests monkeypatch `tradekit.mae._data.macro._fetch_rows` with
fixture rows. yfinance does NOT go through `httpx` (it uses `requests` /
`curl_cffi` under the hood), so the suite's autouse `respx_mock` zero-
network guard (`tests/conftest.py`) never sees it either way — do NOT
respx-mock Yahoo's internals (addendum); the `_fetch_rows` monkeypatch is
the only sanctioned zero-network seam for this provider.

ASSUMPTIONS internal-import exception (extends entry 39's pattern):
`tests/unit/mae_data/test_macro.py` imports this module directly — no
public verb wires macro.py into a verb's pipeline yet this batch (deferred;
non-gating per the addendum — this story may be re-deferred without
blocking the sprint's done-gate if it proves fragile).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from tradekit.contracts import AssetRef, BarSeries
from tradekit.mae._data.cache import BarCache

MACRO_TICKERS: tuple[str, ...] = ("^GSPC", "^VIX", "DX-Y.NYB", "GLD", "TLT")

DEFAULT_CACHE_PATH = Path("data/cache.db")


def _fetch_rows(
    ticker: str, start: datetime, end: datetime
) -> list[tuple[date, str, str, str, str, str]]:
    """Raw `(date, open, high, low, close, volume)` STRING rows from
    yfinance, one row per trading day in `[start, end)`, ascending by date.
    Prices are stringified here (never left as float) so callers convert via
    `Decimal(str(x))` exactly like Alpaca's provider does (ASSUMPTIONS 32) —
    yfinance, like Alpaca, returns JSON/DataFrame float columns, not
    pre-stringified venue prices like Kraken's.

    Raises on ANY failure (network, rate limit, malformed/empty frame,
    unrecognized ticker) — this function never degrades itself; that is
    `get_macro_bars`'s job, one layer up (P1A supplementary-data rule: a
    *provider* raises, only the supplementary-data WRAPPER degrades).
    """
    raise NotImplementedError("P1C batch A stub — see mae/_data/macro.py module docstring")


class MacroProvider:
    """Implements `MarketDataPort` for yfinance macro tickers. `timeframe`
    must be `"1d"` — yfinance macro batching is daily-only per the addendum;
    any other value is a caller bug (this is a provider, not the never-raise
    wrapper — it validates and raises like `KrakenProvider`/
    `AlpacaDataProvider` do, it does not degrade)."""

    def get_bars(
        self, asset: AssetRef, timeframe: str, start: datetime, end: datetime
    ) -> BarSeries:
        raise NotImplementedError("P1C batch A stub — see mae/_data/macro.py module docstring")


def get_macro_bars(
    ticker: str,
    lookback_days: int,
    *,
    cache: BarCache | None = None,
) -> BarSeries:
    """Never-raise entrypoint for one macro ticker.

    Happy path: `BarCache.get_or_fetch(MacroProvider().get_bars, ...)` —
    returns a fresh `BarSeries` with `stale=False`, `source="yfinance"`,
    ascending aware-UTC `ts_open`, Decimal-via-str prices.

    Degraded path: if the fetch raises for any reason, this function
    catches it (never propagates) and instead returns whatever `BarCache`
    already has on disk for `(source="yfinance", symbol=ticker,
    timeframe="1d")`, with `stale=True`. If the cache has nothing for this
    ticker yet, returns `BarSeries(asset=..., timeframe="1d", bars=[],
    source="yfinance", stale=True)` — an empty-but-typed result, never an
    exception.

    `cache` defaults to `BarCache(DEFAULT_CACHE_PATH)`; tests always pass an
    explicit `tmp_path`-backed instance (isolation + the suite's zero-
    network guarantee — no test may touch the real `data/cache.db`).
    """
    raise NotImplementedError("P1C batch A stub — see mae/_data/macro.py module docstring")


__all__ = ["DEFAULT_CACHE_PATH", "MACRO_TICKERS", "MacroProvider", "get_macro_bars"]
