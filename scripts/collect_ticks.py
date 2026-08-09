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

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collector_core import stream_dir, symbol_dirname

WS_URL = "wss://ws.kraken.com/v2"
REST_ASSET_PAIRS_URL = "https://api.kraken.com/0/public/AssetPairs"

# Tick data prefers the external drive (Mike, 2026-07-26: C: is nearly full,
# 1.2G of ticks and growing) and falls back to the repo-local dir whenever
# D:\tradekit-data is absent (drive unplugged) so collection never stops.
_EXTERNAL_DATA_ROOT = Path("D:/tradekit-data")
_LOCAL_DATA_DIR = Path("data/ticks")


def resolve_data_dir(
    external_root: Path = _EXTERNAL_DATA_ROOT, local_dir: Path = _LOCAL_DATA_DIR
) -> Path:
    """`<external_root>/ticks` when the external root dir exists, else the
    repo-local fallback. Checked at process start, not per flush — a drive
    that vanishes mid-run surfaces as a loud write error, never a silent
    mid-stream relocation."""
    if external_root.is_dir():
        return external_root / "ticks"
    return local_dir


DATA_DIR = resolve_data_dir()
BOOK_DEPTH = 10
FLUSH_INTERVAL_S = 60.0
FLUSH_ROW_LIMIT = 5000
RETENTION_DAYS = 730
HEARTBEAT_TIMEOUT_S = 15.0

# Kraken WS v2 symbols (BTC, not the REST-side XBT — see `_ws_v2_symbol`).
# Grouped by research intent; each group can be cut without touching the others.
# The book collectors import this list and drop what their own venue doesn't
# list, so non-USD and Kraken-only pairs are safe to include here.

# L1 gas / settlement assets.
_PAIRS_L1: list[str] = [
    "BTC/USD",
    "ETH/USD",
    "SOL/USD",
    "XRP/USD",
    "AVAX/USD",
    "NEAR/USD",
    "ADA/USD",
    "SUI/USD",
    "BNB/USD",
    "ZEC/USD",
]

# Picks-and-shovels: compute, storage, oracles, DA, staking, L2 gas.
_PAIRS_INFRA: list[str] = [
    "LINK/USD",
    "TAO/USD",
    "AKT/USD",
    "RENDER/USD",
    "EIGEN/USD",
    "TIA/USD",
    "POL/USD",
    "FIL/USD",
]

# Research-pedigree L1s held for the long-horizon utility thesis.
_PAIRS_ACADEMIC: list[str] = [
    "ALGO/USD",
    "DOT/USD",
    "HBAR/USD",
]

# Cross-chain messaging / bridges.
_PAIRS_BRIDGE: list[str] = [
    "ZRO/USD",
    "W/USD",
]

# DEX / DeFi rails. CAKE is retained as a reference series only — its US tape
# is a fragment of real (Binance-global) CAKE volume, so treat it as a venue
# artifact, not a price. ACX was dropped: Risk Labs is converting the token to
# C-corp equity, so the series has a scheduled death.
_PAIRS_DEX: list[str] = [
    "AERO/USD",
    "CAKE/USD",
]

# RWA sleeve: two gold issuers (basis), tokenized treasuries, private credit.
_PAIRS_RWA: list[str] = [
    "PAXG/USD",
    "XAUT/USD",
    "ONDO/USD",
    "CFG/USD",
]

# Stablecoin peg monitoring — the depeg tape is the point, so thin issuers are
# deliberately included; a quiet book is itself the signal.
#
# Volumes below are true USD notional measured 2026-08-08 (base volume x price,
# with non-USD quotes converted through Kraken's own fiat pairs). Do NOT read
# a venue's raw 24h volume field as USD: OKX reports `volCcy24h` in the QUOTE
# currency, so USDT/TRY looks like "470M" when the USD notional is ~$9.9M.
_PAIRS_STABLE: list[str] = [
    "USDT/USD",  # $34.9M
    "USDC/USD",  # $16.0M
    "USDC/USDT",  # $9.2M — the reference stable-vs-stable leg
    "DAI/USD",  # $36k
    "PYUSD/USD",  # $253k
    "RLUSD/USD",  # $7.6k
    "USDG/USD",  # $202k
    "USDS/USD",  # thin on Kraken ($1.6k); ~$2.2M on Coinbase
    "EURC/USD",  # $136k
    "EURC/EUR",  # $70k
    "EURC/USDC",  # $33k
    # Non-USD-native issuers. Real and tradeable but genuinely tiny — carried
    # for peg-history coverage, not because anything can be traded on them.
    "TGBP/USD",  # $2.9k, 0.4bp
    "QCAD/USD",  # $1.4k
    "BRL1/USD",  # $28k, 220 trades
    "MXNB/USD",  # $114, 2 trades
    "EURQ/USD",  # $153, 6 trades
    "XSGD/USDC",  # Coinbase only
    "AUDD/USDC",  # Coinbase only
    "TGBP/USDC",  # Coinbase only
]

