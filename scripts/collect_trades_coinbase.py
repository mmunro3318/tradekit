"""Trade collector for Coinbase Advanced Trade — the missing half of the books.

We already archive Coinbase level2 books (collect_books_coinbase.py) but not
the trades that moved them, which makes the book data much harder to use: you
can see the queue change without seeing what consumed it. This fills that gap.

The `market_trades` channel is PUBLIC (probed 2026-08-08: subscribes and
streams with no API key, no JWT, no account). Coinbase API keys are therefore
NOT required or used here.

Frame shape (real sample, 2026-08-08):

    {"channel":"market_trades","events":[{"type":"update","trades":[
      {"product_id":"BTC-USD","trade_id":"1068307673","price":"64975.28",
       "size":"0.01149823","time":"2026-08-08T09:29:38.161179Z","side":"BUY"}]}]}

Parquet schema (`trades-<HH>.parquet`), matching collect_ticks' trade rows so
the two venues concatenate:

    ts (str ISO8601 UTC), price (float), qty (float), side ("buy"/"sell"),
    trade_id (str)

Run:
    uv run python scripts/collect_trades_coinbase.py --smoke 60
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collect_ticks import GREENLIST_PAIRS
from collector_core import (
    ParsedRow,
    VenueSpec,
    resolve_data_root,
    run_ws_collector,
)

VENUE = "coinbase"
WS_URL = "wss://advanced-trade-ws.coinbase.com"
REST_PRODUCTS_URL = "https://api.exchange.coinbase.com/products"

# The market_trades channel has no documented per-session cap and trade frames
# are tiny (unlike level2 snapshots, which cap at 30 products/session). Kept
# conservative anyway so one rejected session cannot take the venue down.
MAX_STREAMS_PER_SESSION = 100


def resolve_trades_dir(venue: str = VENUE) -> Path:
    return resolve_data_root() / "trades" / venue


def pair_to_product(pair: str) -> str:
    return pair.replace("/", "-")


def verify_pairs(pairs: Iterable[str], timeout: float = 15.0) -> dict[str, bool]:
    """Which pairs Coinbase lists as online. Never raises — callers skip."""
    result = dict.fromkeys(pairs, False)
    try:
        resp = httpx.get(REST_PRODUCTS_URL, timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:
        print(f"WARN: products verification failed ({exc!r}); assuming all unknown")
        return result
    live = {p.get("id") for p in body if p.get("status") == "online"}
    for pair in pairs:
        result[pair] = pair_to_product(pair) in live
    return result


def subscribe(symbols: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "type": "subscribe",
            "channel": "market_trades",
            "product_ids": [pair_to_product(s) for s in symbols],
        }
    ]


def error_of(msg: dict[str, Any]) -> str | None:
    return msg.get("message") if msg.get("type") == "error" else None


def parse(msg: dict[str, Any], now: datetime) -> list[ParsedRow]:
    """Extract trade rows. Ignores the `snapshot` event type — it replays
    recent history on connect and would duplicate rows across reconnects."""
    if msg.get("channel") != "market_trades":
        return []
    out: list[ParsedRow] = []
    for event in msg.get("events", []):
        if event.get("type") != "update":
            continue
        for t in event.get("trades", []):
            product = t.get("product_id")
            if not product:
                continue
            out.append(
                (
                    product.replace("-", "/"),
                    "trades",
                    {
                        "ts": t.get("time"),
                        "price": float(t["price"]),
                        "qty": float(t["size"]),
                        "side": str(t.get("side", "")).lower(),
                        "trade_id": str(t.get("trade_id", "")),
                    },
                )
            )
    return out


SPEC = VenueSpec(
    name=VENUE,
    ws_url=WS_URL,
    subscribe=subscribe,
    parse=parse,
    error_of=error_of,
    max_streams_per_session=MAX_STREAMS_PER_SESSION,
    throttled_streams=frozenset(),  # never coalesce trades
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", type=float, default=None, help="run N seconds then exit 0")
    args = parser.parse_args()

    live = verify_pairs(GREENLIST_PAIRS)
    active = [p for p in GREENLIST_PAIRS if live[p]]
    for p in GREENLIST_PAIRS:
        if not live[p]:
            print(f"WARN: pair {p} not listed on Coinbase — skipping")

    counts = asyncio.run(
        run_ws_collector(SPEC, active, resolve_trades_dir(), duration_s=args.smoke)
    )
    for pair, n in counts.items():
        print(f"{pair}: trades={n}")
    sys.exit(0)


if __name__ == "__main__":
    main()
