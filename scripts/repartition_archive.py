"""Offline repair: re-file every row into the day/hour its own timestamp names.

WHY THIS EXISTS. Until 2026-08-09 every sink in the pipeline named its target
file from FLUSH time rather than from the row's timestamp, so a row's on-disk
hour recorded when we ingested it, not when it happened. On the live
websocket feeds that only leaked at hour boundaries; on the delayed Alpaca
poller the two diverge by design and a whole Friday equity tape was filed
under Sunday. Measured on 2026-08-08 alone: 1.87% of 24.2M Kraken book rows in
the wrong hour (38,148 in the wrong DAY), 5.90% of Coinbase trades, 14.7% of
Alpaca prints.

The collectors are fixed. This repairs what they already wrote, which is
possible only because the timestamp is in the data — nothing has to be
refetched.

    uv run python scripts/repartition_archive.py D:/tradekit-data/equities/alpaca
    uv run python scripts/repartition_archive.py D:/tradekit-data/ticks --no-dry-run

SAFETY. This deletes source files, so it is deliberately timid:

  - `--dry-run` is ON by default, like the backfillers.
  - Days at or after the cutoff (default: today UTC) are never touched, and no
    row is ever written INTO such a day. A live collector owns those.
  - If any file in a (symbol, day, stream) unit cannot be read, the whole unit
    is skipped rather than rewritten around the gap. One such file already
    exists — books/coinbase/crypto/CAKE_USD/2026-08-08/book-05.parquet was
    left with no footer by a kill mid read-modify-write — and rewriting its
    hour would silently discard whatever it still holds.
  - A row whose timestamp cannot be parsed stays exactly where it is. Not
    knowing where a row belongs is not a reason to guess.
  - An hour that is already correct is not rewritten at all, not even
    byte-identically.

Byte-identical duplicate rows are collapsed only with `--dedupe`, which is
OFF by default. The Alpaca cursor genuinely stored the same print twice and
needs it. But Kraken's unthrottled book re-writes an unchanged top-10
constantly (~23% of its rows), and whether that is redundancy or resolution
is a deliberate decision — a partition repair must not quietly make it. The
dry run reports the count before anything is removed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HOUR_FILE_RE = re.compile(
    r"^(?P<stream>[A-Za-z0-9_]+)-(?P<hour>\d{2})(?:\.part-\d{4})?\.parquet$"
)


@dataclass
class Report:
    files_read: int = 0
    rows_read: int = 0
    rows_moved: int = 0
    rows_deduped: int = 0
    files_written: int = 0
    files_removed: int = 0
    skipped: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"files_read={self.files_read} rows_read={self.rows_read} "
            f"rows_moved={self.rows_moved} rows_deduped={self.rows_deduped} "
            f"files_written={self.files_written} files_removed={self.files_removed} "
            f"skipped={len(self.skipped)}"
        )


def _placement(key: str | None, here: tuple[str, int], cutoff: date) -> tuple[str, int]:
    """Where rows carrying this `YYYY-MM-DDTHH` key belong.

    Falls back to `here` — leave the rows exactly where they are — when the
    timestamp is unreadable (we do not know where they go, and guessing is
    worse than leaving them) or when it names a day a live collector still
    owns.
    """
    if not key or len(key) < 13 or key[10] not in "T " or not DAY_RE.match(key[:10]):
        return here
    if not key[11:13].isdigit():
        return here
    try:
        if date.fromisoformat(key[:10]) >= cutoff:
            return here
    except ValueError:
        return here
    return key[:10], int(key[11:13])


def _dedupe(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        key = json.dumps(r, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out, len(rows) - len(out)


def hour_files(day_dir: Path, stream: str) -> list[Path]:
    out = []
    for f in sorted(day_dir.iterdir()):
        m = HOUR_FILE_RE.match(f.name)
        if m and m.group("stream") == stream:
            out.append(f)
    return out


def _hour_keys(table: Any) -> Any:
    """The `YYYY-MM-DDTHH` prefix of each row's `ts`, as an Arrow array.

    Everything downstream works off this instead of materialising rows. A
    41-column L10 book table inflates ~145x through `to_pylist()` — one 58 MB
    day of ETH/USD reached 8.5 GB resident and never finished — whereas
    slicing with an Arrow mask stays proportional to the data.
    """
    import pyarrow as pa
    import pyarrow.compute as pc

    ts = table.column("ts")
    if pa.types.is_timestamp(ts.type):
        return pc.strftime(ts, format="%Y-%m-%dT%H")
    return pc.utf8_slice_codeunits(ts.cast(pa.string()), 0, 13)


def _repartition_unit(
    day_dir: Path, stream: str, cutoff: date, dry_run: bool, dedupe: bool, report: Report
) -> None:
    """Re-file one (symbol, day, stream). Reads everything before writing anything."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    sources = hour_files(day_dir, stream)
    tables: dict[Path, Any] = {}
    for f in sources:
        try:
            tables[f] = pq.read_table(f)
        except Exception as exc:
            # Cannot know what this file holds, so cannot safely rewrite the
            # hours around it. Leave the whole unit alone and say so.
            report.skipped.append(f"{f}: {exc!r}")
            return
    report.files_read += len(tables)

    buckets: dict[tuple[str, int], list[Any]] = {}
    moved = 0
    for f, table in tables.items():
        m = HOUR_FILE_RE.match(f.name)
        assert m is not None  # hour_files only returns matches
        here = (day_dir.name, int(m.group("hour")))
        report.rows_read += table.num_rows
        keys = _hour_keys(table)
        for raw in pc.unique(keys).to_pylist():
            want = _placement(raw, here, cutoff)
            sub = table.filter(
                pc.is_null(keys) if raw is None else pc.equal(keys, raw)
            )
            if not sub.num_rows:
                continue
            if want != here:
                moved += sub.num_rows
            buckets.setdefault(want, []).append(sub)

    # An hour already in compacted form and holding only its own rows is left
    # completely alone — rewriting the archive to change nothing is how a
    # repair tool becomes the thing that breaks it.
    tidy = all(
        f.name == f"{stream}-{h:02d}.parquet" for f in sources if (h := _hour(f)) is not None
    )
    if moved == 0 and tidy and not dedupe:
        return

    # Pull in any target that already exists outside this unit (the cross-day
    # case) before writing, so a read failure aborts before any destruction.
    targets: dict[tuple[str, int], Path] = {
        key: day_dir.parent / key[0] / f"{stream}-{key[1]:02d}.parquet" for key in buckets
    }
    for key, path in targets.items():
        if path in tables or not path.exists():
            continue
        try:
            existing = pq.read_table(path)
        except Exception as exc:
            report.skipped.append(f"{path}: {exc!r}")
            return
        tables[path] = existing
        buckets[key].append(existing)

    merged: dict[tuple[str, int], Any] = {}
    for key, parts in buckets.items():
        table = pa.concat_tables(parts, promote_options="default")
        if dedupe:
            rows, dropped = _dedupe(table.to_pylist())
            if dropped:
                table = pa.Table.from_pylist(rows, schema=table.schema)
                report.rows_deduped += dropped
        merged[key] = table

    if moved == 0 and tidy and not report.rows_deduped:
        return
    report.rows_moved += moved
    if dry_run:
        return

    for key, table in merged.items():
        path = targets[key]
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".parquet.tmp")
        pq.write_table(table, tmp, compression="zstd", compression_level=3)
        tmp.replace(path)
        report.files_written += 1
    for f in sources:
        if f not in targets.values():
            f.unlink(missing_ok=True)
            report.files_removed += 1
    # A day directory we emptied must go with its files. The husk is not
    # cosmetic: collect_equities_alpaca resumes from the newest day directory,
    # and an empty one read as "nothing stored", sending the poller back to
    # its lookback floor to re-store five days of tape on every pass.
    if not any(day_dir.iterdir()):
        day_dir.rmdir()


