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

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from tradekit.contracts import AssetRef, Bar, BarSeries
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
    import yfinance as yf  # lazy import — the ONLY module that touches yfinance/pandas

    frame = yf.Ticker(ticker).history(start=start, end=end, interval="1d", auto_adjust=False)
    if frame is None or frame.empty:
        raise ValueError(f"yfinance returned no rows for ticker {ticker!r} in [{start}, {end})")

    rows: list[tuple[date, str, str, str, str, str]] = []
    for ts, row in frame.iterrows():
        row_date = ts.date() if hasattr(ts, "date") else ts
        rows.append(
            (
                row_date,
                str(row["Open"]),
                str(row["High"]),
                str(row["Low"]),
                str(row["Close"]),
                str(row["Volume"]),
            )
        )
    rows.sort(key=lambda r: r[0])
    return rows


class MacroProvider:
    """Implements `MarketDataPort` for yfinance macro tickers. `timeframe`
    must be `"1d"` — yfinance macro batching is daily-only per the addendum;
    any other value is a caller bug (this is a provider, not the never-raise
    wrapper — it validates and raises like `KrakenProvider`/
    `AlpacaDataProvider` do, it does not degrade)."""

    def get_bars(
        self, asset: AssetRef, timeframe: str, start: datetime, end: datetime
    ) -> BarSeries:
        if timeframe != "1d":
            raise ValueError(
                f"MacroProvider only supports timeframe '1d' (yfinance macro batching is "
                f"daily-only, addendum); got {timeframe!r}"
            )
        rows = _fetch_rows(asset.symbol, start, end)
        bars = [
            Bar(
                ts_open=datetime(d.year, d.month, d.day, tzinfo=UTC),
                open=Decimal(str(o)),
                high=Decimal(str(h)),
                low=Decimal(str(low)),
                close=Decimal(str(c)),
                volume=Decimal(str(v)),
            )
            for d, o, h, low, c, v in rows
            if start <= datetime(d.year, d.month, d.day, tzinfo=UTC) < end
        ]
        bars.sort(key=lambda b: b.ts_open)
        return BarSeries(asset=asset, timeframe=timeframe, bars=bars, source="yfinance")


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
    from tradekit.mae import _runtime  # "now" stays behind the one sanctioned clock seam

    asset = AssetRef(
        symbol=ticker, venue="yfinance", asset_class="macro", tick_size=Decimal("0.01")
    )
    resolved_cache = cache if cache is not None else BarCache(DEFAULT_CACHE_PATH)
    now = _runtime.clock()
    start = now - timedelta(days=lookback_days)

    try:
        return resolved_cache.get_or_fetch(
            MacroProvider().get_bars,
            source="yfinance",
            asset=asset,
            timeframe="1d",
            start=start,
            end=now,
        )
    except Exception:
        # The fallback read itself must never escape either — a sqlite
        # error reading the degraded-path cache (corrupt db, locked file,
        # etc.) is still a "we have nothing reliable to return" case, not a
        # license to raise (ASSUMPTIONS 46's never-raise pin covers this
        # WHOLE function, not just the primary fetch). `except Exception`
        # here is deliberately broad — it can mask a programming error in
        # `_read_cached_map` itself, but the never-raise contract on this
        # entrypoint is a ratified, higher-priority pin than narrow
        # exception hygiene for this one function.
        try:
            cached_map = resolved_cache._read_cached_map("yfinance", ticker, "1d")
            cached_bars = sorted(cached_map.values(), key=lambda b: b.ts_open)
        except Exception:
            cached_bars = []
        return BarSeries(
            asset=asset, timeframe="1d", bars=cached_bars, source="yfinance", stale=True
        )


__all__ = ["DEFAULT_CACHE_PATH", "MACRO_TICKERS", "MacroProvider", "get_macro_bars"]
