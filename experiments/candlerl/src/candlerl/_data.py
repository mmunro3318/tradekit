"""Daily OHLCV acquisition with local parquet cache.

Primary source: Stooq CSV endpoint (keyless, ~20y of history). Fallback: yfinance.
Crypto uses Stooq's btcusd/ethusd series. Volume may be missing for crypto -> 0.
"""
from __future__ import annotations

import io
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ARTIFACTS = Path(__file__).resolve().parents[2] / "artifacts"
DATA_DIR = ARTIFACTS / "data"

STOCKS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "XOM", "JNJ", "PG",
    "KO", "WMT", "DIS", "CAT", "BA", "GE", "IBM", "INTC", "T", "CSCO",
]
CRYPTO = ["BTCUSD", "ETHUSD"]
UNIVERSE = STOCKS + CRYPTO

_COLS = ["open", "high", "low", "close", "volume"]


def _stooq_symbol(ticker: str) -> str:
    if ticker in CRYPTO:
        return ticker.lower()
    return ticker.lower() + ".us"


def _fetch_stooq(ticker: str) -> pd.DataFrame:
    url = f"https://stooq.com/q/d/l/?s={_stooq_symbol(ticker)}&i=d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    if not raw.startswith("Date"):
        raise ValueError(f"stooq returned no data for {ticker}: {raw[:80]!r}")
    df = pd.read_csv(io.StringIO(raw), parse_dates=["Date"])
    df.columns = [c.lower() for c in df.columns]
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df = df.set_index("date")[_COLS].astype(float)
    return df


def _fetch_yfinance(ticker: str) -> pd.DataFrame:
    import yfinance as yf

    yft = {"BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD"}.get(ticker, ticker)
    df = yf.download(yft, start="2000-01-01", progress=False, auto_adjust=True)
    if df is None or df.empty:
        raise ValueError(f"yfinance returned no data for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [str(c).lower() for c in df.columns]
    df.index.name = "date"
    return df[_COLS].astype(float)


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
    df = df[df["high"] >= df[["open", "close", "low"]].max(axis=1)]
    df = df[df["low"] <= df[["open", "close"]].min(axis=1)]
    df = df.dropna(subset=["open", "high", "low", "close"])
    df["volume"] = df["volume"].fillna(0.0)
    return df


def load_ohlcv(ticker: str, refresh: bool = False) -> pd.DataFrame:
    """Cached daily OHLCV, DatetimeIndex ascending."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = DATA_DIR / f"{ticker}.parquet"
    if cache.exists() and not refresh:
        return pd.read_parquet(cache)
    try:
        df = _fetch_stooq(ticker)
    except Exception:
        df = _fetch_yfinance(ticker)
    df = _clean(df)
    if len(df) < 300:
        raise ValueError(f"{ticker}: only {len(df)} usable rows")
    df.to_parquet(cache)
    return df


def load_universe(tickers: list[str] | None = None, refresh: bool = False) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for tk in tickers or UNIVERSE:
        hit_network = refresh or not (DATA_DIR / f"{tk}.parquet").exists()
        try:
            out[tk] = load_ohlcv(tk, refresh=refresh)
            if hit_network:
                time.sleep(0.3)  # throttle Stooq
        except Exception as exc:  # noqa: BLE001 - a missing ticker must not sink the run
            print(f"[data] skip {tk}: {exc}")
    return out


def summarize(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = [
        {"ticker": tk, "rows": len(df), "start": df.index[0].date(), "end": df.index[-1].date()}
        for tk, df in data.items()
    ]
    return pd.DataFrame(rows).set_index("ticker")


if __name__ == "__main__":
    data = load_universe()
    print(summarize(data).to_string())
    total = int(np.sum([len(d) for d in data.values()]))
    print(f"total rows: {total}")
