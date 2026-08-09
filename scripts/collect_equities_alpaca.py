"""Delayed SIP tick puller for the crypto-adjacent equity complex (Alpaca).

WHY EQUITIES IN A CRYPTO ARCHIVE. Several of the most tradeable relationships
in crypto are cross-asset and none of them are visible from crypto venues
alone: spot BTC against the ETF wrapper (IBIT/FBTC/GBTC premium-discount),
spot ETH against ETHA, tokenised gold against the metal (PAXG/XAUT vs GLD),
and the equity proxies MSTR and COIN. Aligning those against tick data we
already hold is the kind of dataset nobody publishes for free.

WHY A POLLER AND NOT A WEBSOCKET. Probed 2026-08-08 on this account:

    wss://.../v2/sip          -> {"T":"error","code":409,"insufficient subscription"}
    GET /v2/stocks/trades?feed=sip&start=<now-5min>  -> 403
    GET /v2/stocks/trades?feed=sip&start=<now-20min> -> 200, full tick data

So the real-time SIP stream needs a paid plan, but the HISTORICAL SIP tape —
every print and every NBBO quote, full consolidated tape, not just IEX — is
available on the current plan behind a 15-minute delay. For an archive that
is a non-issue, so this polls on a lag instead of streaming. Free real-time
IEX is deliberately not used: it is ~2-3% of consolidated volume and would
make the series unrepresentative.

CADENCE. Each pass asks for everything from the last row we stored up to
`now - SIP_DELAY_S`, pages the cursor to exhaustion, and writes hourly part
files via collector_core. Because the request is bounded by stored state and
not by wall-clock, a restart resumes exactly where it stopped and a long
outage backfills itself.

Quotes are OFF by default. Measured 2026-08-08 over a ~5-day pull:

    COIN trades    672,789 rows    10.6 MB     (~2 MB/symbol/day)
    IBIT trades    466,800 rows     7.2 MB
    IBIT quotes  3,904,802 rows    44.5 MB     (~10-15 MB/symbol/day)

so the ten default symbols cost ~20 MB/day on trades alone but ~150 MB/day
with NBBO on all of them. `--quotes SYM,SYM` turns them on selectively —
worth it for the ETFs where the quote is the arbitrage leg, wasteful for the
miners.

Auth: ALPACA_API_KEY_ID / ALPACA_API_SECRET from the repo .env (already
present). Market data only — no trading endpoint is touched.

Run:
    uv run python scripts/collect_equities_alpaca.py --once
    uv run python scripts/collect_equities_alpaca.py --once --quotes IBIT,GLD
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collector_core import (
    PartitionedParquetSink,
    iter_symbol_dirs,
    resolve_data_root,
    symbol_dirname,
)

VENUE = "alpaca"
DATA_BASE = "https://data.alpaca.markets/v2/stocks"

# Free/basic SIP entitlement refuses any window ending inside 15 minutes.
# 60 s of slack keeps us off the boundary when clocks drift.
SIP_DELAY_S = 15 * 60 + 60
POLL_INTERVAL_S = 300.0
PAGE_LIMIT = 10_000

# The crypto-adjacent complex, all confirmed to return SIP data 2026-08-08.
DEFAULT_SYMBOLS: list[str] = [
    "COIN",  # Coinbase Global — the closest listed proxy for Base + USDC rails
    "MSTR",  # leveraged BTC balance-sheet proxy
    "HOOD",
    "IBIT",  # spot BTC ETFs — premium/discount vs our BTC/USD tape
    "FBTC",
    "GBTC",
    "ETHA",  # spot ETH ETF
    "GLD",   # gold ETF — the TradFi leg against PAXG/XAUT
    "MARA",  # miners
    "RIOT",
]


def resolve_equities_dir(venue: str = VENUE) -> Path:
    return resolve_data_root() / "equities" / venue


def auth_headers() -> dict[str, str]:
    key = os.environ.get("ALPACA_API_KEY_ID")
    secret = os.environ.get("ALPACA_API_SECRET")
    if not key or not secret:
        raise RuntimeError(
            "ALPACA_API_KEY_ID / ALPACA_API_SECRET missing from the environment — "
            "they live in the repo .env; load it before running."
        )
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def load_dotenv(path: Path) -> None:
    """Populate os.environ from the repo .env without adding a dependency."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


# What makes a row unique WITHIN one instant. Alpaca stamps every print with
# a venue trade id; NBBO quotes carry no id, so the quote itself is its
# identity — two byte-identical quotes at the same nanosecond are not two
# facts.
_IDENTITY_COLUMNS: dict[str, tuple[str, ...]] = {
    "trades": ("trade_id",),
    "quotes": ("bid_price", "bid_qty", "bid_exchange", "ask_price", "ask_qty", "ask_exchange"),
}

_HOUR_FILE_RE = re.compile(r"^(?P<stream>[A-Za-z0-9_]+)-(?P<hour>\d{2})(?:\.part-\d{4})?\.parquet$")


def row_identity(stream: str, row: Mapping[str, Any]) -> str:
    return "|".join(str(row[c]) for c in _IDENTITY_COLUMNS[stream])


def _hour_of(name: str, stream: str) -> int | None:
    m = _HOUR_FILE_RE.match(name)
    return int(m.group("hour")) if m and m.group("stream") == stream else None


def rfc3339(when: datetime) -> str:
    """Microsecond-precision RFC-3339 — the only safe format for `start`.

    `%H:%M:%SZ` silently widens the request to a whole second, and since
    Alpaca's `start` is inclusive that re-delivers the entire tail of the tape
    on every pass. See `last_stored_cursor`.
    """
    return f"{when:%Y-%m-%dT%H:%M:%S}.{when.microsecond:06d}Z"


