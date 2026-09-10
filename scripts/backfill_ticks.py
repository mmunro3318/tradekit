"""Backfill TRADE gaps in the tick archive from Kraken's public REST API.

The WS collector (scripts/collect_ticks.py) has died repeatedly, leaving
multi-hour holes in `<base>/<PAIR>/<YYYY-MM-DD>/trades-<HH>.parquet`.
Book depth cannot be backfilled (no historical order-book endpoint);
trades can, via GET https://api.kraken.com/0/public/Trades (1000 trades
per call, `last` cursor pagination, ~1 req/s politeness).

Backfilled files use the SAME layout and schema as collect_ticks trades
files: ts (ISO8601 UTC str), price (float), qty (float), side
("buy"/"sell"), ord_type ("market"/"limit"). Existing hourly files are
NEVER touched — collected data wins; a missing hour is only filled when
no trades-<HH>.parquet exists for it. Book files are never written.

Run modes (from repo root):
    uv run python scripts/backfill_ticks.py --dry-run           # inventory only
    uv run python scripts/backfill_ticks.py --pair ETH/USD      # one pair
    uv run python scripts/backfill_ticks.py                     # full backfill
"""

from __future__ import annotations

import argparse
import re
import sys
import time as _time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

sys.path.insert(0, str(Path(__file__).resolve().parent))

import collect_ticks as ct  # noqa: E402

REST_TRADES_URL = "https://api.kraken.com/0/public/Trades"
REQUEST_INTERVAL_S = 1.1
RATE_LIMIT_BACKOFF_S = 10.0

_SIDE = {"b": "buy", "s": "sell"}
_ORD_TYPE = {"m": "market", "l": "limit"}

# A present hour is either the compacted file or one of its pre-compaction
# append-only fragments (see docs/ARCHIVE-README.md "path grammar"); both
# are valid, self-contained parquet. Anchored on the whole stem so e.g. a
# quarantined "trades-05.parquet.corrupt-no-footer" (stem
# "trades-05.parquet") or a ".tmp" file never matches.
_HOUR_STEM_RE = {
    "trades": re.compile(r"^trades-(\d{2})(?:\.part-\d+)?$"),
    "book": re.compile(r"^book-(\d{2})(?:\.part-\d+)?$"),
}

# Any fixed UTC datetime works here: passed to ct.stream_dir only to pick a
# day segment, which callers immediately strip with `.parent` to recover
# the pair directory (asset-class partitioned or not, per collector_core).
_LAYOUT_PROBE_TS = datetime(1970, 1, 1, tzinfo=UTC)


# --------------------------------------------------------------------------
# Pure logic — no network, exercised directly by unit tests.
# --------------------------------------------------------------------------


def floor_hour(ts: datetime) -> datetime:
    return ts.replace(minute=0, second=0, microsecond=0)


def _present_hours_in_dir(date_dir: Path, stream: str) -> set[int]:
    """Hours (0-23) that have any present-form file for `stream`
    ("trades" or "book") in one day directory — compacted or fragment."""
    pattern = _HOUR_STEM_RE[stream]
    hours: set[int] = set()
    for f in date_dir.glob(f"{stream}-*.parquet"):
        m = pattern.match(f.stem)
        if m:
            hours.add(int(m.group(1)))
    return hours


def hour_is_present(date_dir: Path, stream: str, hh: int) -> bool:
    """True when hour `hh` of `stream` already has a present-form file
    (compacted or fragment) in `date_dir`."""
    return hh in _present_hours_in_dir(date_dir, stream)


