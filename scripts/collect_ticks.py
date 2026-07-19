"""Tick/book collector for the P5-PROP greenlist (SPRINT-P5-PROP §2c, Q.F.83).

Subscribes to Kraken's PUBLIC WebSocket v2 (wss://ws.kraken.com/v2, no auth
required) `trade` and `book` (depth 10) channels for the greenlist pairs and
appends rows to hourly-rotated Parquet files under `data/ticks/`.

Optional dependencies (NEW, not in core deps — `uv sync --group collector`):
`websockets` (WS v2 client) and `pyarrow` (Parquet sink). Import of this
module never requires either — only `run_collector()` / `--smoke` / normal
execution do (AC-10 guard pattern, mirrors `tradekit.bridge._pywinauto`).
Pure parsing/path/prune/backoff logic below has zero dependency on them.

Parquet schema (documented here, kept simple — no nested/list columns):

    trades-<HH>.parquet   ts (str, ISO8601 UTC), price (float), qty (float),
                          side (str: "buy"/"sell"), ord_type (str)

    book-<HH>.parquet     ts (str, ISO8601 UTC),
                          bid_price_1..10, bid_qty_1..10,
                          ask_price_1..10, ask_qty_1..10 (float or null)

One row is written per `book` channel message (snapshot or update) using
the collector's locally-maintained top-of-book state (v2 `update` messages
carry deltas only, not the full depth — see `OrderBookState`).

Retention: `--prune` deletes `data/ticks/<PAIR>/<YYYY-MM-DD>/` directories
whose date is older than 730 days (2y). Run it periodically (e.g. daily),
separately from the collector process.

Scheduled task (at-logon start; run once as CTO/Mike with approval — this
script never creates the task itself):

    schtasks /create /tn "TradeKit Tick Collector" /sc onlogon ^
        /tr "uv run --project C:\\Users\\admin\\dev\\tradekit python scripts\\collect_ticks.py" ^
        /rl limited

Run modes:
    uv run python scripts/collect_ticks.py            # run forever
    uv run python scripts/collect_ticks.py --smoke 60  # run 60s, print counts, exit 0
    uv run python scripts/collect_ticks.py --prune     # delete date dirs older than 2y
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

WS_URL = "wss://ws.kraken.com/v2"
REST_ASSET_PAIRS_URL = "https://api.kraken.com/0/public/AssetPairs"
DATA_DIR = Path("data/ticks")
BOOK_DEPTH = 10
FLUSH_INTERVAL_S = 60.0
FLUSH_ROW_LIMIT = 5000
RETENTION_DAYS = 730
HEARTBEAT_TIMEOUT_S = 15.0

GREENLIST_PAIRS: list[str] = [
    "ETH/USD",
    "SOL/USD",
    "LINK/USD",
    "NEAR/USD",
    "EIGEN/USD",
    "RENDER/USD",
    "PAXG/USD",
    "TAO/USD",
    "XRP/USD",
    "AVAX/USD",
    "AKT/USD",
]


# --------------------------------------------------------------------------
# Pure logic: message parsing, book state, file paths, prune, backoff.
# No network, no optional deps — exercised directly by unit tests.
# --------------------------------------------------------------------------


def parse_trade_rows(msg: dict[str, Any]) -> list[dict[str, Any]]:
    """Kraken v2 `trade` channel message -> row dicts (one per trade)."""
    if msg.get("channel") != "trade":
        return []
    rows = []
    for item in msg.get("data", []):
        rows.append(
            {
                "ts": item["timestamp"],
                "price": item["price"],
                "qty": item["qty"],
                "side": item["side"],
                "ord_type": item["ord_type"],
            }
        )
    return rows


class OrderBookState:
    """Local top-of-book state for one pair. Kraken v2 `book` `update`
    messages carry only changed levels, not the full depth, so the
    collector must replay snapshot + deltas to know the current top-N
    (qty <= 0 removes a level)."""

    def __init__(self) -> None:
        self._bids: dict[float, float] = {}
        self._asks: dict[float, float] = {}

    def apply_snapshot(self, data: dict[str, Any]) -> None:
        self._bids = {lvl["price"]: lvl["qty"] for lvl in data.get("bids", [])}
        self._asks = {lvl["price"]: lvl["qty"] for lvl in data.get("asks", [])}

    def apply_update(self, data: dict[str, Any]) -> None:
        for lvl in data.get("bids", []):
            self._apply_level(self._bids, lvl)
        for lvl in data.get("asks", []):
            self._apply_level(self._asks, lvl)

    @staticmethod
    def _apply_level(book_side: dict[float, float], lvl: dict[str, float]) -> None:
        price, qty = lvl["price"], lvl["qty"]
        if qty <= 0:
            book_side.pop(price, None)
        else:
            book_side[price] = qty

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


def _pair_dirname(pair: str) -> str:
    return pair.replace("/", "_")


def trade_file_path(base_dir: Path, pair: str, ts: datetime) -> Path:
    return base_dir / _pair_dirname(pair) / ts.strftime("%Y-%m-%d") / f"trades-{ts:%H}.parquet"


def book_file_path(base_dir: Path, pair: str, ts: datetime) -> Path:
    return base_dir / _pair_dirname(pair) / ts.strftime("%Y-%m-%d") / f"book-{ts:%H}.parquet"


def prune_cutoff_date(now: datetime, retention_days: int = RETENTION_DAYS) -> Any:
    from datetime import timedelta

    return (now - timedelta(days=retention_days)).date()


def prune_targets(
    base_dir: Path, now: datetime, retention_days: int = RETENTION_DAYS
) -> list[Path]:
    """Date directories (`<PAIR>/<YYYY-MM-DD>/`) older than the retention
    window. Non-date-named directories are left alone."""
    cutoff = prune_cutoff_date(now, retention_days)
    targets: list[Path] = []
    if not base_dir.exists():
        return targets
    for pair_dir in base_dir.iterdir():
        if not pair_dir.is_dir():
            continue
        for date_dir in pair_dir.iterdir():
            if not date_dir.is_dir():
                continue
            try:
                dir_date = datetime.strptime(date_dir.name, "%Y-%m-%d").date()
            except ValueError:
                continue
            if dir_date < cutoff:
                targets.append(date_dir)
    return targets


def backoff_delay(attempt: int, base: float = 1.0, cap: float = 60.0) -> float:
    """Exponential backoff (base * 2**attempt), capped at `cap` seconds."""
    return min(base * (2.0**attempt), cap)


# --------------------------------------------------------------------------
# REST verification (httpx — core dep, no guard needed).
# --------------------------------------------------------------------------


def verify_pairs(pairs: Iterable[str], timeout: float = 15.0) -> dict[str, bool]:
    """Check each pair against Kraken's public AssetPairs endpoint by
    `wsname`. Never raises on an unknown pair (e.g. AKT may be unlisted) —
    callers log + skip."""
    result = dict.fromkeys(pairs, False)
    try:
        resp = httpx.get(REST_ASSET_PAIRS_URL, timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        print(f"WARN: AssetPairs verification failed ({exc!r}); assuming all pairs unknown")
        return result
    if body.get("error"):
        print(f"WARN: AssetPairs returned error {body['error']}; assuming all pairs unknown")
        return result
    live_wsnames = {info.get("wsname") for info in body.get("result", {}).values()}
    for pair in pairs:
        result[pair] = pair in live_wsnames
    return result


# --------------------------------------------------------------------------
# Parquet sink + WS collector (optional deps — imported lazily, AC-10 guard).
# --------------------------------------------------------------------------


@dataclass
class _Buffer:
    rows: list[dict[str, Any]] = field(default_factory=list)
    last_flush: float = 0.0


class ParquetSink:
    """Buffers rows per (pair, kind) and flushes to hourly Parquet files
    every FLUSH_INTERVAL_S or FLUSH_ROW_LIMIT rows, whichever first."""

    def __init__(self, base_dir: Path = DATA_DIR) -> None:
        try:
            import pyarrow  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "ParquetSink requires the optional collector dependency group — "
                "run `uv sync --group collector`"
            ) from exc
        self.base_dir = base_dir
        self._buffers: dict[tuple[str, str], _Buffer] = {}

    def add(self, pair: str, kind: str, row: dict[str, Any], ts: datetime) -> None:
        key = (pair, kind)
        buf = self._buffers.setdefault(key, _Buffer())
        buf.rows.append(row)
        if len(buf.rows) >= FLUSH_ROW_LIMIT:
            self.flush(pair, kind, ts)

    def flush(self, pair: str, kind: str, ts: datetime) -> int:
        import pyarrow as pa
        import pyarrow.parquet as pq

        buf = self._buffers.get((pair, kind))
        if not buf or not buf.rows:
            return 0
        path = trade_file_path(self.base_dir, pair, ts) if kind == "trades" else book_file_path(
            self.base_dir, pair, ts
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pylist(buf.rows)
        if path.exists():
            existing = pq.read_table(path)
            table = pa.concat_tables([existing, table], promote_options="default")
        pq.write_table(table, path)
        n = len(buf.rows)
        buf.rows.clear()
        return n

    def flush_all(self, ts: datetime) -> None:
        for pair, kind in list(self._buffers.keys()):
            self.flush(pair, kind, ts)


async def run_collector(
    pairs: list[str], base_dir: Path = DATA_DIR, duration_s: float | None = None
) -> dict[str, dict[str, int]]:
    """Connect, subscribe, and consume `trade`/`book` messages until
    `duration_s` elapses (None = forever). Returns per-pair counts
    ({"trades": n, "book_updates": n})."""
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
            print(f"WARN: pair {p} not found via AssetPairs — skipping")

    sink = ParquetSink(base_dir)
    counts: dict[str, dict[str, int]] = {p: {"trades": 0, "book_updates": 0} for p in active}
    books: dict[str, OrderBookState] = {p: OrderBookState() for p in active}
    loop = asyncio.get_event_loop()
    deadline = (loop.time() + duration_s) if duration_s is not None else None
    attempt = 0

    while deadline is None or loop.time() < deadline:
        try:
            async with websockets.connect(WS_URL, open_timeout=10) as ws:
                attempt = 0
                await ws.send(
                    json.dumps(
                        {"method": "subscribe", "params": {"channel": "trade", "symbol": active}}
                    )
                )
                await ws.send(
                    json.dumps(
                        {
                            "method": "subscribe",
                            "params": {"channel": "book", "symbol": active, "depth": BOOK_DEPTH},
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
                    now = datetime.now(UTC)
                    channel = msg.get("channel")
                    if channel == "trade":
                        for item in msg.get("data", []):
                            pair = item["symbol"]
                            if pair not in books:
                                continue
                            row = {
                                "ts": item["timestamp"],
                                "price": item["price"],
                                "qty": item["qty"],
                                "side": item["side"],
                                "ord_type": item["ord_type"],
                            }
                            sink.add(pair, "trades", row, now)
                            counts[pair]["trades"] += 1
                    elif channel == "book":
                        for item in msg.get("data", []):
                            pair = item["symbol"]
                            if pair not in books:
                                continue
                            book = books[pair]
                            if msg.get("type") == "snapshot":
                                book.apply_snapshot(item)
                            else:
                                book.apply_update(item)
                            row = book.top_row(ts=now.isoformat(), depth=BOOK_DEPTH)
                            sink.add(pair, "book", row, now)
                            counts[pair]["book_updates"] += 1
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

    sink.flush_all(datetime.now(UTC))
    return counts


def prune(base_dir: Path = DATA_DIR) -> None:
    now = datetime.now(UTC)
    for target in prune_targets(base_dir, now):
        import shutil

        print(f"pruning {target}")
        shutil.rmtree(target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", type=float, default=None, help="run N seconds then exit 0")
    parser.add_argument("--prune", action="store_true", help="delete date dirs older than 2y")
    args = parser.parse_args()

    if args.prune:
        prune()
        return

    duration = args.smoke
    counts = asyncio.run(run_collector(GREENLIST_PAIRS, duration_s=duration))
    for pair, c in counts.items():
        print(f"{pair}: trades={c['trades']} book_updates={c['book_updates']}")
    sys.exit(0)


if __name__ == "__main__":
    main()
