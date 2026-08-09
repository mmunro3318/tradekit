"""Trade collector for Binance.US — the missing half of the books.

We already archive Binance.US L20 books (collect_books_binance.py) but not
the trades that moved them. This fills that gap.

VENUE NOTE (inherited from collect_books_binance.py, still true 2026-08-08):
api.binance.com is geo-blocked from this machine ("Service unavailable from
a restricted location", HTTP 451) — this collector targets binance.US
(api.binance.us / stream.binance.us) instead. Symbols are `<BASE><QUOTE>`,
e.g. "BTC/USD" -> "BTCUSD".

THIS IS A REST POLLER, NOT A WEBSOCKET COLLECTOR — established the hard way
2026-08-08, recorded here so it is never rediscovered:

    1. First cut used run_ws_collector against `<symbol>@trade` /
       `<symbol>@aggTrade` (dynamic SUBSCRIBE on wss://stream.binance.us:9443/ws).
       Subscribe ack'd cleanly ({"result":null,"id":1}) on both forms
       (dynamic /ws SUBSCRIBE and the URL-embedded /stream?streams=... form)
       and then went totally silent — a 300s smoke run over 25 pairs wrote
       ZERO rows and produced no files.
    2. Control test to rule out "bad adapter, not bad venue": one socket,
       four streams, 240s —
           btcusd@depth20@1000ms -> 103 frames
           btcusd@trade          -> 0
           btcusd@aggTrade       -> 0
           adausd@trade          -> 0
       Depth streamed fine on the SAME connection, ruling out the URL form
       and the socket. The public WS trade channels on binance.us simply do
       not deliver — a venue defect (or entitlement gate), not a parsing bug.
    3. The trades DO exist: GET /api/v3/trades returns them, and
       GET /api/v3/ticker/24hr shows BTCUSD at ~2,669 trades/day with a
       last-print only minutes old.

So: poll REST instead. Cadence, cursor and dedup pattern are modeled on
scripts/collect_equities_alpaca.py (also a cursor-based REST poller writing
through collector_core.PartitionedParquetSink) — reused rather than invented.

ENDPOINT CHOICE — GET /api/v3/aggTrades, not /api/v3/trades. `/trades`
(recent trades list) takes no `fromId`/time-range params at all — it can
only hand back "the most recent N", which cannot be turned into a gapless
cursor. `/historicalTrades` has `fromId` but requires an API key (a new
credential we do not have or need for market data). `/aggTrades` has
`fromId`, needs NO auth (verified: 200 with no key), and is what makes an
id-based cursor possible at all — that is the deciding factor, not size.

CONSEQUENCE FOR trade_id: rows now carry OKX/Coinbase-incompatible
semantics for that one field — `trade_id` here is the aggregate-trade id
(`a`), not a raw per-fill id (`f`..`l`), because aggTrades is the only
unauthenticated cursorable endpoint. Verified live 2026-08-08 that merges do
occasionally happen even on this low-volume venue (one captured row: `"a":
20828515,"f":89669105,"l":89669106` — two fills folded into one aggregate),
so this is a real, not theoretical, schema note.

DEDUP / CURSOR. Each pass reads the highest `trade_id` (aggTradeId) already
on disk for a symbol (`last_stored_id`, mirrors Alpaca's `last_stored_ts`)
and requests `fromId=<last+1>`. Binance's `fromId` is INCLUSIVE of the id
given (verified live: requesting `fromId=20828514` returned 20828514 first),
so `last_seen_id + 1` makes consecutive polls non-overlapping BY
CONSTRUCTION rather than by post-hoc filtering — there is no window in
which the same id can land twice. Verified directly: two back-to-back
overlapping polls for the same symbol produced zero duplicate trade_ids
between them (see smoke output). Cold start (no rows on disk yet) does NOT
backfill full history — it seeds the cursor from the single most recent
trade and collects forward from there; scripts/backfill_ticks.py is the
place for historical backfill, not this collector.

CADENCE / WEIGHT. Venue is glacial: BTCUSD ~2,669 trades/day, ETHUSD ~537,
XRPUSD ~320 (probed 2026-08-08 via /ticker/24hr `count`). One poll/60s/symbol
with `limit=1000` therefore has enormous headroom — even BTCUSD's ~1.85
trades/min is nowhere near exhausting a single page. 25 symbols x 1
request/poll x weight-1 aggTrades calls is trivial against Binance.US's
per-minute weight budget; a small inter-symbol sleep is kept anyway so a
25-symbol pass doesn't look like a burst.

side mapping: Binance gives `m` (isBuyerMaker), not a side string. m=true
means the buyer posted the passive order, so the TAKER (the side that
crossed the spread) was the seller -> side="sell". m=false -> taker was the
buyer -> side="buy".

Parquet schema (`trades-<HH>.parquet`), matching the other trade venues:

    ts (str ISO8601 UTC), price (float), qty (float), side ("buy"/"sell"),
    trade_id (str)  # aggTradeId — see CONSEQUENCE note above

Run:
    uv run python scripts/collect_trades_binance_us.py --once
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collect_ticks import GREENLIST_PAIRS
from collector_core import (
    PartitionedParquetSink,
    iter_symbol_dirs,
    resolve_data_root,
    symbol_dirname,
)

VENUE = "binance_us"
REST_BASE = "https://api.binance.us/api/v3"
REST_EXCHANGE_INFO_URL = f"{REST_BASE}/exchangeInfo"
REST_AGG_TRADES_URL = f"{REST_BASE}/aggTrades"

POLL_INTERVAL_S = 60.0
PAGE_LIMIT = 1000
# Courtesy delay between symbols within one pass — see CADENCE / WEIGHT above;
# not needed to stay under the rate limit, kept so a 25-symbol pass doesn't
# look like a burst.
INTER_SYMBOL_SLEEP_S = 0.1


def resolve_trades_dir(venue: str = VENUE) -> Path:
    return resolve_data_root() / "trades" / venue


def pair_to_symbol(pair: str) -> str:
    """Greenlist pair -> Binance.US symbol: "ETH/USD" -> "ETHUSD"."""
    return pair.replace("/", "")


def verify_pairs(pairs: Iterable[str], timeout: float = 15.0) -> dict[str, bool]:
    """Which pairs Binance.US lists as TRADING. Never raises — callers skip."""
    result = dict.fromkeys(pairs, False)
    try:
        resp = httpx.get(REST_EXCHANGE_INFO_URL, timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:
        print(f"WARN: exchangeInfo verification failed ({exc!r}); assuming all pairs unknown")
        return result
    live = {s["symbol"] for s in body.get("symbols", []) if s.get("status") == "TRADING"}
    for pair in pairs:
        result[pair] = pair_to_symbol(pair) in live
    return result


_SIDE_OF_BUYER_MAKER = {True: "sell", False: "buy"}


def trade_row(item: dict[str, Any]) -> dict[str, Any]:
    ts = datetime.fromtimestamp(item["T"] / 1000, tz=UTC).isoformat()
    return {
        "ts": ts,
        "price": float(item["p"]),
        "qty": float(item["q"]),
        "side": _SIDE_OF_BUYER_MAKER[bool(item.get("m"))],
        "trade_id": str(item["a"]),
    }


def last_stored_id(base_dir: Path, symbol: str, stream: str = "trades") -> int | None:
    """Highest `trade_id` already on disk for `symbol`, or None.

    Mirrors collect_equities_alpaca.last_stored_ts: only the newest
    day-directory is read, since the cursor only ever moves forward.
    """
    import pyarrow.parquet as pq

    want = symbol_dirname(symbol)
    days = [d for d in iter_symbol_dirs(base_dir) if d.parent.name == want]
    if not days:
        return None
    newest: int | None = None
    for day in sorted(days, reverse=True)[:1]:
        for f in day.iterdir():
            if not f.name.startswith(f"{stream}-") or f.suffix != ".parquet":
                continue
            try:
                col = pq.read_table(f, columns=["trade_id"]).column("trade_id").to_pylist()
            except Exception:
                continue
            for raw in col:
                if not raw:
                    continue
                tid = int(raw)
                if newest is None or tid > newest:
                    newest = tid
    return newest


def fetch_agg_trades(
    client: httpx.Client, symbol: str, from_id: int | None
) -> list[dict[str, Any]]:
    """Every aggTrade for `symbol` from `from_id` (inclusive) forward, paged
    to exhaustion. `from_id=None` (cold start) fetches only the single most
    recent trade to seed a cursor — see docstring's DEDUP / CURSOR note."""
    if from_id is None:
        resp = client.get(REST_AGG_TRADES_URL, params={"symbol": symbol, "limit": 1})
        resp.raise_for_status()
        return resp.json()

    rows: list[dict[str, Any]] = []
    cursor = from_id
    while True:
        resp = client.get(
            REST_AGG_TRADES_URL,
            params={"symbol": symbol, "fromId": cursor, "limit": PAGE_LIMIT},
        )
        resp.raise_for_status()
        page = resp.json()
        if not page:
            return rows
        rows.extend(page)
        if len(page) < PAGE_LIMIT:
            return rows
        cursor = page[-1]["a"] + 1
        time.sleep(0.12)


