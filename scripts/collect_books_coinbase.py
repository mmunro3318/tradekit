"""Order-book collector for Coinbase — mirrors scripts/collect_ticks.py.

Subscribes to Coinbase Advanced Trade's PUBLIC WebSocket
(wss://advanced-trade-ws.coinbase.com, channel "level2", no auth for market
data) for the greenlist pairs and appends top-20 rows to hourly-rotated
Parquet files under `books/coinbase/`.

level2 sends a full snapshot then per-level delta updates (new_quantity "0"
removes a level), so the collector replays snapshot + deltas locally
(OrderBookState, same pattern as collect_ticks). Deltas can arrive hundreds
of times per second — rows are throttled to at most one per pair per second.

WS NOTE (probed 2026-07-26): the ETH-USD level2 snapshot frame exceeds 1 MiB
(23k+ levels), larger than the `websockets` default max_size — the collector
connects with max_size=None.

Optional dependencies (`uv sync --group collector`): `websockets`, `pyarrow`
— imported lazily (AC-10 guard pattern); pure parsing/book-state/path/
throttle logic has zero dependency on them.

Parquet schema:

    book-<HH>.parquet     ts (str, ISO8601 UTC),
                          bid_price_1..20, bid_qty_1..20,
                          ask_price_1..20, ask_qty_1..20 (float or null)

Layout: <base>/<PAIR>/<YYYY-MM-DD>/book-<HH>.parquet where <base> is
D:\\tradekit-data\\books\\coinbase when the external drive is present, else
repo-local data/books/coinbase.

Run modes:
    uv run python scripts/collect_books_coinbase.py            # run forever
    uv run python scripts/collect_books_coinbase.py --smoke 60  # run 60s, print counts, exit 0
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

VENUE = "coinbase"
WS_URL = "wss://advanced-trade-ws.coinbase.com"
REST_PRODUCTS_URL = "https://api.exchange.coinbase.com/products"

_EXTERNAL_DATA_ROOT = Path("D:/tradekit-data")
_LOCAL_BOOKS_DIR = Path("data/books")

BOOK_DEPTH = 20
FLUSH_INTERVAL_S = 60.0
HEARTBEAT_TIMEOUT_S = 15.0
ROW_INTERVAL_S = 1.0

# Coinbase caps level2 product streams per WS session (probed 2026-08-08:
# 30 subscribes fine, 31 returns {"type":"error","message":"too many L2
# streams requested in a single session"}). Over the cap the server sends
# that one frame and then goes silent, which the read loop cannot distinguish
# from a dead connection — it reconnects on heartbeat timeout, re-subscribes,
# and livelocks without ever writing a row. Shard across sessions instead.
MAX_STREAMS_PER_SESSION = 30


def resolve_books_dir(
    venue: str = VENUE,
    external_root: Path = _EXTERNAL_DATA_ROOT,
    local_dir: Path = _LOCAL_BOOKS_DIR,
) -> Path:
    """`<external_root>/books/<venue>` when the external root dir exists,
    else `<local_dir>/<venue>` (same policy as collect_ticks.resolve_data_dir)."""
    if external_root.is_dir():
        return external_root / "books" / venue
    return local_dir / venue


DATA_DIR = resolve_books_dir()


# --------------------------------------------------------------------------
# Pure logic: product mapping, book state, file paths, throttle, backoff.
# No network, no optional deps — exercised directly by unit tests.
# --------------------------------------------------------------------------


def pair_to_product(pair: str) -> str:
    """Greenlist pair -> Coinbase product_id: "ETH/USD" -> "ETH-USD"."""
    return pair.replace("/", "-")


class OrderBookState:
    """Local book state for one product. level2 `update` events carry only
    changed levels (new_quantity "0" removes), so the collector replays
    snapshot + deltas to know the current top-N. Prices/qtys arrive as
    strings (observed shape, probe 2026-07-26: events[].updates[] items are
    {"side": "bid"|"offer", "event_time": ..., "price_level": "1882.19",
    "new_quantity": "3.89877"})."""

    def __init__(self) -> None:
        self._bids: dict[float, float] = {}
        self._asks: dict[float, float] = {}

    def apply_event(self, event: dict[str, Any]) -> None:
        """Apply one l2_data event (snapshot resets the book; update patches)."""
        if event.get("type") == "snapshot":
            self._bids.clear()
            self._asks.clear()
        for upd in event.get("updates", []):
            side = self._bids if upd["side"] == "bid" else self._asks
            price = float(upd["price_level"])
            qty = float(upd["new_quantity"])
            if qty <= 0:
                side.pop(price, None)
            else:
                side[price] = qty

    def top_row(self, ts: str, depth: int = BOOK_DEPTH) -> dict[str, Any]:
        row: dict[str, Any] = {"ts": ts}
        bids = sorted(self._bids.items(), key=lambda kv: kv[0], reverse=True)[:depth]
        asks = sorted(self._asks.items(), key=lambda kv: kv[0])[:depth]
        for i in range(depth):
            row[f"bid_price_{i + 1}"] = bids[i][0] if i < len(bids) else None
            row[f"bid_qty_{i + 1}"] = bids[i][1] if i < len(bids) else None
            row[f"ask_price_{i + 1}"] = asks[i][0] if i < len(asks) else None
            row[f"ask_qty_{i + 1}"] = asks[i][1] if i < len(asks) else None
        return row


def parse_l2_events(msg: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """l2_data message -> [(product_id, event), ...]; [] for other channels."""
    if msg.get("channel") != "l2_data":
        return []
    out: list[tuple[str, dict[str, Any]]] = []
    for event in msg.get("events", []):
        product = event.get("product_id")
        if product:
            out.append((product, event))
    return out


# Layout is owned by collector_core (see collect_ticks.py for why) so every
# collector agrees on where a pair lives, and PARTITION_BY_CLASS moves them
# all together.
def _pair_dirname(pair: str) -> str:
    return symbol_dirname(pair)


def book_file_path(base_dir: Path, pair: str, ts: datetime) -> Path:
    return stream_dir(base_dir, pair, ts) / f"book-{ts:%H}.parquet"


class RowThrottle:
    """At most one row per key per `interval_s` — level2 deltas can arrive
    hundreds of times per second; coalesce to 1 Hz."""

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
    """Check each pair's product against Coinbase Exchange's public products
    endpoint (status "online"). Never raises — callers log + skip."""
    result = dict.fromkeys(pairs, False)
    try:
        resp = httpx.get(REST_PRODUCTS_URL, timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        print(f"WARN: products verification failed ({exc!r}); assuming all pairs unknown")
        return result
    live = {p.get("id") for p in body if p.get("status") == "online"}
    for pair in pairs:
        result[pair] = pair_to_product(pair) in live
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
    """Connect, subscribe level2, replay snapshot+deltas, and write throttled
    top-20 rows until `duration_s` elapses (None = forever). Returns per-pair
    row counts."""
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
            print(f"WARN: pair {p} not found via products endpoint — skipping")

    sink = PartitionedParquetSink(base_dir)
    counts: dict[str, int] = dict.fromkeys(active, 0)
    throttle = RowThrottle()
    loop = asyncio.get_event_loop()
    deadline = (loop.time() + duration_s) if duration_s is not None else None

    shards = [
        active[i : i + MAX_STREAMS_PER_SESSION]
        for i in range(0, len(active), MAX_STREAMS_PER_SESSION)
    ]
    if len(shards) > 1:
        print(
            f"INFO: {len(active)} pairs over {len(shards)} sessions "
            f"(cap {MAX_STREAMS_PER_SESSION}/session)"
        )

    async def run_shard(shard: list[str]) -> None:
        product_to_pair = {pair_to_product(p): p for p in shard}
        last_flush = loop.time()
        attempt = 0
        while deadline is None or loop.time() < deadline:
            books: dict[str, OrderBookState] = {p: OrderBookState() for p in shard}
            try:
                # max_size=None: level2 snapshot frames exceed the 1 MiB default.
                async with websockets.connect(WS_URL, open_timeout=10, max_size=None) as ws:
                    attempt = 0
                    await ws.send(
                        json.dumps(
                            {
                                "type": "subscribe",
                                "channel": "level2",
                                "product_ids": [pair_to_product(p) for p in shard],
                            }
                        )
                    )
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
                        # A rejected subscribe is followed by silence, not a close
                        # — surface it instead of looping on heartbeat timeouts.
                        if msg.get("type") == "error":
                            raise RuntimeError(f"Coinbase rejected subscribe: {msg.get('message')}")
                        now = datetime.now(UTC)
                        for product, event in parse_l2_events(msg):
                            pair = product_to_pair.get(product)
                            if pair is None:
                                continue
                            books[pair].apply_event(event)
                            if not throttle.allow(pair, time.monotonic()):
                                continue
                            row = books[pair].top_row(ts=now.isoformat(), depth=BOOK_DEPTH)
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

    await asyncio.gather(*(run_shard(s) for s in shards))

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
