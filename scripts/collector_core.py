"""Shared collector infrastructure — venue adapters supply only what differs.

The first three collectors (collect_ticks / collect_books_coinbase /
collect_books_binance) each carried their own copy of the Parquet sink, path
builder, throttle, backoff and reconnect loop. Adding five more venues that
way would mean five more copies of the same bugs. This module owns that
machinery once; a venue is a `VenueSpec` — a URL, a subscribe payload builder
and a parse function — and `run_ws_collector` does the rest.

Two deliberate departures from the original sink, both learned the hard way
on 2026-08-08:

1. WRITES ARE APPEND-ONLY. The original flushed by reading the whole hourly
   file back, concatenating, and rewriting it. That is O(file) per flush: at
   56 pairs it cost ~0.1 s per file per minute and made the process grow to
   ~400 MB within an hour. Here each flush writes a self-contained
   `<stream>-<HH>.part-<NNNN>.parquet`; `compact_hour` merges the parts into
   `<stream>-<HH>.parquet` once the hour is closed. Flush cost is O(rows).

   A persistent `pq.ParquetWriter` would also give O(rows) appends, but a
   Parquet file is unreadable until its footer is written on close — and
   these collectors DO die (see watchdog.log). Part files keep every
   already-flushed row readable no matter how the process ends; only the
   in-memory buffer is ever at risk.

2. FLUSHING IS TIME-BASED, NOT ONLY SIZE-BASED. collect_ticks flushed solely
   on a 5000-row threshold, so a quiet pair held its rows in RAM for hours,
   lost them on any crash, and mis-filed them into the flush hour's file when
   it finally crossed. Callers here get an unconditional `flush_due`.

Optional deps (`uv sync --group collector`): `websockets`, `pyarrow`. Both are
imported lazily so importing this module stays free — the pure logic below
(paths, partitioning, throttle, backoff, sharding) has no optional dep and is
what the unit tests exercise.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EXTERNAL_DATA_ROOT = Path("D:/tradekit-data")
LOCAL_DATA_ROOT = Path("data")

FLUSH_INTERVAL_S = 60.0
FLUSH_ROW_LIMIT = 5000
HEARTBEAT_TIMEOUT_S = 15.0
BOOK_ROW_INTERVAL_S = 1.0

# Asset-class partitioning. The archive began as a flat <SYMBOL>/ tree; on
# 2026-08-08 `migrate_layout.py --apply` moved all 124 existing symbol dirs
# under ticks/ and books/{coinbase,binance} into <class>/<SYMBOL>/ and this
# was flipped to True in the same maintenance window.
#
# Every collector routes its paths through `stream_dir`, so this constant is
# the single switch for the whole archive. It must agree with what is on disk:
# never flip it while anything is running, or the tree ends up half flat and
# half partitioned with no error to tell you.
PARTITION_BY_CLASS = True

# Which subdirectory a symbol lands in when partitioning is on. Order matters:
# first match wins, so put narrow rules above broad ones.
#
# The BASE asset decides "stables" and the QUOTE decides "cross". That
# distinction is load-bearing: USDC/USD is peg-monitoring data, whereas
# BTC/USDT is a basis instrument that happens to be quoted in a stablecoin.
# Filing the latter under "stables" would bury eleven majors in the sleeve
# we intend to publish as depeg data.
# Fiat-referenced tokens whose peg is the thing being watched. Non-USD issuers
# (TGBP, QCAD, BRL1, MXNB, EURQ, AUDF, XSGD, AUDD) are here so their pairs file
# under stables/ rather than fx/ — the base asset is what makes it peg data.
_STABLES = (
    "USDT|USDC|DAI|PYUSD|RLUSD|USDG|USDS|EURC|EURQ|EURS|EURT"
    "|XSGD|BRZ|BRL1|QCAD|CADC|AUDD|AUDF|TGBP|MXNB"
)
# USD is the archive's default quote, so it is excluded here — "/USD$" would
# otherwise pull every major (BTC/USD, ETH/USD, ...) into the FX sleeve.
_FIAT_QUOTE = "EUR|GBP|AUD|CHF|CAD|JPY"
_FIAT_BASE = f"USD|{_FIAT_QUOTE}"

_CLASS_RULES: list[tuple[str, str]] = [
    # Base is a stablecoin -> peg monitoring, whatever it is quoted against.
    (rf"^({_STABLES})/", "stables"),
    (r"^(PAXG|XAUT|ONDO|CFG)/", "rwa"),
    # A fiat base is always an FX pair (EUR/USD, GBP/USD).
    (rf"^({_FIAT_BASE})/", "fx"),
    # A non-USD fiat quote is a cross-quote of the same asset (BTC/EUR).
    (rf"/({_FIAT_QUOTE})$", "fx"),
    # Quoted in crypto or a stablecoin -> ratio / basis series.
    (rf"/(BTC|ETH|{_STABLES})$", "cross"),
]
_DEFAULT_CLASS = "crypto"


def resolve_data_root(
    external_root: Path = EXTERNAL_DATA_ROOT, local_root: Path = LOCAL_DATA_ROOT
) -> Path:
    """The external drive when mounted, else the repo-local fallback.

    Checked once at process start, never per flush — a drive that vanishes
    mid-run must surface as a loud write error, not a silent relocation that
    splits one day across two roots.
    """
    return external_root if external_root.is_dir() else local_root


def asset_class(symbol: str) -> str:
    """Partition directory for `symbol` (e.g. "USDC/USD" -> "stables")."""
    for pattern, name in _CLASS_RULES:
        if re.search(pattern, symbol):
            return name
    return _DEFAULT_CLASS


def symbol_dirname(symbol: str) -> str:
    """Filesystem-safe form of a venue symbol ("BTC/USD" -> "BTC_USD")."""
    return symbol.replace("/", "_").replace(":", "_")


def stream_dir(
    base_dir: Path, symbol: str, ts: datetime, partition: bool | None = None
) -> Path:
    """Directory holding one symbol's files for the UTC day of `ts`."""
    use_partition = PARTITION_BY_CLASS if partition is None else partition
    parts = [base_dir]
    if use_partition:
        parts.append(Path(asset_class(symbol)))
    parts.extend([Path(symbol_dirname(symbol)), Path(ts.strftime("%Y-%m-%d"))])
    out = parts[0]
    for p in parts[1:]:
        out = out / p
    return out


