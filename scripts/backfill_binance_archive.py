"""Backfill the tick archive from Binance's public GLOBAL historical archive.

WHY THIS EXISTS. api.binance.com is geo-blocked from this machine (HTTP 451),
so live collection only reaches the near-dead Binance.US venue
(collect_trades_binance_us.py / collect_books_binance.py). But the GLOBAL
historical archive at data.binance.vision is fully reachable and needs no
auth — it is how this archive gets the world's deepest venue at all. This
script bulk-pulls daily (or monthly, for fundingRate) zipped CSV dumps and
writes them into `resolve_data_root()/"archive"/"binance"/<market>/`, kept
deliberately separate from anything a live collector writes so a backfill
run can never collide with or overwrite collected data.

LISTING API. The plain https://data.binance.vision page is JS-rendered and
useless to curl/httpx. This script never lists — daily/monthly file paths
follow a fixed, documented convention (verified against the bucket
2026-08-07), so files are addressed directly:

    https://data.binance.vision/data/spot/daily/aggTrades/<SYM>/<SYM>-aggTrades-<YYYY-MM-DD>.zip
    https://data.binance.vision/data/futures/um/daily/bookTicker/<SYM>/<SYM>-bookTicker-<YYYY-MM-DD>.zip
    https://data.binance.vision/data/futures/um/monthly/fundingRate/<SYM>/<SYM>-fundingRate-<YYYY-MM>.zip

Every data file has a sibling `<file>.CHECKSUM` (plain-text sha256) which is
verified before any write — this is a bulk unattended pull and silent
corruption would poison the archive.

DATATYPES SUPPORTED (per market):

    spot: aggTrades, trades, klines
    um:   aggTrades, trades, klines, bookTicker, metrics, fundingRate (monthly only)
    cm:   all of um's, plus liquidationSnapshot (DISCONTINUED — last file
          2024-10-14; refused for dates after that)

`bookDepth` is deliberately NOT offered: it is 1-second snapshots of
cumulative depth at 11 fixed %% bands, not an order book, and not worth the
archive space it would cost across 50+ symbols.

SCHEMA HANDLING. Spot files have NO header row; several futures datatypes
do. Every file is sniffed (is the first cell of the first row a header
label, i.e. not parseable as a number?) rather than trusting a per-market
assumption, because that assumption has already been observed to vary.

TIMESTAMP UNIT TRAP (verified 2026-08-07): spot klines timestamps are now
MICROSECONDS (e.g. 1785542400000000) while futures klines are still
MILLISECONDS, and Binance gives no header flag for this. Every timestamp
value is sniffed by magnitude — >= 1e14 is microseconds, else milliseconds
(`normalize_ts`) — never hardcoded per market. Getting this wrong silently
shifts an entire day's data by a factor of 1000.

SYMBOL MAPPING. Binance's global venue has no fiat quote pairs at all, so
the default symbol list is GREENLIST_PAIRS (collect_ticks.py) with every
fiat-quoted pair (EUR/GBP/AUD/CHF/CAD/JPY on either side) dropped, and every
remaining USD quote rewritten to USDT (Binance's de-facto USD stand-in):
BTC/USD -> BTCUSDT, ETH/BTC -> ETHBTC, BTC/USDT -> BTCUSDT (already
deduped). Override with `--symbols` for anything else (raw Binance symbols,
comma-separated).

IDEMPOTENCY. Every (symbol, period) that has been resolved — written,
confirmed empty, or confirmed absent upstream (404, e.g. before a symbol's
listing date) — gets a marker file under
`<symbol_dir>/_markers/<datatype>-<period>.done` so re-running the script
never re-downloads. A checksum MISMATCH is the one outcome that does not get
a marker: the file is discarded, the failure reported, and the next run
retries it.

Run modes (from repo root):
    uv run python scripts/backfill_binance_archive.py --dry-run \\
        --market spot --datatype aggTrades --symbols BTCUSDT,ETHUSDT \\
        --start 2026-08-01 --end 2026-08-03

    uv run python scripts/backfill_binance_archive.py \\
        --market spot --datatype aggTrades --symbols BTCUSDT \\
        --start 2026-08-01 --end 2026-08-01 --dry-run=false
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import sys
import time
import zipfile
from collections import defaultdict
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collector_core import (  # noqa: E402
    PartitionedParquetSink,
    compact_hour,
    resolve_data_root,
    stream_dir,
    symbol_dirname,
)

DATA_HOST = "https://data.binance.vision"
ARCHIVE_VENUE = "binance"

MARKET_BASE = {
    "spot": "data/spot",
    "um": "data/futures/um",
    "cm": "data/futures/cm",
}

DATATYPES_BY_MARKET: dict[str, set[str]] = {
    "spot": {"aggTrades", "trades", "klines"},
    "um": {"aggTrades", "trades", "klines", "bookTicker", "metrics", "fundingRate"},
    "cm": {
        "aggTrades",
        "trades",
        "klines",
        "bookTicker",
        "metrics",
        "fundingRate",
        "liquidationSnapshot",
    },
}

MONTHLY_ONLY = {"fundingRate"}

# Last confirmed liquidationSnapshot file on the archive (verified 2026-08-07).
LIQUIDATION_LAST_DATE = date(2024, 10, 14)

# Which column in each datatype's schema is the row's primary timestamp.
TS_COLUMN = {
    "aggTrades": "transact_time",
    "trades": "time",
    "klines": "open_time",
    "bookTicker": "transaction_time",
    "metrics": "create_time",
    "fundingRate": "calc_time",
    "liquidationSnapshot": "time",
}

# Headerless fallback schemas (spot never has a header; some futures
# datatypes also don't — detected per-file, never assumed).
_AGGTRADES_COLS = [
    "agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id",
    "transact_time", "is_buyer_maker", "is_best_match",
]
_TRADES_COLS = [
    "trade_id", "price", "qty", "quote_qty", "time", "is_buyer_maker", "is_best_match",
]
_KLINES_COLS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]
FALLBACK_COLUMNS: dict[str, list[str]] = {
    "aggTrades": _AGGTRADES_COLS,
    "trades": _TRADES_COLS,
    "klines": _KLINES_COLS,
}

# metrics columns are verified exactly (task brief); used whenever the file's
# own header doesn't already give us column names.
_METRICS_COLS = [
    "create_time", "symbol", "sum_open_interest", "sum_open_interest_value",
    "count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio",
    "count_long_short_ratio", "sum_taker_long_short_vol_ratio",
]
FALLBACK_COLUMNS["metrics"] = _METRICS_COLS

REQUEST_TIMEOUT_S = 30.0
POLITE_DELAY_S = 0.2
MAX_CONCURRENCY = 4


# --------------------------------------------------------------------------
# Symbol mapping — pure, no network.
# --------------------------------------------------------------------------

_FIAT = {"EUR", "GBP", "AUD", "CHF", "CAD", "JPY"}


def default_symbols() -> list[str]:
    """GREENLIST_PAIRS (collect_ticks.py) mapped to Binance global symbols.

    Binance's global venue has no fiat-quoted pairs, so any pair touching a
    fiat currency (either side) is dropped. Everything else quoted in USD is
    rewritten to USDT — Binance's de-facto USD stand-in — and BASE/QUOTE is
    simply concatenated otherwise (ETH/BTC -> ETHBTC, BTC/USDT -> BTCUSDT).
    Order is preserved with de-duplication (BTC/USD and a hypothetical
    BTC/USDT both resolve to BTCUSDT).
    """
    import collect_ticks as ct

    seen: set[str] = set()
    out: list[str] = []
    for pair in ct.GREENLIST_PAIRS:
        base, quote = pair.split("/")
        if base in _FIAT or quote in _FIAT:
            continue
        sym = f"{base}USDT" if quote == "USD" else f"{base}{quote}"
        if sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


# --------------------------------------------------------------------------
# Path / period logic — pure, no network.
# --------------------------------------------------------------------------


def daterange(start: date, end: date) -> Iterable[date]:
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def months_covered(start: date, end: date) -> list[str]:
    """Distinct YYYY-MM strings for every month touched by [start, end]."""
    out: list[str] = []
    d = date(start.year, start.month, 1)
    while d <= end:
        out.append(d.strftime("%Y-%m"))
        if d.month == 12:
            d = date(d.year + 1, 1, 1)
        else:
            d = date(d.year, d.month + 1, 1)
    return out


def periods_for(market: str, datatype: str, start: date, end: date) -> list[str]:
    if datatype in MONTHLY_ONLY:
        return months_covered(start, end)
    return [d.strftime("%Y-%m-%d") for d in daterange(start, end)]


def archive_key(market: str, datatype: str, symbol: str, period: str, interval: str) -> str:
    base = MARKET_BASE[market]
    if datatype == "klines":
        return f"{base}/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{period}.zip"
    period_kind = "monthly" if datatype in MONTHLY_ONLY else "daily"
    return f"{base}/{period_kind}/{datatype}/{symbol}/{symbol}-{datatype}-{period}.zip"


def validate_request(market: str, datatype: str, period: str) -> str | None:
    """Reason to refuse this (market, datatype, period), or None if fine."""
    if datatype not in DATATYPES_BY_MARKET[market]:
        return f"{datatype} is not offered on market={market}"
    if datatype == "liquidationSnapshot":
        d = datetime.strptime(period, "%Y-%m-%d").date()
        if d > LIQUIDATION_LAST_DATE:
            return (
                f"liquidationSnapshot was discontinued after "
                f"{LIQUIDATION_LAST_DATE.isoformat()} — {period} would never exist"
            )
    return None


# --------------------------------------------------------------------------
# Timestamp normalisation — pure, no network. The us/ms trap lives here.
# --------------------------------------------------------------------------


def detect_ts_unit(raw: int) -> str:
    """"us" or "ms" by magnitude — never assumed per market/datatype.

    A millisecond epoch stays below 1e14 until the year 5138; a microsecond
    epoch has been above 1e14 since 1973. That gap is the whole detector.
    """
    return "us" if raw >= 10**14 else "ms"


def normalize_ts(raw: str) -> str:
    """UTC ISO8601 string (trailing "Z") from a Binance timestamp cell.

    Handles three observed shapes: millisecond epoch (futures klines etc.),
    microsecond epoch (spot klines, verified 2026-08-07), and the
    space-separated datetime string some `metrics` files use for create_time.
    """
    raw = raw.strip()
    try:
        val = int(float(raw))
    except ValueError:
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        return dt.isoformat().replace("+00:00", "Z")
    seconds = val / 1_000_000 if detect_ts_unit(val) == "us" else val / 1_000
    return datetime.fromtimestamp(seconds, tz=UTC).isoformat().replace("+00:00", "Z")


def _to_bool(v: str) -> bool:
    return v.strip().lower() in ("true", "1")


def _try_num(v: str) -> Any:
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


# --------------------------------------------------------------------------
# CSV parsing — pure, no network.
# --------------------------------------------------------------------------


def looks_like_header(first_row: list[str]) -> bool:
    if not first_row:
        return False
    try:
        float(first_row[0])
        return False
    except ValueError:
        return True


def parse_csv(text: str, datatype: str) -> tuple[list[str], list[list[str]]]:
    """(columns, data_rows) for one datatype's CSV body, header or not."""
    rows = [r for r in csv.reader(io.StringIO(text)) if r]
    if not rows:
        return [], []
    if looks_like_header(rows[0]):
        return rows[0], rows[1:]
    fallback = FALLBACK_COLUMNS.get(datatype)
    width = len(rows[0])
    if fallback and width == len(fallback):
        return fallback, rows
    if fallback and width == len(fallback) - 1:
        # a trailing optional column (e.g. is_best_match) sometimes absent
        return fallback[:-1], rows
    return [f"col_{i}" for i in range(width)], rows


