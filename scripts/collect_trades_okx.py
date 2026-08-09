"""Trade collector for OKX — the other half of collect_books_okx.py.

See collect_books_okx.py's module docstring for why OKX (the only new deep
venue reachable live from this machine) and how pairs are mapped/verified;
this file reuses the same instId mapping and REST verification shape.

The `trades` public channel needs no auth (probed 2026-08-08 alongside the
book channels). Frame shape (real captured sample, ETH-USD):

    {"arg":{"channel":"trades","instId":"ETH-USD"},
     "data":[{"instId":"ETH-USD","tradeId":"21746139","px":"1918.15",
              "sz":"0.4","side":"sell","ts":"1786182686418","count":"1",
              "source":"0","seqId":11335881725}]}

Unlike Binance, OKX gives `side` directly ("buy"/"sell") — no
buyer-is-maker inference needed. `ts` is an epoch-millisecond string.

Parquet schema (`trades-<HH>.parquet`), matching the other trade venues:

    ts (str ISO8601 UTC), price (float), qty (float), side ("buy"/"sell"),
    trade_id (str)

Subscription cap: see collect_books_okx.py — none found up to 1200
subscriptions on one connection (probed across books/books5/trades/bbo-tbt
together); our real need is ~37. MAX_STREAMS_PER_SESSION kept conservative.

Run:
    uv run python scripts/collect_trades_okx.py --smoke 60
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collect_books_okx import pair_to_inst, verify_pairs
from collect_ticks import GREENLIST_PAIRS
from collector_core import (
    ParsedRow,
    VenueSpec,
    resolve_data_root,
    run_ws_collector,
)

VENUE = "okx"
WS_URL = "wss://ws.okx.com:8443/ws/v5/public"

# See collect_books_okx.py docstring: no cap observed up to 1200
# subscriptions/connection; our real need is ~37. Kept conservative anyway.
MAX_STREAMS_PER_SESSION = 100


def resolve_trades_dir(venue: str = VENUE) -> Path:
    return resolve_data_root() / "trades" / venue


def subscribe(symbols: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "op": "subscribe",
            "args": [{"channel": "trades", "instId": pair_to_inst(s)} for s in symbols],
        }
    ]


def error_of(msg: dict[str, Any]) -> str | None:
    return msg.get("msg") if msg.get("event") == "error" else None


def parse(msg: dict[str, Any], now: datetime) -> list[ParsedRow]:
    arg = msg.get("arg", {})
    if arg.get("channel") != "trades":
        return []
    inst = arg.get("instId")
    if not inst:
        return []
    out: list[ParsedRow] = []
    for t in msg.get("data", []):
        ts_ms = t.get("ts")
        ts = (
            datetime.fromtimestamp(int(ts_ms) / 1000, tz=now.tzinfo).isoformat()
            if ts_ms
            else now.isoformat()
        )
        out.append(
            (
                inst.replace("-", "/"),
                "trades",
                {
                    "ts": ts,
                    "price": float(t["px"]),
                    "qty": float(t["sz"]),
                    "side": str(t.get("side", "")).lower(),
                    "trade_id": str(t.get("tradeId", "")),
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
            print(f"WARN: pair {p} not live on OKX — skipping")

    counts = asyncio.run(
        run_ws_collector(SPEC, active, resolve_trades_dir(), duration_s=args.smoke)
    )
    for pair, n in counts.items():
        print(f"{pair}: trades={n}")
    sys.exit(0)


if __name__ == "__main__":
    main()