def hour_file_path(
    base_dir: Path,
    symbol: str,
    stream: str,
    ts: datetime,
    part: int | None = None,
    partition: bool | None = None,
) -> Path:
    """Compacted hourly file, or a numbered part file when `part` is given."""
    name = (
        f"{stream}-{ts:%H}.parquet"
        if part is None
        else f"{stream}-{ts:%H}.part-{part:04d}.parquet"
    )
    return stream_dir(base_dir, symbol, ts, partition) / name


# Stream names may contain digits and capitals ("aggTrades", "book5"). This
# was `[a-z_]+` until 2026-08-08, and the failure mode was vicious: a stream
# the regex could not match made `part_files()` return nothing, so BOTH
# `compact_hour` (permanent silent no-op) and `_next_part` (always returns 0,
# so every flush overwrites part-0000) broke. Verified: three writes of an
# "aggTrades" stream left one file with only the last row. No error either
# time. `_assert_stream_name` below makes the class of bug loud instead.
_STREAM_CHARS = r"[A-Za-z0-9_]+"
_PART_RE = re.compile(rf"^(?P<stream>{_STREAM_CHARS})-(?P<hour>\d{{2}})\.part-\d{{4}}\.parquet$")
_STREAM_RE = re.compile(rf"^{_STREAM_CHARS}$")


def _assert_stream_name(stream: str) -> None:
    """Reject a stream name the part-file regex could not round-trip.

    Cheap insurance against reintroducing the silent-data-loss bug above: a
    name containing "-" or "." would parse ambiguously and quietly disable
    both compaction and part numbering.
    """
    if not _STREAM_RE.match(stream):
        raise ValueError(
            f"stream name {stream!r} must match {_STREAM_CHARS} — other characters "
            "break part-file discovery, which silently disables compaction and "
            "makes every flush overwrite part-0000"
        )


