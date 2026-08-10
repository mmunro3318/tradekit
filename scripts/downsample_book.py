"""Bring stored book history down to the rate the collectors now record at.

WHY. `collect_ticks` never had a row throttle — it predates collector_core and
never inherited its default `throttled_streams={"book"}` — so Kraken book, the
largest stream in the archive, was sampled at the venue's chattiness while
every other book stream was coalesced to 1 Hz. Measured on 2026-08-08 across
77 symbols: 23,213,832 rows stored where 1 Hz keeps 2,347,045, a 9.9x
difference, with TAO_USD alone writing 2,114,430 rows in a day — more than
ETH. The collector is fixed; this brings the history to the same rate so the
archive has one sampling policy rather than a seam at the date it changed.

    uv run python scripts/downsample_book.py D:/tradekit-data/ticks
    uv run python scripts/downsample_book.py D:/tradekit-data/ticks --no-dry-run

It keeps the FIRST row of each interval, because that is what the live
`RowThrottle` does: it emits a row, then blocks for `interval` measured from
the row it emitted. The window slides from the last kept row rather than
sitting on a fixed grid, so history and new data are sampled the same way.

SAFETY. This deletes rows, so it is bounded hard:

  - `--dry-run` is ON by default.
  - Only `--stream book`. Trades are never touched and must never be: a
    dropped print is a hole in the tape that cannot be reconstructed.
  - Days at or after the cutoff (default: today UTC) are left to the live
    collector.
  - A row whose timestamp cannot be read is KEPT. Discarding is this tool's
    whole purpose, which is exactly why anything it cannot place in time has
    to survive instead of being dropped on a guess.
  - If any file in a (symbol, day, stream) unit is unreadable, the unit is
    skipped whole.
  - It takes `repartition_archive`'s tree lock, not its own. Both tools
    rewrite the same files, so they have to exclude each other.

The pass runs over a whole day at a time, not per hour, so an hour boundary
cannot smuggle through an extra row a few milliseconds after the last one.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from repartition_archive import DAY_RE, HOUR_FILE_RE, hour_files, tree_lock

DEFAULT_INTERVAL_S = 1.0


@dataclass
class Report:
    files_read: int = 0
    rows_read: int = 0
    rows_kept: int = 0
    rows_dropped: int = 0
    files_written: int = 0
    files_removed: int = 0
    skipped: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        pct = 100 * self.rows_dropped / max(self.rows_read, 1)
        return (
            f"files_read={self.files_read} rows_read={self.rows_read} "
            f"rows_kept={self.rows_kept} rows_dropped={self.rows_dropped} ({pct:.1f}%) "
            f"files_written={self.files_written} files_removed={self.files_removed} "
            f"skipped={len(self.skipped)}"
        )


def _epoch_us(column: Any) -> list[int | None]:
    """Each row's timestamp as microseconds since the epoch, None if unreadable."""
    import pyarrow as pa
    import pyarrow.compute as pc

    stamped = pa.timestamp("us", tz="UTC")
    try:
        if not pa.types.is_timestamp(column.type):
            column = pc.cast(column, stamped)
        return pc.cast(pc.cast(column, stamped), pa.int64()).to_pylist()
    except Exception:
        # A column pyarrow will not cast wholesale still deserves a best
        # effort per row; anything that fails stays None and is kept.
        out: list[int | None] = []
        for raw in column.to_pylist():
            try:
                parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                out.append(None)
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            out.append(int(parsed.timestamp() * 1_000_000))
        return out


def _keep_indices(stamps: list[int | None], interval_us: int) -> list[int]:
    """Indices surviving the throttle, assuming `stamps` is in time order.

    A row with no readable timestamp is kept and does not move the window —
    it cannot, since we do not know when it happened.
    """
    keep: list[int] = []
    last: int | None = None
    for i, us in enumerate(stamps):
        if us is None:
            keep.append(i)
            continue
        if last is None or us - last >= interval_us:
            keep.append(i)
            last = us
    return keep