# Stablecoins quoted in fiat. This is where on-chain-vs-real-world FX drift
# shows up: USDC/EUR against EUR/USD is the same exposure priced two ways, and
# the emerging-market legs (TRY, BRL, AED) are where capital controls put a
# persistent premium on dollar access.
_PAIRS_STABLE_FX: list[str] = [
    "USDC/EUR",  # $13.0M, 15.5k trades — busiest of the whole sleeve
    "USDT/EUR",  # $4.4M
    "USDC/GBP",  # $4.0M
    "USDT/GBP",  # $1.3M
    "USDC/CAD",  # $1.0M
    "USDT/CAD",  # $172k
    "USDC/AUD",  # $496k
    "USDT/AUD",  # $574k
    "USDC/CHF",  # $130k
    "USDT/CHF",  # $246k
    "USDT/JPY",  # $4.3M but only 64 trades/day at 40bp — wide, treat with care
    # OKX-only legs. Kraken/Coinbase drop what they do not list, so these cost
    # nothing on the other venues.
    "USDT/TRY",  # $9.9M — the capital-controls instrument
    "USDT/BRL",  # $3.5M
    "USDT/AED",  # $697k
    "USDT/SGD",  # $240k
    "USDC/BRL",  # $59k
    "USDC/TRY",  # $28k
    "BRL1/BRL",  # $810k
    "AUDF/AUD",  # listed, ~zero volume — coverage only
]

# Fiat and cross-quote basis. Same asset quoted in several currencies lets the
# implied FX rate be recovered from crypto and compared against the venue's own
# fiat book. JPY is excluded — BTC/JPY trades ~70x/day, ETH/JPY ~4x.
_PAIRS_FX: list[str] = [
    "EUR/USD",
    "GBP/USD",
    "AUD/USD",
    "BTC/EUR",
    "ETH/EUR",
    "SOL/EUR",
    "BTC/GBP",
    "ETH/GBP",
    "BTC/CHF",
    "BTC/CAD",
    "BTC/AUD",
]

# Crypto-quoted ratios and stablecoin-quoted majors (CEX basis).
_PAIRS_CROSS: list[str] = [
    "ETH/BTC",
    "SOL/BTC",
    "XRP/BTC",
    "ADA/BTC",
    "SOL/ETH",
    "BTC/USDT",
    "BTC/USDC",
    "ETH/USDT",
    "ETH/USDC",
]

GREENLIST_PAIRS: list[str] = [
    *_PAIRS_L1,
    *_PAIRS_INFRA,
    *_PAIRS_ACADEMIC,
    *_PAIRS_BRIDGE,
    *_PAIRS_DEX,
    *_PAIRS_RWA,
    *_PAIRS_STABLE,
    *_PAIRS_STABLE_FX,
    *_PAIRS_FX,
    *_PAIRS_CROSS,
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


# Layout is owned by collector_core so this collector and the newer ones can
# never disagree about where a pair lives. `stream_dir` honours
# collector_core.PARTITION_BY_CLASS, so flipping that constant (after running
# migrate_layout.py) moves every collector at once. Delegating rather than
# duplicating is the whole point: a private copy here is exactly how the tree
# would end up half flat and half partitioned.
def _pair_dirname(pair: str) -> str:
    return symbol_dirname(pair)


def trade_file_path(base_dir: Path, pair: str, ts: datetime) -> Path:
    return stream_dir(base_dir, pair, ts) / f"trades-{ts:%H}.parquet"


def book_file_path(base_dir: Path, pair: str, ts: datetime) -> Path:
    return stream_dir(base_dir, pair, ts) / f"book-{ts:%H}.parquet"


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


# REST `wsname` still carries Kraken's legacy asset codes; WS v2 renamed them
# (probed 2026-08-07: subscribing to "XBT/USD" returns "Currency pair not
# supported", "BTC/USD" succeeds). Verification compares WS v2 symbols, so the
# REST side is translated — without this, every BTC/* pair verifies False and
# is silently dropped from the greenlist.
_WS_V2_ASSET_RENAMES = {"XBT": "BTC", "XDG": "DOGE"}


def _ws_v2_symbol(wsname: str | None) -> str | None:
    if not wsname or "/" not in wsname:
        return wsname
    base, _, quote = wsname.partition("/")
    return f"{_WS_V2_ASSET_RENAMES.get(base, base)}/{_WS_V2_ASSET_RENAMES.get(quote, quote)}"


def verify_pairs(pairs: Iterable[str], timeout: float = 15.0) -> dict[str, bool]:
    """Check each pair against Kraken's public AssetPairs endpoint, comparing
    WS v2 symbols (see `_ws_v2_symbol`). Never raises on an unknown pair (e.g.
    AKT may be unlisted) — callers log + skip."""
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
    live_wsnames = {_ws_v2_symbol(info.get("wsname")) for info in body.get("result", {}).values()}
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
    last_flush = loop.time()
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
                    # Time-based flush. Without it the only drain is the
                    # per-pair FLUSH_ROW_LIMIT, so a quiet pair holds its rows
                    # in RAM indefinitely — losing them if the process dies and
                    # mis-filing them into the flush hour's file when it finally
                    # crosses the threshold. Mirrors the book collectors.
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
