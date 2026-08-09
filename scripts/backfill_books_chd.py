"""Backfill order-book (and other) history from cryptohftdata.com.

WHY THIS EXISTS. Kraken publishes no historical order-book REST endpoint —
scripts/backfill_ticks.py's docstring says so, and every gap in our L2 book
archive has therefore been permanently unfillable by our own means.
cryptohftdata.com sells exactly that: hourly L2 incremental-diff dumps per
exchange/symbol. This script finds the gaps in our OWN archive and fetches
only those hours from the vendor.

PROVENANCE. Vendor data is written under
`<data-root>/backfill/chd/<exchange>/<PAIR>/<date>/<datatype>-<HH>.parquet`
— a tree kept SEPARATE from anything our own collectors wrote. It is never
merged into the live archive: provenance must stay separable (needed for the
open-source release, and because a vendor's book state can legitimately
disagree with ours at the edges). Existing files are never overwritten.

API (probed 2026-08-07/08 against the live service):
    auth:      POST /jwt-token       header X-API-Key: <key> -> {jwt_token, expires_in: 14400}
    download:  GET  /download?file=<path>   header Authorization: Bearer <jwt>
    symbols:   GET  /symbols?exchange=<id>  (no auth) -> {"symbols": [...]}
    path:      {exchange}/{YYYY-MM-DD}/{HH}/{symbol}_{datatype}.parquet.zst
               ONE FILE PER SYMBOL PER HOUR — a day of one pair is 24 fetches.
Static objects, not a query API: no filtering, no pagination, no partial-hour
fetch. Symbols use an underscore (BTC_USD, never Kraken's XBT).

--start/--end WINDOW: `--end` is EXCLUSIVE, matching backfill_ticks.py's
`missing_hours` convention (the current, still-in-progress hour is never
counted as missing). `--start 2026-08-05 --end 2026-08-06` scans exactly
the 24 hours of 2026-08-05, not 2026-08-05 through 2026-08-06.

HISTORY_FLOOR (2025-06-29): every exchange tested 404s before this date —
refused outright, never hammered. There is ALSO a rolling lag on the recent
side (measured ~10-11 days behind "now" as of 2026-08-08: 2026-07-28 12:00
UTC was the last hour available, 2026-07-28 23:00 already 404s) — that
boundary is NOT hardcoded here because it visibly drifts day to day; a 404
on a recent hour is reported as "not published yet (or genuinely absent)"
and skipped, not treated as a hard error or retried into the ground.

FORMAT. Genuine L2 incremental diffs, not snapshots. Columns: received_time
and event_time are int64 NANOSECOND epochs, transaction_time is int64
MILLISECOND epoch, symbol is "BASE/QUOTE" (a slash — the vendor's own
convention, distinct from the underscore in the download path), price and
quantity arrive as STRINGS. This script casts price/quantity to float64 and
adds a `ts` column (ISO8601 UTC string, matching collect_ticks' row
convention) derived from event_time.

SIZE. Measured: kraken_spot orderbook ~7.95 MB/hour compressed (BTC_USD,
~190 MB/day); binance_futures orderbook ~15.9 MB/hour (BTCUSDT, ~382 MB/day,
~104M rows/day). Other exchange/datatype combinations fall back to a
conservative default and are flagged UNMEASURED in the estimate. Dry run
always prints hours-to-fetch and an estimated download size; a real run
additionally requires `--yes` (or an interactive confirmation) once the
estimate crosses SIZE_CONFIRM_MB.

KNOWN-BROKEN: `klines` is advertised by the vendor but 404s on every
exchange tested — refused outright rather than offered as a choice.

Rate limits: no `X-RateLimit-*` header was ever seen; 40 sequential authed
requests hit zero 429s, but the authenticated ceiling is UNKNOWN. Downloads
run with bounded concurrency (`--concurrency`, default 4, hard-capped at 4)
and back off exponentially (`collector_core.backoff_delay`) on 429/5xx.

Run (from repo root):
    uv run python scripts/backfill_books_chd.py --dry-run --pair BTC/USD
    uv run python scripts/backfill_books_chd.py --pair BTC/USD --no-dry-run \\
        --max-hours 2 --yes
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backfill_ticks as bt  # noqa: E402  (reuse floor_hour/missing_hours/gap_spans)
from collector_core import (  # noqa: E402
    backoff_delay,
    iter_symbol_dirs,
    resolve_data_root,
    symbol_dirname,
)

CHD_BASE_URL = "https://api.cryptohftdata.com"

# Every exchange tested 404s before this date — refuse outright rather than
# hammer the API with doomed requests. See module docstring for the (not
# hardcoded, because it drifts) recent-side lag.
HISTORY_FLOOR = datetime(2025, 6, 29, tzinfo=UTC)

ALLOWED_DATATYPES = frozenset(
    {"orderbook", "trades", "liquidations", "open_interest", "mark_price", "ticker"}
)
# Advertised by the vendor, 404s everywhere tested — refuse rather than offer.
KNOWN_BROKEN_DATATYPES = frozenset({"klines"})

MAX_CONCURRENCY = 4
JWT_REFRESH_SLACK_S = 300  # re-auth 5 min before the vendor's stated expiry

# Measured MB/hour (compressed, on the wire) for exchange+orderbook. Anything
# absent here (any other exchange, or any other datatype) uses
# DEFAULT_HOUR_MB and is flagged UNMEASURED in the size estimate.
MEASURED_HOUR_MB: dict[tuple[str, str], float] = {
    ("kraken_spot", "orderbook"): 7.95,
    ("binance_futures", "orderbook"): 15.9,
}
DEFAULT_HOUR_MB = 6.0

# Above this estimated total, a real (non-dry-run) pull requires --yes or an
# interactive confirmation.
SIZE_CONFIRM_MB = 20.0

# Local archive this tool can gap-scan against, keyed by CHD exchange id:
# (relative dir under resolve_data_root(), {chd_datatype: local file-prefix}).
# Only populated for archives verified to exist on disk. An exchange absent
# here has no local counterpart to diff against — --start/--end become
# mandatory and every hour in the range is treated as "missing".
ARCHIVE_MAP: dict[str, tuple[str, dict[str, str]]] = {
    "kraken_spot": ("ticks", {"orderbook": "book", "trades": "trades"}),
    "binance_spot": ("books/binance", {"orderbook": "book"}),
}


# --------------------------------------------------------------------------
# Pure logic — no network, exercised directly by unit tests.
# --------------------------------------------------------------------------


def chd_symbol(pair: str) -> str:
    """"BTC/USD" -> "BTC_USD" — same transform as collector_core.symbol_dirname,
    named separately because it is a vendor wire-format requirement, not a
    filesystem-safety one, even though the two happen to coincide today."""
    return symbol_dirname(pair)


def download_path(exchange: str, pair: str, datatype: str, hour: datetime) -> str:
    return f"{exchange}/{hour:%Y-%m-%d}/{hour:%H}/{chd_symbol(pair)}_{datatype}.parquet.zst"


def local_archive_dir(exchange: str) -> Path | None:
    entry = ARCHIVE_MAP.get(exchange)
    if entry is None:
        return None
    rel, _ = entry
    return resolve_data_root() / rel


def local_stream_prefix(exchange: str, datatype: str) -> str | None:
    entry = ARCHIVE_MAP.get(exchange)
    if entry is None:
        return None
    return entry[1].get(datatype)


def present_hours(base_dir: Path, pair: str, stream_prefix: str) -> set[datetime]:
    """Hours already on disk for (pair, stream), scanning EITHER the flat
    `<PAIR>/<date>/` layout or the partitioned `<class>/<PAIR>/<date>/` one —
    `iter_symbol_dirs` finds every day-directory regardless of nesting, so
    this only has to check the leaf's own parent name."""
    want = symbol_dirname(pair)
    hours: set[datetime] = set()
    for day_dir in iter_symbol_dirs(base_dir):
        if day_dir.parent.name != want:
            continue
        try:
            day = datetime.strptime(day_dir.name, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            continue
        for f in day_dir.glob(f"{stream_prefix}-*.parquet"):
            stem = f.name[: -len(".parquet")]
            try:
                hh = int(stem.rsplit("-", 1)[-1])
            except ValueError:
                continue
            hours.add(day + timedelta(hours=hh))
    return hours


def clamp_to_floor(hours: list[datetime]) -> tuple[list[datetime], int]:
    """(in-range hours, count dropped for being before HISTORY_FLOOR)."""
    keep = [h for h in hours if h >= HISTORY_FLOOR]
    return keep, len(hours) - len(keep)


def estimate_mb(exchange: str, datatype: str, n_hours: int) -> tuple[float, bool]:
    """(estimated MB, is_measured). Unmeasured combos use a conservative
    default and the caller must say so — don't present a guess as fact."""
    per_hour = MEASURED_HOUR_MB.get((exchange, datatype))
    if per_hour is not None:
        return per_hour * n_hours, True
    return DEFAULT_HOUR_MB * n_hours, False


def gap_report(
    exchange: str,
    pairs: list[str],
    datatype: str,
    start: datetime | None,
    end: datetime | None,
    now: datetime | None = None,
) -> dict[str, list[datetime]]:
    """Per-pair missing hours in the scanned window — `[start, end)` when
    both are given (END IS EXCLUSIVE, same convention as backfill_ticks'
    `missing_hours`: the current, still-in-progress hour is never counted
    as missing), else the local archive's own `[earliest hour, now)`.

    `have` and `miss` are both scoped to that SAME window, so the two
    always sum to the printed window length — the (`have` archive-wide,
    `miss` window-scoped) mismatch from the first version made a report
    that looked internally inconsistent to whoever has to eyeball it before
    authorising a paid, possibly multi-GB pull. Hours before HISTORY_FLOOR
    are counted in `miss` (so the sum invariant holds) but reported via a
    separate note and dropped from the returned, actually-fetchable list.
    """
    now = now or datetime.now(UTC)
    base_dir = local_archive_dir(exchange)
    stream_prefix = local_stream_prefix(exchange, datatype)
    print(f"{'pair':<12} {'window':<42} {'have':>5} {'miss':>5}  largest gap")
    out: dict[str, list[datetime]] = {}
    for pair in pairs:
        if base_dir is not None and stream_prefix is not None:
            present = present_hours(base_dir, pair, stream_prefix)
        else:
            present = set()
        if start is not None and end is not None:
            window_start = bt.floor_hour(start)
            window_end = bt.floor_hour(end)
            cur = window_start
            missing = []
            while cur < window_end:
                if cur not in present:
                    missing.append(cur)
                cur += timedelta(hours=1)
        elif present:
            window_start = min(present)
            window_end = bt.floor_hour(now)
            missing = bt.missing_hours(present, now)
        else:
            print(f"{pair:<12} (no local archive for {exchange}/{datatype} — pass --start/--end)")
            out[pair] = []
            continue
        window_hours = max(int((window_end - window_start).total_seconds() // 3600), 0)
        have_count = window_hours - len(missing)
        fetchable, dropped = clamp_to_floor(missing)
        if dropped:
            print(
                f"  ({dropped} hour(s) before HISTORY_FLOOR {HISTORY_FLOOR:%Y-%m-%d} "
                f"excluded from the fetch — permanently unfillable, still counted in miss below)"
            )
        spans = bt.gap_spans(missing)
        largest = max(spans, key=lambda s: (s[1] - s[0]), default=None)
        largest_str = (
            f"{largest[0]:%Y-%m-%d %H}h..{largest[1]:%Y-%m-%d %H}h "
            f"({int((largest[1] - largest[0]).total_seconds() // 3600) + 1}h)"
            if largest
            else "-"
        )
        window_str = f"{window_start:%Y-%m-%d %H}h..{window_end:%Y-%m-%d %H}h ({window_hours}h)"
        print(f"{pair:<12} {window_str:<42} {have_count:>5} {len(missing):>5}  {largest_str}")
        out[pair] = fetchable
    return out


# --------------------------------------------------------------------------
# Network — JWT auth, download, decode.
# --------------------------------------------------------------------------


def load_dotenv(path: Path) -> None:
    """Populate os.environ from the repo .env without adding a dependency
    (mirrors collect_equities_alpaca.load_dotenv)."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


class ChdAuth:
    """Caches the vendor JWT and re-authenticates transparently before it
    expires (4h TTL) or the moment the vendor rejects it — a long backfill
    must never die on a stale token."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._jwt: str | None = None
        self._expiry_monotonic = 0.0

    def invalidate(self) -> None:
        self._jwt = None

    def token(self, client: httpx.Client) -> str:
        if self._jwt is not None and time.monotonic() < self._expiry_monotonic:
            return self._jwt
        resp = client.post(
            f"{CHD_BASE_URL}/jwt-token", headers={"X-API-Key": self._api_key}, timeout=20
        )
        resp.raise_for_status()
        body = resp.json()
        self._jwt = body["jwt_token"]
        ttl = float(body.get("expires_in", 14400))
        self._expiry_monotonic = time.monotonic() + max(ttl - JWT_REFRESH_SLACK_S, 60.0)
        return self._jwt


def fetch_symbols(client: httpx.Client, exchange: str) -> set[str]:
    resp = client.get(f"{CHD_BASE_URL}/symbols", params={"exchange": exchange}, timeout=20)
    resp.raise_for_status()
    return set(resp.json().get("symbols", []))


@dataclass
class DownloadResult:
    hour: datetime
    raw: bytes | None  # None = 404 (not published / absent), skip silently


def download_hour(
    client: httpx.Client,
    auth: ChdAuth,
    exchange: str,
    pair: str,
    datatype: str,
    hour: datetime,
    max_retries: int = 6,
) -> DownloadResult:
    path = download_path(exchange, pair, datatype, hour)
    for attempt in range(max_retries):
        jwt = auth.token(client)
        resp = client.get(
            f"{CHD_BASE_URL}/download",
            params={"file": path},
            headers={"Authorization": f"Bearer {jwt}"},
            timeout=60,
        )
        if resp.status_code == 404:
            return DownloadResult(hour, None)
        if resp.status_code == 401:
            auth.invalidate()
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            delay = backoff_delay(attempt)
            print(f"WARN: {path}: HTTP {resp.status_code}; retrying in {delay:.1f}s")
            time.sleep(delay)
            continue
        resp.raise_for_status()
        return DownloadResult(hour, resp.content)
    raise RuntimeError(f"exhausted retries downloading {path}")


def decode_book_rows(raw: bytes) -> list[dict[str, Any]]:
    """zstd-compressed parquet bytes -> row dicts with price/quantity cast to
    float and a `ts` (ISO8601 UTC) column derived from event_time.

    Decompression uses pyarrow's own bundled zstd codec
    (`pa.input_stream(..., compression="zstd")`) — no extra dependency
    beyond the `collector` group's pyarrow, and the parquet library itself
    needs a seekable, fully-materialized buffer, so the whole hour is
    decompressed into memory before pq.read_table (hourly files are tens of
    MB, not a streaming-scale concern here).
    """
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    stream = pa.input_stream(pa.py_buffer(raw), compression="zstd")
    table = pq.read_table(io.BytesIO(stream.read()))
    table = table.set_column(
        table.schema.get_field_index("price"), "price", pc.cast(table["price"], pa.float64())
    )
    table = table.set_column(
        table.schema.get_field_index("quantity"),
        "quantity",
        pc.cast(table["quantity"], pa.float64()),
    )
    rows = table.to_pylist()
    for row in rows:
        ts = datetime.fromtimestamp(row["event_time"] / 1_000_000_000, tz=UTC)
        row["ts"] = ts.isoformat().replace("+00:00", "Z")
    return rows


# --------------------------------------------------------------------------
# Write — one atomic file per hour, layout mirrors collector_core's own
# (stream-<HH>.parquet under <base>/<exchange>/<PAIR>/<date>/), but written
# whole rather than through PartitionedParquetSink's row-buffering: a vendor
# hour arrives as one complete table, not a stream of live events, so there
# is nothing for part-file crash-safety to protect — a single tmp-then-
# rename write (the same technique collector_core.compact_hour uses to merge
# parts) gives the same guarantee with one file instead of hundreds.
# --------------------------------------------------------------------------


def out_dir(base_dir: Path, exchange: str, pair: str, hour: datetime) -> Path:
    return (
        base_dir / "backfill" / "chd" / exchange / symbol_dirname(pair) / hour.strftime("%Y-%m-%d")
    )


def out_file(base_dir: Path, exchange: str, pair: str, datatype: str, hour: datetime) -> Path:
    return out_dir(base_dir, exchange, pair, hour) / f"{datatype}-{hour:%H}.parquet"


def write_hour(
    base_dir: Path,
    exchange: str,
    pair: str,
    datatype: str,
    hour: datetime,
    rows: list[dict[str, Any]],
) -> bool:
    """Write one hourly parquet. Returns False (no write) if the file
    already exists — resumable/idempotent, never overwrites."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = out_file(base_dir, exchange, pair, datatype, hour)
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    pq.write_table(pa.Table.from_pylist(rows), tmp, compression="zstd", compression_level=3)
    tmp.replace(path)
    return True


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def run_backfill(
    exchange: str,
    pairs: list[str],
    datatype: str,
    missing: dict[str, list[datetime]],
    base_dir: Path,
    api_key: str,
    concurrency: int,
) -> dict[str, dict[str, int]]:
    auth = ChdAuth(api_key)
    stats: dict[str, dict[str, int]] = {}
    with httpx.Client() as client:
        known_symbols = fetch_symbols(client, exchange)
        for pair in pairs:
            hours = missing.get(pair, [])
            if not hours:
                continue
            sym = chd_symbol(pair)
            if sym not in known_symbols:
                print(f"WARN: {sym} not in {exchange}/symbols — skipping (would 404)")
                continue
            written_hours = written_rows = skipped_404 = skipped_existing = 0
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = {
                    pool.submit(download_hour, client, auth, exchange, pair, datatype, h): h
                    for h in hours
                    if not out_file(base_dir, exchange, pair, datatype, h).exists()
                }
                skipped_existing = len(hours) - len(futures)
                for fut in as_completed(futures):
                    hour = futures[fut]
                    result = fut.result()
                    if result.raw is None:
                        skipped_404 += 1
                        p = download_path(exchange, pair, datatype, hour)
                        print(f"  {p}: 404 (not published / absent)")
                        continue
                    rows = decode_book_rows(result.raw)
                    if write_hour(base_dir, exchange, pair, datatype, hour, rows):
                        written_hours += 1
                        written_rows += len(rows)
            print(
                f"{pair}: {written_hours} hours written ({written_rows} rows), "
                f"{skipped_existing} already present, {skipped_404} not published"
            )
            stats[pair] = {
                "hours_written": written_hours,
                "rows_written": written_rows,
                "skipped_existing": skipped_existing,
                "skipped_404": skipped_404,
            }
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--exchange", default="kraken_spot")
    parser.add_argument("--pair", action="append", help="e.g. BTC/USD; repeatable")
    parser.add_argument("--datatype", default="orderbook", choices=sorted(ALLOWED_DATATYPES))
    parser.add_argument(
        "--start", type=str, default=None, help="ISO date/hour, e.g. 2026-07-28 or 2026-07-28T12"
    )
    parser.add_argument("--end", type=str, default=None, help="ISO date/hour, exclusive")
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="inventory + size estimate only (default: on — pass --no-dry-run to write)",
    )
    parser.add_argument("--max-hours", type=int, default=None, help="cap fetched hours per pair")
    parser.add_argument("--yes", action="store_true", help="skip the size confirmation")
    parser.add_argument("--concurrency", type=int, default=MAX_CONCURRENCY)
    parser.add_argument(
        "--base-dir", type=Path, default=None, help="override output root (default: data root)"
    )
    args = parser.parse_args()

    if args.datatype in KNOWN_BROKEN_DATATYPES:
        raise SystemExit(
            f"refusing: datatype '{args.datatype}' is advertised but 404s on every exchange tested"
        )

    def parse_bound(s: str | None) -> datetime | None:
        if s is None:
            return None
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)

    start = parse_bound(args.start)
    end = parse_bound(args.end)
    if start is not None and start < HISTORY_FLOOR:
        raise SystemExit(
            f"refusing: --start {start:%Y-%m-%d %H:%M} is before HISTORY_FLOOR "
            f"{HISTORY_FLOOR:%Y-%m-%d} — cryptohftdata has no history before this date "
            f"on any exchange tested; that gap is permanently unfillable via this tool"
        )

    if args.pair:
        pairs = args.pair
    elif args.exchange in ARCHIVE_MAP:
        import collect_ticks as ct  # local archive default only exists for kraken_spot today

        pairs = ct.GREENLIST_PAIRS
    else:
        raise SystemExit(f"--pair is required: no default pair list for exchange '{args.exchange}'")

    if local_archive_dir(args.exchange) is None and (start is None or end is None):
        raise SystemExit(
            f"--start and --end are required: no local archive mapping for exchange "
            f"'{args.exchange}' to gap-scan against (known: {sorted(ARCHIVE_MAP)})"
        )

    missing = gap_report(args.exchange, pairs, args.datatype, start, end)
    if args.max_hours is not None:
        missing = {p: h[: args.max_hours] for p, h in missing.items()}

    total_hours = sum(len(h) for h in missing.values())
    est_mb, measured = estimate_mb(args.exchange, args.datatype, total_hours)
    tag = "" if measured else " (UNMEASURED — conservative default, could be off)"
    print(f"\ntotal missing hours: {total_hours}   estimated size: {est_mb:.1f} MB{tag}")

    if args.dry_run:
        print("dry run — no writes (pass --no-dry-run to fetch)")
        return

    if total_hours == 0:
        print("nothing to fetch")
        return

    if est_mb >= SIZE_CONFIRM_MB and not args.yes:
        reply = input(f"about to download ~{est_mb:.1f} MB — proceed? [y/N] ").strip().lower()
        if reply != "y":
            print("aborted")
            return

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    api_key = os.environ.get("CRYPTOHFTDATA_API_KEY")
    if not api_key:
        raise SystemExit(
            "CRYPTOHFTDATA_API_KEY missing from the environment — it lives in the repo .env"
        )

    base_dir = args.base_dir or resolve_data_root()
    concurrency = min(args.concurrency, MAX_CONCURRENCY)
    run_backfill(args.exchange, pairs, args.datatype, missing, base_dir, api_key, concurrency)


if __name__ == "__main__":
    main()