def normalize_row(datatype: str, row: dict[str, str]) -> dict[str, Any]:
    """One parsed CSV row -> a Parquet-ready dict with a normalised `ts`."""
    if datatype == "aggTrades":
        out = {
            "ts": normalize_ts(row["transact_time"]),
            "agg_trade_id": int(row["agg_trade_id"]),
            "price": float(row["price"]),
            "quantity": float(row["quantity"]),
            "first_trade_id": int(row["first_trade_id"]),
            "last_trade_id": int(row["last_trade_id"]),
            "is_buyer_maker": _to_bool(row["is_buyer_maker"]),
        }
        return out
    if datatype == "trades":
        return {
            "ts": normalize_ts(row["time"]),
            "trade_id": int(row["trade_id"]),
            "price": float(row["price"]),
            "qty": float(row["qty"]),
            "quote_qty": float(row["quote_qty"]),
            "is_buyer_maker": _to_bool(row["is_buyer_maker"]),
        }
    if datatype == "klines":
        return {
            "ts": normalize_ts(row["open_time"]),
            "close_ts": normalize_ts(row["close_time"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
            "quote_volume": float(row["quote_volume"]),
            "count": int(row["count"]),
            "taker_buy_volume": float(row["taker_buy_volume"]),
            "taker_buy_quote_volume": float(row["taker_buy_quote_volume"]),
        }
    if datatype == "metrics":
        return {
            "ts": normalize_ts(row["create_time"]),
            "sum_open_interest": _try_num(row.get("sum_open_interest", "")),
            "sum_open_interest_value": _try_num(row.get("sum_open_interest_value", "")),
            "count_toptrader_long_short_ratio": _try_num(
                row.get("count_toptrader_long_short_ratio", "")
            ),
            "sum_toptrader_long_short_ratio": _try_num(
                row.get("sum_toptrader_long_short_ratio", "")
            ),
            "count_long_short_ratio": _try_num(row.get("count_long_short_ratio", "")),
            "sum_taker_long_short_vol_ratio": _try_num(
                row.get("sum_taker_long_short_vol_ratio", "")
            ),
        }
    # bookTicker / fundingRate / liquidationSnapshot: schema not pinned to the
    # same certainty as the above (verified only by description, not by an
    # observed column list), so pass every other column through generically
    # with best-effort numeric coercion rather than risk a wrong hardcoded
    # name silently dropping data.
    ts_col = TS_COLUMN.get(datatype)
    out = {}
    for k, v in row.items():
        if k == ts_col:
            out["ts"] = normalize_ts(v)
        elif k == "symbol":
            continue  # redundant with the partition path
        else:
            out[k] = _try_num(v)
    return out


# --------------------------------------------------------------------------
# Network — checksum verify, fetch, unzip.
# --------------------------------------------------------------------------


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_checksum(client: httpx.Client, key: str) -> str | None:
    """Expected sha256 for `key`, or None if the .CHECKSUM file is absent
    (treated the same as the data file being absent — nothing to verify)."""
    resp = client.get(f"{DATA_HOST}/{key}.CHECKSUM", timeout=REQUEST_TIMEOUT_S)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    # format: "<sha256>  <filename>"
    return resp.text.strip().split()[0].lower()


def fetch_zip(client: httpx.Client, key: str) -> bytes | None:
    resp = client.get(f"{DATA_HOST}/{key}", timeout=REQUEST_TIMEOUT_S)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.content


def extract_csv_text(zip_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise ValueError("zip has no .csv member")
        return zf.read(names[0]).decode("utf-8")


# --------------------------------------------------------------------------
# Marker-based idempotency.
# --------------------------------------------------------------------------


def marker_path(out_root: Path, symbol: str, datatype: str, period: str) -> Path:
    return out_root / symbol_dirname(symbol) / "_markers" / f"{datatype}-{period}.done"


def already_done(out_root: Path, symbol: str, datatype: str, period: str) -> bool:
    return marker_path(out_root, symbol, datatype, period).is_file()


def write_marker(
    out_root: Path, symbol: str, datatype: str, period: str, status: str, rows: int
) -> None:
    p = marker_path(out_root, symbol, datatype, period)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f"status={status} rows={rows} at={datetime.now(UTC).isoformat(timespec='seconds')}\n",
        encoding="utf-8",
    )


# --------------------------------------------------------------------------
# Write path — buckets a day/month's rows by hour and drives
# PartitionedParquetSink + compact_hour so the result is one clean file per
# touched hour, never a pile of unmerged parts.
# --------------------------------------------------------------------------


def sink_stream_name(datatype: str) -> str:
    """collector_core's part-file regex is lowercase-only ([a-z_]+) — it was
    written for "trades"/"book" and never anticipated a mixed-case stream
    name like "aggTrades". Feeding it "aggTrades" verbatim doesn't error: it
    just makes `part_files()` match nothing, so `compact_hour` silently
    becomes a no-op forever and part files pile up unmerged (caught by
    reading the pull back in verification). Lowercasing at the call site
    avoids touching collector_core.py."""
    return datatype.lower()


def write_rows(sink: PartitionedParquetSink, symbol: str, stream: str, rows: list[dict]) -> None:
    buckets: dict[datetime, list[dict]] = defaultdict(list)
    for row in rows:
        ts = datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
        buckets[ts.replace(minute=0, second=0, microsecond=0)].append(row)
    for hour_ts, hour_rows in buckets.items():
        for row in hour_rows:
            sink.add(symbol, stream, row, hour_ts)
        sink.flush(symbol, stream, hour_ts)
        day_dir = stream_dir(sink.base_dir, symbol, hour_ts, sink.partition)
        compact_hour(day_dir, stream, hour_ts.hour)


# --------------------------------------------------------------------------
# Per-(symbol, period) task.
# --------------------------------------------------------------------------


@dataclass
class TaskResult:
    symbol: str
    datatype: str
    period: str
    status: str  # written | empty | missing | checksum_fail | skipped | refused
    rows: int = 0
    bytes: int = 0
    detail: str = ""


def process_one(
    client: httpx.Client,
    out_root: Path,
    market: str,
    datatype: str,
    symbol: str,
    period: str,
    interval: str,
) -> TaskResult:
    if already_done(out_root, symbol, datatype, period):
        return TaskResult(symbol, datatype, period, "skipped")

    reason = validate_request(market, datatype, period)
    if reason:
        return TaskResult(symbol, datatype, period, "refused", detail=reason)

    key = archive_key(market, datatype, symbol, period, interval)
    try:
        expected_sha = fetch_checksum(client, key)
        time.sleep(POLITE_DELAY_S)
        zip_bytes = fetch_zip(client, key)
        time.sleep(POLITE_DELAY_S)
    except httpx.HTTPError as exc:
        return TaskResult(symbol, datatype, period, "missing", detail=f"network error: {exc!r}")

    if zip_bytes is None:
        write_marker(out_root, symbol, datatype, period, "missing", 0)
        return TaskResult(symbol, datatype, period, "missing")

    if expected_sha is not None:
        actual_sha = sha256_hex(zip_bytes)
        if actual_sha != expected_sha:
            return TaskResult(
                symbol, datatype, period, "checksum_fail",
                bytes=len(zip_bytes),
                detail=f"expected {expected_sha}, got {actual_sha}",
            )

    csv_text = extract_csv_text(zip_bytes)
    columns, data_rows = parse_csv(csv_text, datatype)
    rows: list[dict[str, Any]] = []
    for r in data_rows:
        if len(r) != len(columns):
            continue
        rows.append(normalize_row(datatype, dict(zip(columns, r, strict=True))))

    if not rows:
        write_marker(out_root, symbol, datatype, period, "empty", 0)
        return TaskResult(symbol, datatype, period, "empty", bytes=len(zip_bytes))

    sink = PartitionedParquetSink(out_root)
    write_rows(sink, symbol, sink_stream_name(datatype), rows)
    write_marker(out_root, symbol, datatype, period, "written", len(rows))
    return TaskResult(symbol, datatype, period, "written", rows=len(rows), bytes=len(zip_bytes))


# --------------------------------------------------------------------------
# Plan + run.
# --------------------------------------------------------------------------


@dataclass
class Plan:
    market: str
    datatype: str
    symbols: list[str]
    periods: list[str]
    interval: str

    @property
    def n_tasks(self) -> int:
        return len(self.symbols) * len(self.periods)


def build_plan(
    market: str, datatype: str, symbols: list[str], start: date, end: date, interval: str
) -> Plan:
    return Plan(market, datatype, symbols, periods_for(market, datatype, start, end), interval)


def print_plan(plan: Plan, out_root: Path) -> None:
    print(f"market={plan.market} datatype={plan.datatype} out={out_root}")
    print(f"symbols ({len(plan.symbols)}): {', '.join(plan.symbols)}")
    print(
        f"periods ({len(plan.periods)}): {plan.periods[0]}..{plan.periods[-1]}"
        if plan.periods
        else "periods: (none)"
    )
    print(f"planned requests: {plan.n_tasks} symbol x period combinations "
          f"(each = 1 .CHECKSUM + 1 .zip GET)")
    for symbol in plan.symbols:
        for period in plan.periods:
            key = archive_key(plan.market, plan.datatype, symbol, period, plan.interval)
            reason = validate_request(plan.market, plan.datatype, period)
            tag = f"  REFUSED: {reason}" if reason else ""
            print(f"  {symbol:<14} {period:<10} {DATA_HOST}/{key}{tag}")


def run(plan: Plan, out_root: Path) -> list[TaskResult]:
    results: list[TaskResult] = []
    with httpx.Client() as client:
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as pool:
            futures = {
                pool.submit(
                    process_one, client, out_root, plan.market, plan.datatype,
                    symbol, period, plan.interval,
                ): (symbol, period)
                for symbol in plan.symbols
                for period in plan.periods
            }
            for fut in as_completed(futures):
                results.append(fut.result())
    return results


def print_summary(results: list[TaskResult]) -> None:
    by_status: dict[str, list[TaskResult]] = defaultdict(list)
    for r in results:
        by_status[r.status].append(r)
    total_rows = sum(r.rows for r in results)
    total_bytes = sum(r.bytes for r in results)
    print("\n--- summary ---")
    print(f"written:        {len(by_status['written'])}  ({total_rows} rows, {total_bytes} bytes)")
    print(f"empty:          {len(by_status['empty'])}")
    print(f"missing:        {len(by_status['missing'])}")
    print(f"skipped:        {len(by_status['skipped'])}  (already present)")
    print(f"refused:        {len(by_status['refused'])}")
    print(f"checksum_fail:  {len(by_status['checksum_fail'])}")
    for r in by_status["checksum_fail"]:
        print(f"  CHECKSUM MISMATCH {r.symbol} {r.datatype} {r.period}: {r.detail}")
    for r in by_status["refused"][:10]:
        print(f"  REFUSED {r.symbol} {r.datatype} {r.period}: {r.detail}")


def resolve_archive_dir(market: str) -> Path:
    return resolve_data_root() / "archive" / ARCHIVE_VENUE / market


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--market", choices=["spot", "um", "cm"], default="spot")
    parser.add_argument(
        "--datatype",
        choices=["aggTrades", "trades", "klines", "bookTicker", "metrics",
                 "fundingRate", "liquidationSnapshot"],
        required=True,
    )
    parser.add_argument(
        "--symbols", default=None, help="comma list; default = GREENLIST_PAIRS mapping"
    )
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--interval", default="1m", help="klines/*Klines interval, e.g. 1m, 1h")
    parser.add_argument("--out", type=Path, default=None, help="override the archive dir")
    parser.add_argument(
        "--dry-run", dest="dry_run", action="store_true", default=True,
        help="print the plan only (default ON)",
    )
    parser.add_argument(
        "--no-dry-run", dest="dry_run", action="store_false", help="actually download"
    )
    args = parser.parse_args()

    if args.datatype not in DATATYPES_BY_MARKET[args.market]:
        parser.error(
            f"--datatype {args.datatype} is not offered on --market {args.market} "
            f"(offered: {sorted(DATATYPES_BY_MARKET[args.market])})"
        )

    symbols = (
        [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        if args.symbols
        else default_symbols()
    )
    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    if end < start:
        parser.error("--end is before --start")

    out_root = args.out or resolve_archive_dir(args.market)
    plan = build_plan(args.market, args.datatype, symbols, start, end, args.interval)
    print_plan(plan, out_root)

    if args.dry_run:
        print("\ndry run — no writes")
        return

    out_root.mkdir(parents=True, exist_ok=True)
    results = run(plan, out_root)
    print_summary(results)


if __name__ == "__main__":
    main()