def present_trade_hours(base_dir: Path, pair: str) -> set[datetime]:
    """Hours (UTC datetimes, floored) that have a present-form trades file."""
    # Same layout helper the writer uses (ct.trade_file_path -> stream_dir),
    # never a private path join — readers and writer must never disagree
    # about where a pair lives. The ts only selects a day segment, stripped
    # by .parent; any fixed UTC datetime works.
    pair_dir = ct.stream_dir(base_dir, pair, _LAYOUT_PROBE_TS).parent
    hours: set[datetime] = set()
    if not pair_dir.is_dir():
        return hours
    for date_dir in pair_dir.iterdir():
        if not date_dir.is_dir():
            continue
        try:
            day = datetime.strptime(date_dir.name, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            continue
        for hh in _present_hours_in_dir(date_dir, "trades"):
            hours.add(day + timedelta(hours=hh))
    return hours


def earliest_book_hour(base_dir: Path, pair: str) -> datetime | None:
    """Earliest present-form book hour for a pair, or None. Anchor fallback
    (CTO adjudication 2026-07-26) for pairs that collected book data but
    never any trades: their trade backfill starts where book collection
    proves the collector was first alive for the pair."""
    pair_dir = ct.stream_dir(base_dir, pair, _LAYOUT_PROBE_TS).parent
    earliest: datetime | None = None
    if not pair_dir.is_dir():
        return None
    for date_dir in pair_dir.iterdir():
        if not date_dir.is_dir():
            continue
        try:
            day = datetime.strptime(date_dir.name, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            continue
        for hh in _present_hours_in_dir(date_dir, "book"):
            hour = day + timedelta(hours=hh)
            if earliest is None or hour < earliest:
                earliest = hour
    return earliest


def missing_hours(present: set[datetime], now: datetime) -> list[datetime]:
    """Hours absent between the first collected hour and `now` (the
    current, still-in-progress hour is excluded)."""
    if not present:
        return []
    cur = min(present)
    end = floor_hour(now)
    out: list[datetime] = []
    while cur < end:
        if cur not in present:
            out.append(cur)
        cur += timedelta(hours=1)
    return out


def gap_spans(missing: list[datetime]) -> list[tuple[datetime, datetime]]:
    """Contiguous (start_hour, end_hour_inclusive) spans from a sorted
    list of missing hours."""
    spans: list[tuple[datetime, datetime]] = []
    for h in missing:
        if spans and h == spans[-1][1] + timedelta(hours=1):
            spans[-1] = (spans[-1][0], h)
        else:
            spans.append((h, h))
    return spans


def rest_trade_to_row(t: list[Any]) -> dict[str, Any]:
    """Kraken REST trade tuple [price, volume, time, b/s, m/l, misc, ...]
    -> collect_ticks trades schema row."""
    ts = datetime.fromtimestamp(float(t[2]), tz=UTC)
    return {
        "ts": ts.isoformat().replace("+00:00", "Z"),
        "price": float(t[0]),
        "qty": float(t[1]),
        "side": _SIDE[t[3]],
        "ord_type": _ORD_TYPE[t[4]],
    }


def parse_trades_response(body: dict[str, Any], altname: str) -> tuple[list[dict[str, Any]], str]:
    """(rows, last_cursor) from a REST Trades response body. Raises
    RuntimeError on API-level errors so callers can back off."""
    if body.get("error"):
        raise RuntimeError(f"Kraken API error: {body['error']}")
    result = body["result"]
    last = str(result["last"])
    # result holds exactly one pair key besides "last"; match altname
    # but tolerate Kraken returning a canonical alias (e.g. XXRPZUSD).
    key = altname if altname in result else next(k for k in result if k != "last")
    return [rest_trade_to_row(t) for t in result[key]], last


def bucket_rows_by_hour(rows: list[dict[str, Any]]) -> dict[datetime, list[dict[str, Any]]]:
    buckets: dict[datetime, list[dict[str, Any]]] = {}
    for row in rows:
        ts = datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
        buckets.setdefault(floor_hour(ts), []).append(row)
    return buckets


def write_hour(base_dir: Path, pair: str, hour: datetime, rows: list[dict[str, Any]]) -> bool:
    """Write one hourly trades parquet. Returns False (no write) when the
    file already exists — collected data always wins."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = ct.trade_file_path(base_dir, pair, hour)
    if path.parent.is_dir() and hour_is_present(path.parent, "trades", hour.hour):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)
    return True


# --------------------------------------------------------------------------
# Inventory
# --------------------------------------------------------------------------


def inventory(
    base_dir: Path, pairs: list[str] | None = None, now: datetime | None = None
) -> dict[str, dict[str, Any]]:
    """Per-pair gap report; prints a compact summary table."""
    pairs = pairs or ct.GREENLIST_PAIRS
    now = now or datetime.now(UTC)
    report: dict[str, dict[str, Any]] = {}
    print(f"{'pair':<12} {'first hour':<17} {'last hour':<17} {'have':>5} {'miss':>5}  largest gap")
    for pair in pairs:
        present = present_trade_hours(base_dir, pair)
        if not present:
            anchor = earliest_book_hour(base_dir, pair)
            if anchor is None:
                print(f"{pair:<12} (no data)")
                report[pair] = {"present": present, "missing": [], "spans": []}
                continue
            # No trades ever collected — anchor on the earliest book hour
            # (proof of collector liveness) and treat every hour since as
            # missing. `missing_hours` needs a non-empty present set, so
            # seed it with the anchor; the anchor hour itself still counts
            # as missing (no trades file exists for it).
            miss = [anchor, *missing_hours({anchor}, now)]
        else:
            miss = missing_hours(present, now)
        spans = gap_spans(miss)
        largest = max(spans, key=lambda s: (s[1] - s[0]), default=None)
        largest_str = (
            f"{largest[0]:%Y-%m-%d %H}h..{largest[1]:%Y-%m-%d %H}h "
            f"({int((largest[1] - largest[0]).total_seconds() // 3600) + 1}h)"
            if largest
            else "-"
        )
        first = min(present) if present else min(miss)
        last = max(present) if present else max(miss)
        tag = "" if present else " (book-anchored)"
        print(
            f"{pair:<12} {first:%Y-%m-%d %H}h   {last:%Y-%m-%d %H}h  "
            f"{len(present):>5} {len(miss):>5}  {largest_str}{tag}"
        )
        report[pair] = {"present": present, "missing": miss, "spans": spans}
    return report


# --------------------------------------------------------------------------
# REST backfill
# --------------------------------------------------------------------------


def resolve_altnames(pairs: list[str], timeout: float = 15.0) -> dict[str, str]:
    """wsname -> altname via the AssetPairs endpoint (resolved once)."""
    resp = httpx.get(ct.REST_ASSET_PAIRS_URL, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    if body.get("error"):
        raise RuntimeError(f"AssetPairs error: {body['error']}")
    mapping = {
        info["wsname"]: info["altname"]
        for info in body["result"].values()
        if info.get("wsname") in pairs
    }
    unknown = [p for p in pairs if p not in mapping]
    if unknown:
        print(f"WARN: no altname for {unknown} — skipping those pairs")
    return mapping


def fetch_trades(altname: str, since_ns: int, timeout: float = 30.0) -> dict[str, Any]:
    while True:
        resp = httpx.get(
            REST_TRADES_URL, params={"pair": altname, "since": str(since_ns)}, timeout=timeout
        )
        resp.raise_for_status()
        body: dict[str, Any] = resp.json()
        errs = body.get("error") or []
        if any("Rate limit" in e or "Too many" in e for e in errs):
            print(f"  rate limited; sleeping {RATE_LIMIT_BACKOFF_S}s")
            _time.sleep(RATE_LIMIT_BACKOFF_S)
            continue
        return body


def backfill_span(
    base_dir: Path,
    pair: str,
    altname: str,
    span: tuple[datetime, datetime],
    missing: set[datetime],
) -> tuple[int, int]:
    """Page REST trades across one contiguous gap span; write each missing
    hour's rows. Returns (hours_written, rows_written)."""
    start, end = span
    end_exclusive = end + timedelta(hours=1)
    since_ns = int(start.timestamp() * 1_000_000_000)
    end_ns = int(end_exclusive.timestamp() * 1_000_000_000)
    pending: dict[datetime, list[dict[str, Any]]] = {}
    n_req = 0
    while since_ns < end_ns:
        body = fetch_trades(altname, since_ns)
        rows, last = parse_trades_response(body, altname)
        n_req += 1
        for hour, hrows in bucket_rows_by_hour(rows).items():
            if hour in missing:
                pending.setdefault(hour, []).extend(hrows)
        new_since = int(last)
        if new_since <= since_ns or not rows:
            break  # caught up / no progress
        since_ns = new_since
        _time.sleep(REQUEST_INTERVAL_S)
    hours_written = rows_written = 0
    for hour in sorted(pending):
        if write_hour(base_dir, pair, hour, pending[hour]):
            hours_written += 1
            rows_written += len(pending[hour])
    print(
        f"  span {start:%Y-%m-%d %H}h..{end:%Y-%m-%d %H}h: "
        f"{n_req} requests, {hours_written} hours, {rows_written} rows"
    )
    return hours_written, rows_written


def backfill(
    pairs: list[str],
    base_dir: Path,
    dry_run: bool = False,
    max_hours: int | None = None,
) -> None:
    report = inventory(base_dir, pairs)
    total_missing = sum(len(r["missing"]) for r in report.values())
    print(f"\ntotal missing hours: {total_missing} "
          f"(>= {total_missing} requests at ~1 req/s minimum)")
    if dry_run:
        print("dry run — no writes")
        return
    altnames = resolve_altnames([p for p in pairs if report[p]["missing"]])
    for pair in pairs:
        miss = report[pair]["missing"]
        if not miss or pair not in altnames:
            continue
        if max_hours is not None:
            miss = miss[:max_hours]
        print(f"backfilling {pair} ({len(miss)} hours)")
        for span in gap_spans(miss):
            backfill_span(base_dir, pair, altnames[pair], span, set(miss))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="inventory + plan only, no writes")
    parser.add_argument("--pair", action="append", help="limit to pair(s), e.g. ETH/USD")
    parser.add_argument("--max-hours", type=int, default=None,
                        help="cap backfilled hours per pair (probe mode)")
    parser.add_argument("--base-dir", type=Path, default=None)
    args = parser.parse_args()

    base_dir = args.base_dir or ct.resolve_data_dir()
    pairs = args.pair or ct.GREENLIST_PAIRS
    backfill(pairs, base_dir, dry_run=args.dry_run, max_hours=args.max_hours)


if __name__ == "__main__":
    main()