def _downsample_unit(
    day_dir: Path, stream: str, interval_s: float, dry_run: bool, report: Report
) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    sources = hour_files(day_dir, stream)
    if not sources:
        return
    tables = []
    for f in sources:
        try:
            tables.append(pq.read_table(f))
        except Exception as exc:
            report.skipped.append(f"{f}: {exc!r}")
            return
    report.files_read += len(sources)

    table = pa.concat_tables(tables, promote_options="default")
    report.rows_read += table.num_rows

    # Order by the PARSED instant, never by the timestamp string. ISO-8601
    # does not sort lexicographically across mixed fractional precision:
    # `...T12:00:00Z` sorts AFTER `...T12:00:00.2Z` because "." < "Z", and
    # `datetime.isoformat()` omits the fraction whenever it is exactly zero.
    # Sorting by text would therefore hand the window the wrong neighbour and
    # keep the wrong row. Rows with no readable instant go last, where they
    # cannot disturb the ordering of the ones that have one.
    stamps = _epoch_us(table.column("ts"))
    order = sorted(
        range(len(stamps)), key=lambda i: (stamps[i] is None, stamps[i] or 0, i)
    )
    keep_at = _keep_indices([stamps[i] for i in order], int(interval_s * 1_000_000))
    keep = [order[p] for p in keep_at]
    dropped = table.num_rows - len(keep)
    report.rows_kept += len(keep)
    if dropped == 0:
        return
    report.rows_dropped += dropped
    if dry_run:
        return

    kept = table.take(keep)
    hours = _epoch_hours(kept)
    written: set[Path] = set()
    for hour in sorted(set(hours)):
        mask = [h == hour for h in hours]
        path = day_dir / f"{stream}-{hour:02d}.parquet"
        tmp = path.with_suffix(".parquet.tmp")
        try:
            pq.write_table(
                kept.filter(mask), tmp, compression="zstd", compression_level=3
            )
            tmp.replace(path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        written.add(path)
        report.files_written += 1
    for f in sources:
        if f not in written:
            f.unlink(missing_ok=True)
            report.files_removed += 1


def _epoch_hours(table: Any) -> list[int]:
    """The hour each kept row belongs to, so rows stay in their own hour file."""
    import pyarrow.compute as pc

    prefix = pc.utf8_slice_codeunits(table.column("ts").cast("string"), 11, 13).to_pylist()
    return [int(h) if h and h.isdigit() else 0 for h in prefix]


def downsample_tree(
    root: Path,
    dry_run: bool = True,
    before: date | None = None,
    stream: str = "book",
    interval_s: float = DEFAULT_INTERVAL_S,
) -> Report:
    """Coalesce `stream` to one row per `interval_s` across every closed day."""
    cutoff = before or datetime.now(UTC).date()
    report = Report()
    with tree_lock(root):
        for day_dir in sorted(p for p in root.rglob("*") if p.is_dir() and DAY_RE.match(p.name)):
            if date.fromisoformat(day_dir.name) >= cutoff:
                continue
            present = {
                m.group("stream") for f in day_dir.iterdir() if (m := HOUR_FILE_RE.match(f.name))
            }
            if stream in present:
                _downsample_unit(day_dir, stream, interval_s, dry_run, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", help="tree to thin, e.g. D:/tradekit-data/ticks")
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="inspect only (default); pass --no-dry-run to write",
    )
    parser.add_argument("--stream", default="book", help="stream to thin (default: book)")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_S)
    parser.add_argument(
        "--before", default=None, help="YYYY-MM-DD; days at or after this are left alone"
    )
    args = parser.parse_args()

    if args.stream == "trades":
        parser.error("refusing to thin trades — every print matters")

    report = downsample_tree(
        Path(args.root),
        dry_run=args.dry_run,
        before=date.fromisoformat(args.before) if args.before else None,
        stream=args.stream,
        interval_s=args.interval,
    )
    print(("DRY RUN " if args.dry_run else "") + str(report))
    for s in report.skipped:
        print(f"  SKIPPED {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