def _hour(path: Path) -> int | None:
    m = HOUR_FILE_RE.match(path.name)
    return int(m.group("hour")) if m else None


LOCK_NAME = ".repartition.lock"


@contextmanager
def tree_lock(root: Path) -> Iterator[None]:
    """Refuse to repair a tree another run is already repairing.

    Two runs racing can lose rows: A reads, B reads, A writes its targets and
    unlinks the sources, then B writes targets built from its now-stale read
    and unlinks again. Hit for real on 2026-08-09 — nothing was lost only
    because both happened to still be in the read phase.

    Deliberately fails closed and does NOT try to detect a stale lock: there
    is no portable, safe liveness check for a pid (on Windows `os.kill(pid, 0)`
    terminates the process rather than probing it), and guessing wrong here
    means racing a live run. A lock left behind by a killed run costs one
    manual delete, and the error message says exactly that.
    """
    lock = root / LOCK_NAME
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError(
            f"{root} is already being repartitioned — {lock} exists "
            f"({lock.read_text(encoding='utf-8').strip()}). If that process is "
            f"gone, delete the lock file and re-run."
        ) from None
    try:
        os.write(fd, f"pid={os.getpid()} root={root}".encode())
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def repartition_tree(
    root: Path, dry_run: bool = True, before: date | None = None, dedupe: bool = False
) -> Report:
    """Repair every closed day under `root`. See the module docstring."""
    with tree_lock(root):
        return _repartition_tree(root, dry_run, before, dedupe)


def _repartition_tree(root: Path, dry_run: bool, before: date | None, dedupe: bool) -> Report:
    cutoff = before or datetime.now(UTC).date()
    report = Report()
    for day_dir in sorted(p for p in root.rglob("*") if p.is_dir() and DAY_RE.match(p.name)):
        if date.fromisoformat(day_dir.name) >= cutoff:
            continue
        streams = {
            m.group("stream") for f in day_dir.iterdir() if (m := HOUR_FILE_RE.match(f.name))
        }
        for stream in sorted(streams):
            _repartition_unit(day_dir, stream, cutoff, dry_run, dedupe, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", help="tree to repair, e.g. D:/tradekit-data/ticks")
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="inspect only (default); pass --no-dry-run to write",
    )
    parser.add_argument(
        "--dedupe",
        action="store_true",
        help="also drop byte-identical rows. OFF by default: on a stream that is "
        "not de-duplicated at the source those rows may be a resolution choice "
        "rather than an error, and a partition repair should not quietly make "
        "that call. Needed for the Alpaca tree, whose cursor really did store "
        "the same print twice.",
    )
    parser.add_argument(
        "--before",
        default=None,
        help="YYYY-MM-DD; days at or after this are left to the live collectors "
        "(default: today UTC)",
    )
    args = parser.parse_args()

    before = date.fromisoformat(args.before) if args.before else None
    report = repartition_tree(
        Path(args.root), dry_run=args.dry_run, before=before, dedupe=args.dedupe
    )
    print(("DRY RUN " if args.dry_run else "") + str(report))
    for s in report.skipped:
        print(f"  SKIPPED {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
