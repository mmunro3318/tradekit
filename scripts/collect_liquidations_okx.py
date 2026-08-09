"""Forced-liquidation collector for OKX — the only live public liquidation
feed reachable from this machine (Binance's `liquidationSnapshot` archive
stream was discontinued Oct 2024 and its live fstream is geo-blocked here;
Hyperliquid has no official liquidation feed). See collect_books_okx.py's
docstring for why OKX is the venue of record for this machine.

WS: wss://ws.okx.com:8443/ws/v5/public , channel `liquidation-orders`, no
auth. Probed live 2026-08-08:

    {"op":"subscribe","args":[
        {"channel":"liquidation-orders","instType":"SWAP"},
        {"channel":"liquidation-orders","instType":"MARGIN"},
        {"channel":"liquidation-orders","instType":"FUTURES"}]}

All three instTypes ack'd cleanly on one connection (no "Please log in" /
error frame the way `books-l2-tbt` does). `OPTION` also ack'd when probed but
is out of scope here — not requested, and OKX options liquidations are a
different risk profile than the linear/margin book this archive tracks.
INST_TYPES below is exactly the set that was verified live, not a guess.

FRAME SHAPE — this is an instType-WIDE subscription, not per-instrument: one
`{"channel":"liquidation-orders","instType":"SWAP"}` arg covers every SWAP
instrument OKX has. Real captured samples, 2026-08-08:

    {"arg":{"channel":"liquidation-orders","instType":"SWAP"},
     "data":[{"details":[{"bkLoss":"0","bkPx":"0.05167","ccy":"",
              "posSide":"long","side":"sell","sz":"508",
              "ts":"1786221914184"}],
              "instFamily":"LA-USDT","instId":"LA-USDT-SWAP",
              "instType":"SWAP","uly":"LA-USDT"}]}

`data[]` is per-instrument; each entry carries a `details[]` array of
individual liquidations. This collector flattens it — one output row per
`details` entry, keyed by the parent's `instId`.

Rate is sporadic: ~4 events in 120s across all SWAP instruments during the
verification window. Long silent stretches are normal, not a collector bug —
`--smoke` defaults to a window long enough to plausibly see one anyway.

SYMBOL ROUTING — the load-bearing decision in this file. `run_ws_collector`
drops any parsed row whose symbol isn't in the `symbols` list it was given,
because that list is what the book/trade collectors use to mean "the pairs I
subscribed to". Liquidations don't work that way: one instType-wide
subscribe delivers every instrument's liquidations regardless of what
`symbols` said, but the row-level filter would still silently discard
anything outside a hand-picked greenlist — and a liquidation tape filtered
to ~25 symbols defeats the point of a venue-wide feed. So `symbols` here is
NOT a subscription list (see `subscribe()` — it ignores its argument and
always subscribes all of INST_TYPES); it is populated at startup with every
live instId OKX reports for SWAP/MARGIN/FUTURES (`fetch_live_instruments`,
same REST endpoint and is-live filtering collect_books_okx.verify_pairs
uses, applied to a full-catalog fetch instead of a greenlist membership
check), purely so the row filter has something to match against and nothing
gets dropped. This is additive plumbing around `run_ws_collector`'s existing
contract, not a modification of it — flagging per the dispatch instructions
in case a cleaner mechanism is wanted later.

Parquet schema (`liquidations-<HH>.parquet`), one row per `details` entry:

    ts (str ISO8601 UTC), inst_id (str), inst_family (str), inst_type (str),
    pos_side ("long"/"short"), side ("buy"/"sell"), size (float),
    bk_px (float, bankruptcy price), bk_loss (float), ccy (str)

Never throttled (`throttled_streams=frozenset()`) — liquidations are already
sparse; coalescing would silently drop real events.

Run:
    uv run python scripts/collect_liquidations_okx.py --smoke
    uv run python scripts/collect_liquidations_okx.py --smoke 240
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collect_books_okx import REST_INSTRUMENTS_URL
from collector_core import (
    ParsedRow,
    VenueSpec,
    resolve_data_root,
    run_ws_collector,
)

VENUE = "okx"
WS_URL = "wss://ws.okx.com:8443/ws/v5/public"

# Verified live 2026-08-08 (see module docstring) — every instType actually
# subscribed and confirmed acceptable, not the full set OKX might support.
INST_TYPES: tuple[str, ...] = ("SWAP", "MARGIN", "FUTURES")

# Sporadic feed (~4 events/120s across all swaps): a short smoke window is
# likely to see nothing and prove nothing. Default long enough to plausibly
# catch a real event without the caller having to know that up front.
DEFAULT_SMOKE_S = 240.0


def resolve_liquidations_dir(venue: str = VENUE) -> Path:
    return resolve_data_root() / "liquidations" / venue


def fetch_live_instruments(inst_type: str, timeout: float = 15.0) -> list[str]:
    """Every live instId OKX currently lists for `inst_type`. Never raises.

    Same endpoint and is-live filtering as collect_books_okx.verify_pairs,
    applied to the full catalog instead of a greenlist membership check —
    see the SYMBOL ROUTING note in the module docstring for why we need the
    whole list rather than a filtered subset.
    """
    try:
        resp = httpx.get(REST_INSTRUMENTS_URL, params={"instType": inst_type}, timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:
        print(f"WARN: instruments fetch failed for {inst_type} ({exc!r}); skipping")
        return []
    return [d["instId"] for d in body.get("data", []) if d.get("state") == "live"]


def subscribe(symbols: list[str]) -> list[dict[str, Any]]:
    """Ignores `symbols` — liquidation-orders is instType-wide, not
    per-instrument (see SYMBOL ROUTING in the module docstring)."""
    return [
        {
            "op": "subscribe",
            "args": [{"channel": "liquidation-orders", "instType": it} for it in INST_TYPES],
        }
    ]


def error_of(msg: dict[str, Any]) -> str | None:
    return msg.get("msg") if msg.get("event") == "error" else None


def parse(msg: dict[str, Any], now: datetime) -> list[ParsedRow]:
    arg = msg.get("arg", {})
    if arg.get("channel") != "liquidation-orders":
        return []
    out: list[ParsedRow] = []
    for item in msg.get("data", []):
        inst_id = item.get("instId")
        if not inst_id:
            continue
        inst_family = item.get("instFamily", "")
        inst_type = item.get("instType") or arg.get("instType", "")
        for det in item.get("details", []):
            ts_ms = det.get("ts")
            ts = (
                datetime.fromtimestamp(int(ts_ms) / 1000, tz=now.tzinfo).isoformat()
                if ts_ms
                else now.isoformat()
            )
            out.append(
                (
                    inst_id,
                    "liquidations",
                    {
                        "ts": ts,
                        "inst_id": inst_id,
                        "inst_family": inst_family,
                        "inst_type": inst_type,
                        "pos_side": str(det.get("posSide", "")),
                        "side": str(det.get("side", "")),
                        "size": float(det.get("sz", 0) or 0),
                        "bk_px": float(det.get("bkPx", 0) or 0),
                        "bk_loss": float(det.get("bkLoss", 0) or 0),
                        "ccy": str(det.get("ccy", "")),
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
    max_streams_per_session=None,  # one instType-wide subscribe, one session
    throttled_streams=frozenset(),  # never coalesce liquidations
    # Liquidations are sporadic — long silences are NORMAL here, not a dead
    # socket. OKX closes a connection idle for ~30s and does not count
    # protocol-level pings, so without an application-level keepalive this
    # feed reconnected ~10x per 240s simply because nothing was liquidated.
    keepalive_text="ping",
    keepalive_interval_s=20.0,
    heartbeat_timeout_s=180.0,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--smoke",
        type=float,
        nargs="?",
        const=DEFAULT_SMOKE_S,
        default=None,
        help=(
            f"run N seconds then exit 0 (bare --smoke uses {DEFAULT_SMOKE_S:.0f}s — "
            "liquidations are sporadic, give it time)"
        ),
    )
    args = parser.parse_args()

    symbols: list[str] = []
    for inst_type in INST_TYPES:
        live = fetch_live_instruments(inst_type)
        print(f"INFO: {inst_type}: {len(live)} live instruments")
        symbols.extend(live)

    counts = asyncio.run(
        run_ws_collector(SPEC, symbols, resolve_liquidations_dir(), duration_s=args.smoke)
    )
    nonzero = {inst: n for inst, n in counts.items() if n > 0}
    total = sum(counts.values())
    for inst, n in sorted(nonzero.items()):
        print(f"{inst}: liquidations={n}")
    if args.smoke is not None and total == 0:
        print(
            f"INFO: 0 events in window (normal — liquidations are sporadic) "
            f"over {args.smoke:.0f}s across {len(symbols)} instruments"
        )
    else:
        print(f"INFO: {total} liquidation rows across {len(nonzero)}/{len(symbols)} instruments")
    sys.exit(0)


if __name__ == "__main__":
    main()
