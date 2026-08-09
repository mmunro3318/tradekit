"""Order-book collector for OKX — a NEW venue, added because it is the only
deep book we can reach live from this machine (probed 2026-08-08:
api.binance.com is 451-geo-blocked, Bybit is 403; OKX's
https://www.okx.com/api/v5/public/time returns 200).

WS: wss://ws.okx.com:8443/ws/v5/public (no auth for the channel used here).
Instruments: https://www.okx.com/api/v5/public/instruments?instType=SPOT,
instId format "BASE-QUOTE", filtered to state == "live".

CHANNEL CHOICE — `books`, not `books5`. OKX offers four public-ish depth
channels; all four were probed live on BTC-USD 2026-08-08:

  - `books-l2-tbt` : rejected unauthenticated — {"event":"error",
    "msg":"Please log in","code":"60011"}. VIP/login-gated, unusable here.
  - `bbo-tbt`      : works unauthenticated, but is top-1-of-book only
    (one bid level, one ask level) — nowhere near the 20 we need.
  - `books5`       : works unauthenticated, snapshot-only, exactly 5 levels
    per side, no checksum.
  - `books`        : works unauthenticated, 400-level incremental
    (snapshot then delta updates keyed by price, qty "0" removes a level).

We need top-20 depth to match the other venues (Coinbase, Binance.US), and
`books5` only carries 5. `books` gets us real top-20 for free by replaying
snapshot+deltas locally — the exact OrderBookState pattern this repo already
uses for Coinbase level2 and Kraken v2 book (collect_books_coinbase.py,
collect_ticks.py), so it is not new complexity, just the established
approach applied to a third venue. We therefore replay `books` rather than
settle for `books5`'s 5 levels.

CHECKSUM CAVEAT (found during verification, not assumed): OKX's `books`
payload carries a `checksum` field documented as a CRC32 over the top-25
interleaved bid/ask levels. Verified against 30 live frames on BTC-USD
2026-08-08 using OKX's own documented algorithm (CRC32 of
"bidPx:bidSz:askPx:askSz:..." for up to 25 levels per side) — EVERY frame on
this unauthenticated public connection carried `"checksum":0`, not a real
CRC32. Checksum-based desync detection is therefore NOT implemented; a
locally-replayed book state that silently drifts from the venue would not be
caught. Mitigation: the existing reconnect-on-error / heartbeat-timeout path
in collector_core forces a fresh snapshot on any transport hiccup, and this
collector trusts the delta stream the same way collect_books_coinbase.py
already does (which also has no checksum). Flagged here rather than quietly
built without it.

Frame shape (real captured sample, 2026-08-08, BTC-USD):

    snapshot: {"arg":{"channel":"books","instId":"BTC-USD"},"action":"snapshot",
      "data":[{"asks":[["64981.2","0.02154857","0","1"], ...],
               "bids":[["64981.1","0.0314486","0","2"], ...],
               "ts":"1786182438309","checksum":0,"seqId":8693644364}]}
    update:   {"arg":{"channel":"books","instId":"BTC-USD"},"action":"update",
      "data":[{"asks":[],"bids":[["64835.8","0.00459528","0","1"],
               ["64010","0","0","0"]],"ts":"1786182438509","checksum":0,
               "seqId":8693644373,"prevSeqId":8693644364}]}

Each level is [price, qty, deprecated "0", order_count] (strings); qty "0"
removes that price from the side.

SUBSCRIPTION CAP: none found. Probed 2026-08-08 by subscribing increasing
counts of (channel, instId) pairs on one connection — up to 500 distinct
live instIds on `books` alone, then up to 1200 total by cycling
books/books5/trades/bbo-tbt across instIds to exceed the ~1336 available
live SPOT instruments — every attempt ack'd with zero rejections. OKX's docs
describe no public-channel subscription-count cap (unlike Coinbase's hard
30-stream level2 limit, which we DID hit empirically). Our actual need is
~37 pairs x 1 channel = 37 subscriptions, far under the tested-safe range;
MAX_STREAMS_PER_SESSION is still set well below what was tested, as a
margin, not because a limit was observed.

Book rows are throttled to 1/sec via collector_core's default
`throttled_streams={"book"}` — deltas can arrive far faster than that.

Parquet schema (`book-<HH>.parquet`), matching the other book venues:

    ts (str, ISO8601 UTC), bid_price_1..20, bid_qty_1..20,
    ask_price_1..20, ask_qty_1..20 (float or null)

Run:
    uv run python scripts/collect_books_okx.py --smoke 60
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

VENUE = "okx"
WS_URL = "wss://ws.okx.com:8443/ws/v5/public"
REST_INSTRUMENTS_URL = "https://www.okx.com/api/v5/public/instruments"
BOOK_DEPTH = 20

# See docstring: no rejection observed up to 1200 subscriptions on one
# connection; our real need is ~37. Kept well under the tested-safe range.
MAX_STREAMS_PER_SESSION = 100


def resolve_books_dir(venue: str = VENUE) -> Path:
    return resolve_data_root() / "books" / venue


def pair_to_inst(pair: str) -> str:
    """Greenlist pair -> OKX instId: "ETH/USD" -> "ETH-USD"."""
    return pair.replace("/", "-")


def verify_pairs(pairs: Iterable[str], timeout: float = 15.0) -> dict[str, bool]:
    """Which pairs OKX lists as live SPOT instruments. Never raises."""
    result = dict.fromkeys(pairs, False)
    try:
        resp = httpx.get(REST_INSTRUMENTS_URL, params={"instType": "SPOT"}, timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:
        print(f"WARN: instruments verification failed ({exc!r}); assuming all pairs unknown")
        return result
    live = {d["instId"] for d in body.get("data", []) if d.get("state") == "live"}
    for pair in pairs:
        result[pair] = pair_to_inst(pair) in live
    return result


def subscribe(symbols: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "op": "subscribe",
            "args": [{"channel": "books", "instId": pair_to_inst(s)} for s in symbols],
        }
    ]


def error_of(msg: dict[str, Any]) -> str | None:
    return msg.get("msg") if msg.get("event") == "error" else None


class _OrderBookState:
    """Local top-of-book state for one instrument, replayed from OKX
    `books` snapshot + update deltas (qty "0" removes a level). See module
    docstring: no venue checksum is available to validate this against."""

    def __init__(self) -> None:
        self._bids: dict[float, float] = {}
        self._asks: dict[float, float] = {}

    def apply(self, action: str, data: dict[str, Any]) -> None:
        if action == "snapshot":
            self._bids.clear()
            self._asks.clear()
        for lvl in data.get("bids", []):
            self._apply_level(self._bids, lvl)
        for lvl in data.get("asks", []):
            self._apply_level(self._asks, lvl)

    @staticmethod
    def _apply_level(side: dict[float, float], lvl: list[str]) -> None:
        price, qty = float(lvl[0]), float(lvl[1])
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


# Book state is per-instrument and must persist across messages on the same
# connection (the incremental replay this venue requires), so `parse` is a
# closure over mutable state rather than the pure function VenueSpec.parse
# is typically handed — same trick collect_books_coinbase.py's OrderBookState
# uses, just adapted to VenueSpec's (frame, now) -> rows signature. A fresh
# `snapshot` action (sent on every (re)subscribe) resets the affected book,
# so a reconnect self-heals instead of replaying deltas onto stale state.
_books: dict[str, _OrderBookState] = {}


def parse(msg: dict[str, Any], now: datetime) -> list[ParsedRow]:
    arg = msg.get("arg", {})
    if arg.get("channel") != "books":
        return []
    inst = arg.get("instId")
    action = msg.get("action")
    if not inst or action not in ("snapshot", "update"):
        return []
    book = _books.setdefault(inst, _OrderBookState())
    out: list[ParsedRow] = []
    for data in msg.get("data", []):
        book.apply(action, data)
        row = book.top_row(ts=now.isoformat(), depth=BOOK_DEPTH)
        out.append((inst.replace("-", "/"), "book", row))
    return out


SPEC = VenueSpec(
    name=VENUE,
    ws_url=WS_URL,
    subscribe=subscribe,
    parse=parse,
    error_of=error_of,
    max_streams_per_session=MAX_STREAMS_PER_SESSION,
    # default throttled_streams={"book"} already matches our stream name
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
        run_ws_collector(SPEC, active, resolve_books_dir(), duration_s=args.smoke)
    )
    for pair, n in counts.items():
        print(f"{pair}: book_rows={n}")
    sys.exit(0)


if __name__ == "__main__":
    main()
