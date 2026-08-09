"""Order-book collector for Binance — mirrors scripts/collect_ticks.py.

Subscribes to Binance's PUBLIC partial-book-depth WebSocket streams
(`<symbol>@depth20@1000ms`, no auth) for the greenlist pairs and appends
top-20 rows to hourly-rotated Parquet files under `books/binance/`.

VENUE NOTE (probed 2026-07-26): api.binance.com is geo-blocked from this
machine ("Service unavailable from a restricted location"), consistent with
the repo's G6 fapi note — so this collector targets binance.US
(wss://stream.binance.us:9443). Symbols are `<BASE>USD` (e.g. ETHUSD).

Each stream message pushes the FULL top-20 snapshot every second — no delta
replay is needed. One row per pair per message, additionally throttled to at
most one row per pair per second (RowThrottle, uniform with the Coinbase
collector).

Optional dependencies (`uv sync --group collector`): `websockets`, `pyarrow`
— imported lazily (AC-10 guard pattern); pure parsing/path/throttle logic has
zero dependency on them.

Parquet schema:

    book-<HH>.parquet     ts (str, ISO8601 UTC),
                          bid_price_1..20, bid_qty_1..20,
                          ask_price_1..20, ask_qty_1..20 (float or null)

Layout: <base>/<PAIR>/<YYYY-MM-DD>/book-<HH>.parquet where <base> is
D:\\tradekit-data\\books\\binance when the external drive is present, else
repo-local data/books/binance.

Run modes:
    uv run python scripts/collect_books_binance.py            # run forever
    uv run python scripts/collect_books_binance.py --smoke 60  # run 60s, print counts, exit 0
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from collect_ticks import GREENLIST_PAIRS
from collector_core import PartitionedParquetSink, stream_dir, symbol_dirname

VENUE = "binance"
WS_BASE_URL = "wss://stream.binance.us:9443/stream"
REST_EXCHANGE_INFO_URL = "https://api.binance.us/api/v3/exchangeInfo"

_EXTERNAL_DATA_ROOT = Path("D:/tradekit-data")
_LOCAL_BOOKS_DIR = Path("data/books")

BOOK_DEPTH = 20
FLUSH_INTERVAL_S = 60.0
HEARTBEAT_TIMEOUT_S = 15.0
ROW_INTERVAL_S = 1.0


def resolve_books_dir(
    venue: str = VENUE,
    external_root: Path = _EXTERNAL_DATA_ROOT,
    local_dir: Path = _LOCAL_BOOKS_DIR,
) -> Path:
    """`<external_root>/books/<venue>` when the external root dir exists,
    else `<local_dir>/<venue>`. Checked at process start (same policy as
    collect_ticks.resolve_data_dir — vanishing drives fail loudly)."""
    if external_root.is_dir():
        return external_root / "books" / venue
    return local_dir / venue


DATA_DIR = resolve_books_dir()


# --------------------------------------------------------------------------
# Pure logic: symbol mapping, message parsing, file paths, throttle, backoff.
# No network, no optional deps — exercised directly by unit tests.
# --------------------------------------------------------------------------


def pair_to_symbol(pair: str) -> str:
    """Greenlist pair -> binance.US symbol: "ETH/USD" -> "ETHUSD"."""
    return pair.replace("/", "")


def stream_name(pair: str) -> str:
    return f"{pair_to_symbol(pair).lower()}@depth{BOOK_DEPTH}@1000ms"


def ws_url(pairs: Iterable[str]) -> str:
    return WS_BASE_URL + "?streams=" + "/".join(stream_name(p) for p in pairs)


def parse_depth_row(msg: dict[str, Any], ts: str) -> tuple[str, dict[str, Any]] | None:
    """Combined-stream depth message -> (stream_name, row) or None.

    Observed shape (probe 2026-07-26): {"stream": "ethusd@depth20@1000ms",
    "data": {"lastUpdateId": ..., "bids": [["price","qty"], ...],
    "asks": [...]}} — prices/qtys are strings."""
    stream = msg.get("stream")
    data = msg.get("data")
    if not stream or not isinstance(data, dict) or "bids" not in data:
        return None
    row: dict[str, Any] = {"ts": ts}
    bids = data.get("bids", [])
    asks = data.get("asks", [])
    for i in range(BOOK_DEPTH):
        row[f"bid_price_{i + 1}"] = float(bids[i][0]) if i < len(bids) else None
        row[f"bid_qty_{i + 1}"] = float(bids[i][1]) if i < len(bids) else None
        row[f"ask_price_{i + 1}"] = float(asks[i][0]) if i < len(asks) else None
        row[f"ask_qty_{i + 1}"] = float(asks[i][1]) if i < len(asks) else None
    return stream, row


# Layout is owned by collector_core (see collect_ticks.py for why) so every
# collector agrees on where a pair lives, and PARTITION_BY_CLASS moves them
# all together.
def _pair_dirname(pair: str) -> str:
    return symbol_dirname(pair)


def book_file_path(base_dir: Path, pair: str, ts: datetime) -> Path:
    return stream_dir(base_dir, pair, ts) / f"book-{ts:%H}.parquet"


class RowThrottle:
    """At most one row per key per `interval_s` (Coinbase level2 deltas can
    arrive hundreds of times per second; coalesce to 1 Hz)."""

    def __init__(self, interval_s: float = ROW_INTERVAL_S) -> None:
        self._interval = interval_s
        self._last: dict[str, float] = {}

    def allow(self, key: str, now: float) -> bool:
        last = self._last.get(key)
        if last is not None and now - last < self._interval:
            return False
        self._last[key] = now
        return True


def backoff_delay(attempt: int, base: float = 1.0, cap: float = 60.0) -> float:
    return min(base * (2.0**attempt), cap)


# --------------------------------------------------------------------------
# REST verification (httpx — core dep, no guard needed).
# --------------------------------------------------------------------------


def verify_pairs(pairs: Iterable[str], timeout: float = 15.0) -> dict[str, bool]:
    """Check each pair's mapped symbol against binance.US exchangeInfo
    (status TRADING). Never raises — callers log + skip."""
    result = dict.fromkeys(pairs, False)
    try:
        resp = httpx.get(REST_EXCHANGE_INFO_URL, timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        print(f"WARN: exchangeInfo verification failed ({exc!r}); assuming all pairs unknown")
        return result
    live = {s["symbol"] for s in body.get("symbols", []) if s.get("status") == "TRADING"}
    for pair in pairs:
        result[pair] = pair_to_symbol(pair) in live
    return result


# --------------------------------------------------------------------------
# Parquet sink + WS collector (optional deps — imported lazily, AC-10 guard).
# --------------------------------------------------------------------------


# The per-venue ParquetSink that used to live here is gone (2026-08-09). It
# named the hourly file from FLUSH time rather than from the row's own
# timestamp, and it wrote by read-modify-write — reading the whole hourly file
# back and rewriting it on every flush. collector_core.PartitionedParquetSink
# fixes both: event-time partitioning and append-only part files, merged by
# scripts/compact_archive.py.

async def run_collector(
    pairs: list[str], base_dir: Path = DATA_DIR, duration_s: float | None = None
) -> dict[str, int]:
    """Connect, consume depth20 snapshots until `duration_s` elapses (None =
    forever). Returns per-pair row counts."""
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError(
            "run_collector requires the optional collector dependency group — "
            "run `uv sync --group collector`"
        ) from exc

    live = verify_pairs(pairs)
    active = [p for p in pairs if live[p]]
    for p in pairs:
        if not live[p]:
            print(f"WARN: pair {p} not found via exchangeInfo — skipping")

    sink = PartitionedParquetSink(base_dir)
    counts: dict[str, int] = dict.fromkeys(active, 0)
    stream_to_pair = {stream_name(p): p for p in active}
    throttle = RowThrottle()
    loop = asyncio.get_event_loop()
    deadline = (loop.time() + duration_s) if duration_s is not None else None
    last_flush = loop.time()
    attempt = 0

    while deadline is None or loop.time() < deadline:
        try:
            async with websockets.connect(ws_url(active), open_timeout=10) as ws:
                attempt = 0
                while deadline is None or loop.time() < deadline:
                    remaining = (deadline - loop.time()) if deadline is not None else None
                    timeout = (
                        min(HEARTBEAT_TIMEOUT_S, remaining)
                        if remaining is not None
                        else HEARTBEAT_TIMEOUT_S
                    )
                    if timeout <= 0:
                        break
                    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    msg = json.loads(raw)
                    now = datetime.now(UTC)
                    parsed = parse_depth_row(msg, ts=now.isoformat())
                    if parsed is None:
                        continue
                    stream, row = parsed
                    pair = stream_to_pair.get(stream)
                    if pair is None or not throttle.allow(pair, time.monotonic()):
                        continue
                    sink.add(pair, "book", row, now)
                    counts[pair] += 1
                    if loop.time() - last_flush >= FLUSH_INTERVAL_S:
                        sink.flush_all(now)
                        last_flush = loop.time()
        except TimeoutError:
            if deadline is not None and loop.time() >= deadline:
                break
            print("WARN: heartbeat timeout — reconnecting")
        except Exception as exc:  # reconnect on any transport error
            delay = backoff_delay(attempt)
            print(f"WARN: connection error {exc!r}; reconnecting in {delay}s")
            attempt += 1
            await asyncio.sleep(delay)
        else:
            continue

    sink.flush_all(datetime.now(UTC), force=True)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", type=float, default=None, help="run N seconds then exit 0")
    args = parser.parse_args()

    counts = asyncio.run(run_collector(GREENLIST_PAIRS, duration_s=args.smoke))
    for pair, n in counts.items():
        print(f"{pair}: book_rows={n}")
    sys.exit(0)


if __name__ == "__main__":
    main()