def last_stored_cursor(
    base_dir: Path, symbol: str, stream: str
) -> tuple[datetime, set[str]] | None:
    """Where to resume, plus the identity of what we already hold there.

    Alpaca's `start` is INCLUSIVE and its timestamps carry nanoseconds, which
    leaves no purely arithmetic answer: resuming at `newest + 1us` drops any
    print inside that microsecond, and truncating to a whole second re-writes
    the tail of the tape forever (measured 2026-08-09 over the closed weekend:
    15 prints re-stored 176 times each). So the venue is asked for the
    boundary instant again and the rows we already have are dropped on
    arrival — no gap, no duplicate.

    Only the newest hour of the newest day is read. That is exact rather than
    a heuristic because the sink files every row under its own event time, so
    the newest hour directory is necessarily where the newest row lives.
    """
    import pyarrow.parquet as pq

    want = symbol_dirname(symbol)
    days = [d for d in iter_symbol_dirs(base_dir) if d.parent.name == want]
    if not days:
        return None
    day = max(days, key=lambda d: d.name)
    hours = {f.name: h for f in day.iterdir() if (h := _hour_of(f.name, stream)) is not None}
    if not hours:
        return None
    newest_hour = max(hours.values())

    newest: datetime | None = None
    held: set[str] = set()
    for name, hour in hours.items():
        if hour != newest_hour:
            continue
        try:
            table = pq.read_table(day / name, columns=["ts", *_IDENTITY_COLUMNS[stream]])
        except Exception:
            continue
        for row in table.to_pylist():
            raw = row.get("ts")
            if not raw:
                continue
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if newest is None or ts > newest:
                newest, held = ts, set()
            if ts == newest:
                held.add(row_identity(stream, row))
    return None if newest is None else (newest, held)


def fetch_pages(
    client: httpx.Client, endpoint: str, symbol: str, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    """All rows for one symbol in [start, end), following the cursor."""
    rows: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        params: dict[str, Any] = {
            "symbols": symbol,
            "start": rfc3339(start),
            "end": rfc3339(end),
            "feed": "sip",
            "limit": PAGE_LIMIT,
        }
        if token:
            params["page_token"] = token
        resp = client.get(f"{DATA_BASE}/{endpoint}", params=params)
        if resp.status_code == 403:
            print(f"WARN: {symbol} {endpoint}: 403 (window too recent for this plan)")
            return rows
        resp.raise_for_status()
        body = resp.json()
        rows.extend(body.get(endpoint, {}).get(symbol) or [])
        token = body.get("next_page_token")
        if not token:
            return rows
        time.sleep(0.12)  # stay well inside the 200 req/min basic-plan budget


def trade_row(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "ts": r["t"],
        "price": float(r["p"]),
        "qty": float(r["s"]),
        "exchange": r.get("x", ""),
        "conditions": ",".join(r.get("c", []) or []),
        "tape": r.get("z", ""),
        "trade_id": str(r.get("i", "")),
    }


def quote_row(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "ts": r["t"],
        "bid_price": float(r.get("bp", 0.0)),
        "bid_qty": float(r.get("bs", 0.0)),
        "bid_exchange": r.get("bx", ""),
        "ask_price": float(r.get("ap", 0.0)),
        "ask_qty": float(r.get("as", 0.0)),
        "ask_exchange": r.get("ax", ""),
        "tape": r.get("z", ""),
    }


def run_once(
    symbols: list[str],
    base_dir: Path,
    quote_symbols: frozenset[str] = frozenset(),
    max_lookback_days: float = 5.0,
) -> dict[str, int]:
    """One incremental pass. Returns rows written per "SYMBOL/stream"."""
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    headers = auth_headers()
    # No class partitioning: `equities/alpaca` IS the asset class. Routing
    # these through asset_class() only found no matching rule and dropped
    # every ticker into `crypto/`.
    sink = PartitionedParquetSink(base_dir, partition=False)
    written: dict[str, int] = {}
    end = datetime.now(UTC) - timedelta(seconds=SIP_DELAY_S)
    floor = end - timedelta(days=max_lookback_days)

    with httpx.Client(timeout=60, headers=headers) as client:
        for symbol in symbols:
            for stream, endpoint, to_row in (
                ("trades", "trades", trade_row),
                ("quotes", "quotes", quote_row),
            ):
                if stream == "quotes" and symbol not in quote_symbols:
                    continue
                cursor = last_stored_cursor(base_dir, symbol, stream)
                boundary, held = cursor if cursor else (None, set())
                start = max(boundary, floor) if boundary else floor
                if start >= end:
                    continue
                kept = 0
                for r in fetch_pages(client, endpoint, symbol, start, end):
                    ts = datetime.fromisoformat(r["t"].replace("Z", "+00:00"))
                    row = to_row(r)
                    # The inclusive `start` hands back the boundary instant we
                    # already stored. Only that instant is suppressed, so a
                    # trade id that recurs later is still recorded.
                    if ts == boundary and row_identity(stream, row) in held:
                        continue
                    sink.add(symbol, stream, row, ts)
                    kept += 1
                written[f"{symbol}/{stream}"] = kept
                sink.flush_all(end, force=True)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="single pass then exit")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--quotes", default="", help="comma list to also pull NBBO for")
    parser.add_argument("--base-dir", default=None)
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    quotes = frozenset(s.strip().upper() for s in args.quotes.split(",") if s.strip())
    base = Path(args.base_dir) if args.base_dir else resolve_equities_dir()

    while True:
        counts = run_once(symbols, base, quotes)
        total = sum(counts.values())
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        print(f"{stamp} rows={total} " + " ".join(f"{k}={v}" for k, v in counts.items() if v))
        if args.once:
            return
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
