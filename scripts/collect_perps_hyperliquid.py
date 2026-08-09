"""Perpetuals collector for Hyperliquid — funding/OI/mark context plus trades.

WHY A CUSTOM ORCHESTRATOR INSTEAD OF `run_ws_collector`. Every other collector
in this repo is pure WS: one `VenueSpec`, one `run_ws_collector` call, one
sink owned by that call. This venue needs a REST poll (universe ranking +
backstop `ctx` coverage for assets outside the tracked top-N) running
CONCURRENTLY with a WS stream that writes the SAME `ctx` stream for the
tracked coins. `PartitionedParquetSink._next_part` seeds its part-file
counter from disk once per (symbol, stream, hour) and then trusts its own
in-memory count — safe across separate PROCESSES (that is what it was built
for) but NOT safe across two independent sink INSTANCES writing the same
stream key inside one process: each seeds independently, so both can pick
part-0001 and the second write clobbers the first. `run_ws_collector`
constructs and owns its own sink with no way to hand it one, so it cannot be
reused here without that clobber risk. Fix: one hand-rolled loop, one shared
`PartitionedParquetSink` for both writers. `collector_core.py` is not
modified; this only composes its primitives (`PartitionedParquetSink`,
`backoff_delay`, `resolve_data_root`).

VENUE FACTS (given, verified by a prior probe — not re-probed):
POST https://api.hyperliquid.xyz/info {"type":"metaAndAssetCtxs"} needs no
auth, returns `[{universe:[...]}, [assetCtx,...]]` index-aligned, weight 20,
232 perps. WS wss://api.hyperliquid.xyz/ws, no auth. Limits: REST 1200
weight/min/IP; WS 10 conns / 1000 subs / 30 new conns/min.

RE-VERIFIED LIVE 2026-08-08 (this build), real captured frames:

    REST metaAndAssetCtxs universe[0]:
        {"szDecimals": 5, "name": "BTC", "maxLeverage": 40, "marginTableId": 56}
    REST metaAndAssetCtxs ctxs[0] (index-aligned to universe[0]):
        {"funding": "0.0000023861", "openInterest": "34574.21364",
         "prevDayPx": "64923.0", "dayNtlVlm": "410605134.8548099995",
         "premium": "-0.0004917176", "oraclePx": "65078.0", "markPx": "65046.9",
         "midPx": "65045.5", "impactPxs": ["65044.8", "65046.0"],
         "dayBaseVlm": "6318.3024"}

    WS subscribe envelope CONFIRMED as documented:
        {"method": "subscribe", "subscription": {"type": "activeAssetCtx", "coin": "BTC"}}
        {"method": "subscribe", "subscription": {"type": "trades", "coin": "BTC"}}
    WS subscriptionResponse ack:
        {"channel": "subscriptionResponse",
         "data": {"method": "subscribe", "subscription": {"type": "activeAssetCtx", "coin": "BTC"}}}
    WS activeAssetCtx push (ctx nested one level under data.ctx, unlike the
    flat REST array — parse code below accounts for this):
        {"channel": "activeAssetCtx", "data": {"coin": "BTC", "ctx": {
         "funding": "0.0000023861", "openInterest": "34574.12754",
         "prevDayPx": "64923.0", "dayNtlVlm": "410608094.415620029",
         "premium": "-0.0004917176", "oraclePx": "65078.0", "markPx": "65046.9",
         "midPx": "65045.5", "impactPxs": ["65044.8", "65046.0"],
         "dayBaseVlm": "6318.34791"}}}
    WS trades push (data is a LIST of fills per frame):
        {"channel": "trades", "data": [{"coin": "BTC", "side": "B", "px": "65050.0",
         "sz": "0.00022", "time": 1786221299743,
         "hash": "0x94ce7654860c4b4696480441bdcd3a020196003a210f6a18389721a745002531",
         "tid": 546335471944431,
         "users": ["0xa2ee24bdb8712e2e31bdee16618e56af38a271b3",
                    "0x6e8bc7cd0978397b06a14af2a8c31f5daeffea79"]}]}

    `side` is "B"/"A" (Bid/Ask, i.e. taker bought / taker sold) — mapped to
    "buy"/"sell" below to match the other venues' trade schema.

CANDIDATE LIQUIDATIONS — UNDOCUMENTED HEURISTIC, NOT AN API CONTRACT. A prior
probe found that some fills carry an all-zero `hash`
("0x0000...0000", 64 zero hex chars) instead of a real tx hash, and that
these correlate with forced/backstop-liquidator fills (33 of 601 trades in a
25s sample). Hyperliquid does not document this and it could change or break
silently — it is an INFERENCE, not ground truth. `is_candidate_liquidation`
is therefore a COLUMN on the ordinary trade tape, not a separate stream: a
separate "liquidations" table would imply an authority this heuristic does
not have.

STREAMS.
  `ctx`    — one row per (coin, update). Written from two sources sharing one
             sink: the WS `activeAssetCtx` push (near-real-time, tracked
             top-N coins only, zero REST weight) and a 30s REST
             `metaAndAssetCtxs` poll (all 232 coins — this is what gives
             coverage outside the top-N, and is also what ranks the
             universe). Neither is throttled: `ctx` updates are already
             low-rate relative to `BOOK_ROW_INTERVAL_S`.
  `trades` — one row per fill, WS only, tracked top-N coins. Never throttled
             (matches every other venue's trade stream in this repo — every
             print matters, and per-item 5 of the dispatch this stream must
             never be coalesced).

UNIVERSE. Top `--universe-size` (default 30) perps by USD notional open
interest (`openInterest` (base units) x `markPx`), recomputed every REST poll
but only ACTED on (WS resubscribe) once an hour, logged when it changes.
`--universe-only` prints the ranked table and exits without opening a sink or
a socket.

Run:
    uv run python scripts/collect_perps_hyperliquid.py --universe-only
    uv run python scripts/collect_perps_hyperliquid.py --smoke 120
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collector_core import (
    PartitionedParquetSink,
    backoff_delay,
    resolve_data_root,
)

VENUE = "hyperliquid"
INFO_URL = "https://api.hyperliquid.xyz/info"
WS_URL = "wss://api.hyperliquid.xyz/ws"

DEFAULT_UNIVERSE_SIZE = 30
REST_POLL_INTERVAL_S = 30.0
UNIVERSE_REFRESH_INTERVAL_S = 3600.0
WS_RECV_TIMEOUT_S = 30.0
ZERO_HASH = "0x" + "0" * 64


def resolve_perps_dir(venue: str = VENUE) -> Path:
    return resolve_data_root() / "perps" / venue


def perp_symbol(coin: str) -> str:
    """Directory/tuple key for a coin's perp — kept distinct from any spot
    "COIN/USD" tree elsewhere in the archive."""
    return f"{coin}-PERP"


# --------------------------------------------------------------------------- #
# REST: universe + ctx backstop
# --------------------------------------------------------------------------- #


def fetch_meta_and_ctxs_sync(
    timeout: float = 20.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    resp = httpx.post(INFO_URL, json={"type": "metaAndAssetCtxs"}, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    return body[0]["universe"], body[1]


async def fetch_meta_and_ctxs(
    client: httpx.AsyncClient,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    resp = await client.post(INFO_URL, json={"type": "metaAndAssetCtxs"})
    resp.raise_for_status()
    body = resp.json()
    return body[0]["universe"], body[1]


def notional_oi(ctx: dict[str, Any]) -> float:
    return _f(ctx.get("openInterest")) * _f(ctx.get("markPx"))


def rank_universe(
    universe: list[dict[str, Any]], ctxs: list[dict[str, Any]], top_n: int
) -> list[tuple[str, float]]:
    """[(coin, notional_oi_usd), ...] sorted descending, top `top_n`."""
    ranked = sorted(
        ((u["name"], notional_oi(c)) for u, c in zip(universe, ctxs, strict=True)),
        key=lambda pair: pair[1],
        reverse=True,
    )
    return ranked[:top_n]


def _f(value: Any) -> float:
    """Cast to float, defaulting missing/None to 0.0.

    Freshly-listed perps can carry `premium: null` (not enough trade history
    yet for the calc) — seen live for at least one universe member during
    this build. Every other numeric field here has been observed non-null,
    but None-safety costs nothing and a null field must not crash the poll.
    """
    return 0.0 if value is None else float(value)


def build_ctx_row(coin: str, ctx: dict[str, Any], ts: datetime) -> dict[str, Any]:
    mark_px = _f(ctx.get("markPx"))
    open_interest = _f(ctx.get("openInterest"))
    return {
        "ts": ts.isoformat(),
        "coin": coin,
        "funding": _f(ctx.get("funding")),
        "open_interest": open_interest,
        "open_interest_usd": open_interest * mark_px,
        "mark_px": mark_px,
        "oracle_px": _f(ctx.get("oraclePx")),
        "premium": _f(ctx.get("premium")),
        "mid_px": _f(ctx.get("midPx")),
        "day_ntl_vlm": _f(ctx.get("dayNtlVlm")),
    }


# --------------------------------------------------------------------------- #
# WS: subscribe payloads + frame parsing
# --------------------------------------------------------------------------- #


def sub_msg(kind: str, coin: str) -> dict[str, Any]:
    return {"method": "subscribe", "subscription": {"type": kind, "coin": coin}}


def unsub_msg(kind: str, coin: str) -> dict[str, Any]:
    return {"method": "unsubscribe", "subscription": {"type": kind, "coin": coin}}


def is_candidate_liquidation(hash_: str) -> bool:
    """INFERRED, not an API contract — see module docstring."""
    return hash_.lower() == ZERO_HASH


def parse_ws_frame(msg: dict[str, Any], now: datetime) -> list[tuple[str, str, dict[str, Any]]]:
    channel = msg.get("channel")
    out: list[tuple[str, str, dict[str, Any]]] = []
    if channel == "activeAssetCtx":
        data = msg.get("data") or {}
        coin = data.get("coin")
        ctx = data.get("ctx")
        if coin and ctx:
            out.append((perp_symbol(coin), "ctx", build_ctx_row(coin, ctx, now)))
    elif channel == "trades":
        for t in msg.get("data") or []:
            coin = t.get("coin")
            if not coin:
                continue
            ts_ms = t.get("time")
            ts = datetime.fromtimestamp(ts_ms / 1000, tz=UTC) if ts_ms else now
            hash_ = str(t.get("hash", ""))
            out.append(
                (
                    perp_symbol(coin),
                    "trades",
                    {
                        "ts": ts.isoformat(),
                        "price": float(t["px"]),
                        "qty": float(t["sz"]),
                        "side": "buy" if t.get("side") == "B" else "sell",
                        "trade_id": str(t.get("tid", "")),
                        "hash": hash_,
                        "is_candidate_liquidation": is_candidate_liquidation(hash_),
                    },
                )
            )
    return out


def error_of(msg: dict[str, Any]) -> str | None:
    if msg.get("channel") == "error":
        return str(msg.get("data"))
    return None


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


@dataclass
class UniverseState:
    coins: list[str] = field(default_factory=list)
    generation: int = 0


class SubscriptionTracker:
    """Owns one socket's subscribe/unsubscribe diffing against `UniverseState`.

    A plain object rather than a closure defined inside the reconnect loop —
    ruff (B023) correctly flags a nested function capturing per-iteration
    loop locals as fragile; this sidesteps that by giving each connection
    attempt its own tracker instance instead.
    """

    def __init__(self) -> None:
        self.subscribed: set[str] = set()
        self.applied_generation = -1

    async def apply(self, ws: Any, state: UniverseState) -> None:
        if state.generation == self.applied_generation:
            return
        target = set(state.coins)
        for coin in self.subscribed - target:
            await ws.send(json.dumps(unsub_msg("trades", coin)))
            await ws.send(json.dumps(unsub_msg("activeAssetCtx", coin)))
            self.subscribed.discard(coin)
        for coin in target - self.subscribed:
            await ws.send(json.dumps(sub_msg("trades", coin)))
            await ws.send(json.dumps(sub_msg("activeAssetCtx", coin)))
            self.subscribed.add(coin)
        self.applied_generation = state.generation


async def rest_poll_task(
    state: UniverseState,
    sink: PartitionedParquetSink,
    counts: dict[tuple[str, str], int],
    universe_size: int,
    loop: asyncio.AbstractEventLoop,
    deadline: float | None,
) -> None:
    attempt = 0
    last_universe_refresh = 0.0
    async with httpx.AsyncClient(timeout=20.0) as client:
        while deadline is None or loop.time() < deadline:
            try:
                universe, ctxs = await fetch_meta_and_ctxs(client)
            except Exception as exc:
                delay = backoff_delay(attempt)
                print(f"WARN: {VENUE}: REST poll failed: {exc!r}; retrying in {delay}s")
                attempt += 1
                await asyncio.sleep(delay)
                continue
            attempt = 0
            now = datetime.now(UTC)
            for u, c in zip(universe, ctxs, strict=True):
                coin = u["name"]
                symbol = perp_symbol(coin)
                sink.add(symbol, "ctx", build_ctx_row(coin, c, now), now)
                counts[(symbol, "ctx")] = counts.get((symbol, "ctx"), 0) + 1

            now_s = loop.time()
            if not state.coins or now_s - last_universe_refresh >= UNIVERSE_REFRESH_INTERVAL_S:
                ranked = rank_universe(universe, ctxs, universe_size)
                new_coins = [coin for coin, _ in ranked]
                if new_coins != state.coins:
                    print(f"INFO: {VENUE}: universe ({len(new_coins)}): {new_coins}")
                    state.coins = new_coins
                    state.generation += 1
                last_universe_refresh = now_s

            sink.flush_all(now)
            await asyncio.sleep(REST_POLL_INTERVAL_S)


async def ws_task(
    state: UniverseState,
    sink: PartitionedParquetSink,
    counts: dict[tuple[str, str], int],
    loop: asyncio.AbstractEventLoop,
    deadline: float | None,
) -> None:
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError(
            "collect_perps_hyperliquid requires the optional collector dependency "
            "group — run `uv sync --group collector`"
        ) from exc

    # Wait for the first universe computation before opening a socket.
    while not state.coins and (deadline is None or loop.time() < deadline):
        await asyncio.sleep(0.2)
    if not state.coins:
        return

    attempt = 0
    last_flush = loop.time()
    while deadline is None or loop.time() < deadline:
        try:
            async with websockets.connect(WS_URL, open_timeout=10) as ws:
                attempt = 0
                tracker = SubscriptionTracker()
                await tracker.apply(ws, state)

                while deadline is None or loop.time() < deadline:
                    remaining = (deadline - loop.time()) if deadline is not None else None
                    timeout = (
                        min(WS_RECV_TIMEOUT_S, remaining)
                        if remaining is not None
                        else WS_RECV_TIMEOUT_S
                    )
                    if timeout <= 0:
                        break
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    except TimeoutError:
                        await tracker.apply(ws, state)
                        continue
                    msg = json.loads(raw)
                    err = error_of(msg)
                    if err:
                        raise RuntimeError(f"{VENUE} rejected subscribe: {err}")
                    now = datetime.now(UTC)
                    for symbol, stream, row in parse_ws_frame(msg, now):
                        sink.add(symbol, stream, row, now)
                        counts[(symbol, stream)] = counts.get((symbol, stream), 0) + 1
                    if loop.time() - last_flush >= 60.0:
                        sink.flush_all(now)
                        last_flush = loop.time()
                    await tracker.apply(ws, state)
        except TimeoutError:
            if deadline is not None and loop.time() >= deadline:
                break
        except Exception as exc:
            delay = backoff_delay(attempt)
            print(f"WARN: {VENUE}: {exc!r}; reconnecting in {delay}s")
            attempt += 1
            await asyncio.sleep(delay)


async def run_collector(
    universe_size: int, base_dir: Path, duration_s: float | None = None
) -> dict[tuple[str, str], int]:
    sink = PartitionedParquetSink(base_dir)
    counts: dict[tuple[str, str], int] = {}
    state = UniverseState()
    loop = asyncio.get_event_loop()
    deadline = (loop.time() + duration_s) if duration_s is not None else None

    await asyncio.gather(
        rest_poll_task(state, sink, counts, universe_size, loop, deadline),
        ws_task(state, sink, counts, loop, deadline),
    )
    # force: on the way out, a small buffer is better written than lost.
    sink.flush_all(datetime.now(UTC), force=True)
    return counts


def print_universe(universe_size: int) -> None:
    universe, ctxs = fetch_meta_and_ctxs_sync()
    ranked = rank_universe(universe, ctxs, universe_size)
    by_name = {u["name"]: c for u, c in zip(universe, ctxs, strict=True)}
    print(f"{'rank':>4}  {'coin':<10}  {'notional_oi_usd':>18}  {'mark_px':>14}  {'funding':>14}")
    for i, (coin, oi_usd) in enumerate(ranked, start=1):
        c = by_name[coin]
        mark_px = _f(c.get("markPx"))
        funding = _f(c.get("funding"))
        print(f"{i:>4}  {coin:<10}  {oi_usd:>18,.0f}  {mark_px:>14,.4f}  {funding:>14.8f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe-size", type=int, default=DEFAULT_UNIVERSE_SIZE)
    parser.add_argument("--smoke", type=float, default=None, help="run N seconds then exit 0")
    parser.add_argument("--universe-only", action="store_true", help="print top-N table and exit")
    parser.add_argument("--base-dir", default=None)
    args = parser.parse_args()

    if args.universe_only:
        print_universe(args.universe_size)
        sys.exit(0)

    base = Path(args.base_dir) if args.base_dir else resolve_perps_dir()
    counts = asyncio.run(run_collector(args.universe_size, base, duration_s=args.smoke))
    for (symbol, stream), n in sorted(counts.items()):
        print(f"{symbol}/{stream}: {n}")
    sys.exit(0)


if __name__ == "__main__":
    main()