def run_once(pairs: list[str], base_dir: Path, sink: PartitionedParquetSink) -> dict[str, int]:
    """One incremental pass over every pair. Returns rows written per symbol.

    `sink` MUST be created once and reused across every call for the life of
    the process (see main()), never re-created per pass: PartitionedParquetSink
    numbers part files from an in-memory counter starting at 0 per instance,
    with no on-disk check — a fresh sink's first flush for a (symbol, stream)
    already active this hour silently overwrites the previous pass's
    `part-0000.parquet` instead of continuing at `part-0001`. Caught live in
    smoke testing 2026-08-08 (a per-pass sink dropped an already-stored row
    for ETHUSDT). A process restart mid-hour can still collide the same way
    — a pre-existing limitation shared with collect_equities_alpaca.py's
    poller, out of scope to fix here since it isn't collector_core's to
    change and the existing poller carries the same risk.
    """
    live = verify_pairs(pairs)
    active = [p for p in pairs if live[p]]
    for p in pairs:
        if not live[p]:
            print(f"WARN: pair {p} not TRADING on Binance.US — skipping")

    written: dict[str, int] = {}
    now = datetime.now(UTC)

    with httpx.Client(timeout=30) as client:
        for pair in active:
            symbol = pair_to_symbol(pair)
            cursor = last_stored_id(base_dir, symbol)
            from_id = None if cursor is None else cursor + 1
            page = fetch_agg_trades(client, symbol, from_id)
            for item in page:
                ts = datetime.fromtimestamp(item["T"] / 1000, tz=UTC)
                sink.add(symbol, "trades", trade_row(item), ts)
            written[symbol] = len(page)
            sink.flush_all(now, force=True)
            time.sleep(INTER_SYMBOL_SLEEP_S)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="single pass then exit")
    parser.add_argument(
        "--smoke", type=float, default=None, help="poll repeatedly for N seconds then exit 0"
    )
    args = parser.parse_args()

    base = resolve_trades_dir()
    sink = PartitionedParquetSink(base)  # one instance for the process lifetime — see run_once()
    deadline = time.monotonic() + args.smoke if args.smoke is not None else None
    while True:
        counts = run_once(GREENLIST_PAIRS, base, sink)
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        total = sum(counts.values())
        print(f"{stamp} rows={total} " + " ".join(f"{k}={v}" for k, v in counts.items() if v))
        if args.once or deadline is None or time.monotonic() >= deadline:
            break
        time.sleep(min(POLL_INTERVAL_S, max(0.0, deadline - time.monotonic())))
    sys.exit(0)


if __name__ == "__main__":
    main()