def part_files(day_dir: Path, stream: str, hour: int) -> list[Path]:
    """Every part file for one (stream, hour), in write order."""
    if not day_dir.is_dir():
        return []
    out = []
    for p in day_dir.iterdir():
        m = _PART_RE.match(p.name)
        if m and m.group("stream") == stream and int(m.group("hour")) == hour:
            out.append(p)
    return sorted(out)


def compact_hour(day_dir: Path, stream: str, hour: int) -> int:
    """Merge part files into the single hourly file and delete them.

    Safe to run repeatedly and safe to interrupt: the merged file is written
    to a temp name and renamed over the target before any part is unlinked,
    so a crash mid-compaction leaves either the parts or the finished file —
    never a half-written one. Returns rows written (0 when nothing to do).
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    parts = part_files(day_dir, stream, hour)
    if not parts:
        return 0
    target = day_dir / f"{stream}-{hour:02d}.parquet"
    tables = []
    if target.exists():
        tables.append(pq.read_table(target))
    for p in parts:
        try:
            tables.append(pq.read_table(p))
        except Exception as exc:  # a part truncated by a hard kill
            print(f"WARN: skipping unreadable part {p.name}: {exc!r}")
    if not tables:
        return 0
    merged = pa.concat_tables(tables, promote_options="default")
    tmp = target.with_suffix(".parquet.tmp")
    pq.write_table(merged, tmp, compression="zstd", compression_level=3)
    tmp.replace(target)
    for p in parts:
        p.unlink(missing_ok=True)
    return merged.num_rows


# A parquet file carries fixed footer/schema overhead regardless of how many
# rows it holds, so flushing every buffer on every tick is ruinous at high
# symbol counts. Measured 2026-08-08 with a plain 60s flush-everything loop:
# Hyperliquid (232 assets x 2 streams) averaged 6 rows/file at 572 bytes/row,
# and OKX books 25 rows/file at 1110 bytes/row — against Coinbase's 126
# bytes/row on the same schema. Nearly an order of magnitude of pure overhead.
#
# So a buffer is only written once it is worth a file. The age and hour
# escapes below bound what that costs: no row waits more than
# MAX_BUFFER_AGE_S, and a buffer whose oldest row belongs to a past hour is
# written out rather than held, so a closed hour reaches compaction promptly.
MIN_PART_ROWS = 500
MAX_BUFFER_AGE_S = 600.0


@dataclass
class _Buffer:
    # (event timestamp, row). The timestamp is carried alongside the row
    # because it, not the moment of the flush, decides where the row is filed.
    rows: list[tuple[datetime, dict[str, Any]]] = field(default_factory=list)
    # Timestamp of the first row currently buffered — drives both the age
    # escape and the hour-boundary escape.
    first_ts: datetime | None = None


class PartitionedParquetSink:
    """Buffers rows per (symbol, stream) and flushes them to part files.

    Every row is filed under the day and hour of ITS OWN timestamp. That is
    the whole point of an hour-partitioned archive and it was wrong until
    2026-08-09: the target file used to be named from flush time, so the path
    recorded when we ingested a row rather than when it happened. On a live
    websocket the two are close enough that only hour-boundary stragglers
    leaked (~0.7% of rows), but a delayed poller diverges by design and filed
    an entire Friday equity tape under Sunday's date. A partition key you
    cannot trust is worse than none, because it invites time-ranged reads that
    silently return the wrong rows.

    One flush therefore writes one part file per (day, hour) the buffer spans,
    not one file per flush.

    `add` triggers a flush at FLUSH_ROW_LIMIT; callers must additionally call
    `flush_all` on a timer so quiet symbols cannot sit in RAM.
    """

    def __init__(self, base_dir: Path, partition: bool | None = None) -> None:
        try:
            import pyarrow  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "PartitionedParquetSink requires the optional collector dependency "
                "group — run `uv sync --group collector`"
            ) from exc
        self.base_dir = base_dir
        self.partition = partition
        self._buffers: dict[tuple[str, str], _Buffer] = {}
        # Next part index per (symbol, stream, YYYY-MM-DD, HH), seeded from
        # disk the first time each hour is written. See `_next_part`.
        self._part_seq: dict[tuple[str, str, str, int], int] = {}
        self._rows_written = 0

    def _next_part(self, symbol: str, stream: str, ts: datetime) -> int:
        """Part index to write next, continuing any parts already on disk.

        An in-memory counter alone is wrong, and silently so: it restarts at 0
        for every new sink instance, so a second sink writing the same hour
        overwrites `part-0000` and the first sink's rows vanish with no error.
        That bites a REST poller that builds a sink per pass, and — worse —
        any collector that dies mid-hour and gets relaunched by the watchdog,
        which would clobber everything written since the top of the hour.

        Seeding from disk once per hour costs one small directory listing and
        makes the numbering correct across instances, restarts and crashes.
        """
        key = (symbol, stream, ts.strftime("%Y-%m-%d"), ts.hour)
        nxt = self._part_seq.get(key)
        if nxt is None:
            day_dir = stream_dir(self.base_dir, symbol, ts, self.partition)
            # `part_files` only returns names matched by _PART_RE, whose part
            # index is `\d{4}` — so this int() cannot fail and is not guarded.
            nxt = 0
            for p in part_files(day_dir, stream, ts.hour):
                nxt = max(nxt, int(p.stem.rsplit("-", 1)[-1]) + 1)
        self._part_seq[key] = nxt + 1
        return nxt

    @property
    def rows_written(self) -> int:
        return self._rows_written

    def add(self, symbol: str, stream: str, row: dict[str, Any], ts: datetime) -> None:
        if (symbol, stream) not in self._buffers:
            _assert_stream_name(stream)
        buf = self._buffers.setdefault((symbol, stream), _Buffer())
        if not buf.rows:
            buf.first_ts = ts
        buf.rows.append((ts, row))
        if len(buf.rows) >= FLUSH_ROW_LIMIT:
            self.flush(symbol, stream)

    def _should_flush(self, buf: _Buffer, ts: datetime) -> bool:
        """Whether this buffer has earned a part file yet. See MIN_PART_ROWS."""
        if not buf.rows:
            return False
        if len(buf.rows) >= MIN_PART_ROWS:
            return True
        first = buf.first_ts
        if first is None:
            return True
        # Rows are filed by their own timestamp, so holding one past its hour
        # no longer misfiles it — but it does keep a closed hour out of reach
        # of compaction. Write it out instead.
        if (first.hour, first.date()) != (ts.hour, ts.date()):
            return True
        return (ts - first).total_seconds() >= MAX_BUFFER_AGE_S

    def flush(self, symbol: str, stream: str) -> int:
        """Write the buffer out, one part file per (day, hour) it spans.

        There is deliberately no `ts` parameter. The caller's notion of "now"
        has no say in where a row is filed — only the row's own timestamp
        does — and a parameter that looks like it decides the path but does
        not is exactly how the misfiling bug survived review.
        """
        import pyarrow as pa
        import pyarrow.parquet as pq

        buf = self._buffers.get((symbol, stream))
        if not buf or not buf.rows:
            return 0
        # Insertion-ordered, so arrival order survives inside each hour.
        groups: dict[tuple[str, int], tuple[datetime, list[dict[str, Any]]]] = {}
        for ts, row in buf.rows:
            _, rows = groups.setdefault((ts.strftime("%Y-%m-%d"), ts.hour), (ts, []))
            rows.append(row)
        n = 0
        for ts, rows in groups.values():
            path = hour_file_path(
                self.base_dir,
                symbol,
                stream,
                ts,
                self._next_part(symbol, stream, ts),
                self.partition,
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            table = pa.Table.from_pylist(rows)
            pq.write_table(table, path, compression="zstd", compression_level=3)
            n += len(rows)
        buf.rows.clear()
        buf.first_ts = None
        self._rows_written += n
        return n

    def flush_all(self, ts: datetime, force: bool = False) -> int:
        """Flush every buffer that has earned a file.

        `force=True` drains everything regardless — use it on shutdown, where
        the alternative is losing the rows entirely.
        """
        total = 0
        for key in list(self._buffers):
            buf = self._buffers[key]
            if force or self._should_flush(buf, ts):
                total += self.flush(key[0], key[1])
        return total

    def buffered_rows(self) -> int:
        return sum(len(b.rows) for b in self._buffers.values())


class RowThrottle:
    """At most one row per key per `interval_s`.

    Book deltas arrive hundreds of times a second on liquid pairs; coalescing
    to 1 Hz keeps the archive proportional to time rather than to venue
    chattiness. Trades are never throttled — every print matters.
    """

    def __init__(self, interval_s: float = BOOK_ROW_INTERVAL_S) -> None:
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


def shard(items: Sequence[str], size: int | None) -> list[list[str]]:
    """Split a symbol list into per-session chunks.

    Venues cap streams per connection (Coinbase level2 rejects the 31st with
    "too many L2 streams requested in a single session" and then goes silent,
    which is indistinguishable from a dead socket). `size=None` means no cap.
    """
    if size is None or size <= 0 or len(items) <= size:
        return [list(items)]
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


# A parsed row: (symbol, stream, row-dict). A venue's parse function returns
# any number of these per inbound frame.
ParsedRow = tuple[str, str, dict[str, Any]]


@dataclass(frozen=True)
class VenueSpec:
    """Everything that differs between venues. The runner owns the rest."""

    name: str
    ws_url: str
    # symbols -> the JSON payloads to send on connect (one or more)
    subscribe: Callable[[list[str]], list[dict[str, Any]]]
    # (frame, now) -> parsed rows
    parse: Callable[[dict[str, Any], datetime], list[ParsedRow]]
    # frame -> error text when the venue rejected us, else None. Venues that
    # answer a bad subscribe with one error frame and then silence must be
    # surfaced here or the runner will livelock on heartbeat reconnects.
    error_of: Callable[[dict[str, Any]], str | None] = lambda _m: None
    max_streams_per_session: int | None = None
    # Streams whose rows are coalesced to BOOK_ROW_INTERVAL_S.
    throttled_streams: frozenset[str] = frozenset({"book"})
    heartbeat_timeout_s: float = HEARTBEAT_TIMEOUT_S
    # level2 snapshots exceed the websockets 1 MiB default on deep books.
    max_frame_bytes: int | None = None
    # Application-level keepalive. Some venues close a connection that has
    # been idle for N seconds and do NOT count protocol-level WebSocket pings
    # towards liveness — OKX drops after ~30s of silence. That is invisible on
    # a chatty book feed but shreds a sparse one: the liquidation stream was
    # reconnecting ~10 times per 240s simply because nothing had been
    # liquidated. Set this to the literal payload the venue expects.
    keepalive_text: str | None = None
    keepalive_interval_s: float = 20.0


async def run_ws_collector(
    spec: VenueSpec,
    symbols: list[str],
    base_dir: Path,
    duration_s: float | None = None,
    partition: bool | None = None,
) -> dict[str, int]:
    """Subscribe, parse, and persist until `duration_s` elapses (None=forever).

    Shards across sessions when the venue caps streams per connection, runs
    the shards concurrently, and reconnects each independently with capped
    exponential backoff. Returns rows written per symbol.
    """
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError(
            "run_ws_collector requires the optional collector dependency group — "
            "run `uv sync --group collector`"
        ) from exc

    sink = PartitionedParquetSink(base_dir, partition)
    counts: dict[str, int] = dict.fromkeys(symbols, 0)
    throttle = RowThrottle()
    loop = asyncio.get_event_loop()
    deadline = (loop.time() + duration_s) if duration_s is not None else None

    shards = shard(symbols, spec.max_streams_per_session)
    if len(shards) > 1:
        print(
            f"INFO: {spec.name}: {len(symbols)} symbols over {len(shards)} sessions "
            f"(cap {spec.max_streams_per_session}/session)"
        )

    async def run_shard(chunk: list[str]) -> None:
        last_flush = loop.time()
        attempt = 0
        while deadline is None or loop.time() < deadline:
            try:
                async with websockets.connect(
                    spec.ws_url, open_timeout=10, max_size=spec.max_frame_bytes
                ) as ws:
                    attempt = 0
                    for payload in spec.subscribe(chunk):
                        await ws.send(json.dumps(payload))
                    last_keepalive = last_msg = loop.time()
                    while deadline is None or loop.time() < deadline:
                        if (
                            spec.keepalive_text
                            and loop.time() - last_keepalive >= spec.keepalive_interval_s
                        ):
                            await ws.send(spec.keepalive_text)
                            last_keepalive = loop.time()
                        # Poll in slices no longer than the keepalive interval,
                        # otherwise a sparse feed blocks past the moment the
                        # ping was due and the venue closes on us. Liveness is
                        # judged by time since the last MESSAGE, not by whether
                        # any single recv timed out.
                        remaining = (deadline - loop.time()) if deadline is not None else None
                        slice_s = spec.heartbeat_timeout_s
                        if spec.keepalive_text:
                            slice_s = min(slice_s, spec.keepalive_interval_s / 2)
                        timeout = min(slice_s, remaining) if remaining is not None else slice_s
                        if timeout <= 0:
                            break
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                        except TimeoutError:
                            if loop.time() - last_msg >= spec.heartbeat_timeout_s:
                                raise
                            continue  # quiet, but not yet dead
                        last_msg = loop.time()
                        try:
                            msg = json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            # Text keepalive replies are not JSON — OKX answers
                            # our "ping" with a bare "pong". It still proves the
                            # socket is alive, which is the whole point, so
                            # count it and move on rather than reconnecting.
                            continue
                        err = spec.error_of(msg)
                        if err:
                            raise RuntimeError(f"{spec.name} rejected subscribe: {err}")
                        now = datetime.now(UTC)
                        for symbol, stream, row in spec.parse(msg, now):
                            if symbol not in counts:
                                continue
                            if stream in spec.throttled_streams and not throttle.allow(
                                f"{symbol}/{stream}", loop.time()
                            ):
                                continue
                            sink.add(symbol, stream, row, now)
                            counts[symbol] += 1
                        if loop.time() - last_flush >= FLUSH_INTERVAL_S:
                            sink.flush_all(now)
                            last_flush = loop.time()
            except TimeoutError:
                if deadline is not None and loop.time() >= deadline:
                    break
                print(f"WARN: {spec.name}: heartbeat timeout — reconnecting")
            except Exception as exc:
                delay = backoff_delay(attempt)
                print(f"WARN: {spec.name}: {exc!r}; reconnecting in {delay}s")
                attempt += 1
                await asyncio.sleep(delay)
            else:
                continue

    await asyncio.gather(*(run_shard(c) for c in shards))
    # force: on the way out, a small buffer is better written than lost.
    sink.flush_all(datetime.now(UTC), force=True)
    return counts


def compact_closed_hours(base_dir: Path, now: datetime | None = None) -> int:
    """Compact every hour that is fully in the past. Run from a scheduled task.

    The current hour is skipped so a live collector's parts are never merged
    out from under it.
    """
    now = now or datetime.now(UTC)
    current = (now.strftime("%Y-%m-%d"), now.hour)
    merged = 0
    for day_dir in sorted(p for p in base_dir.rglob("*") if p.is_dir()):
        seen: set[tuple[str, int]] = set()
        for f in day_dir.iterdir():
            m = _PART_RE.match(f.name)
            if m:
                seen.add((m.group("stream"), int(m.group("hour"))))
        for stream, hour in sorted(seen):
            if (day_dir.name, hour) == current:
                continue
            merged += compact_hour(day_dir, stream, hour)
    return merged


def iter_symbol_dirs(base_dir: Path) -> Iterable[Path]:
    """Every leaf day-directory under `base_dir`, layout-agnostic."""
    for p in base_dir.rglob("*"):
        if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name):
            yield p
