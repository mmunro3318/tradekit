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

Byte-identical duplicate rows are collapsed: the same observation stored
twice is not two facts, and the broken Alpaca cursor produced 2,625 of them.
The dry run reports the count before anything is removed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HOUR_FILE_RE = re.compile(
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


def target_of(row: dict[str, Any]) -> tuple[str, int] | None:
    """The (YYYY-MM-DD, hour) a row belongs to, or None if its ts is unusable."""
    raw = str(row.get("ts") or "")
    if len(raw) < 13 or raw[4] != "-" or raw[10] not in "T ":
        return None
    day, hour = raw[:10], raw[11:13]
    if not _DAY_RE.match(day) or not hour.isdigit():
        return None
    return day, int(hour)


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


def _hour_files(day_dir: Path, stream: str) -> list[Path]:
    out = []
    for f in sorted(day_dir.iterdir()):
        m = _HOUR_FILE_RE.match(f.name)
        if m and m.group("stream") == stream:
            out.append(f)
    return out


def _repartition_unit(
    day_dir: Path, stream: str, cutoff: date, dry_run: bool, report: Report
) -> None:
    """Re-file one (symbol, day, stream). Reads everything before writing anything."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    sources = _hour_files(day_dir, stream)
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

    buckets: dict[tuple[str, int], list[dict[str, Any]]] = {}
    moved = 0
    for f, table in tables.items():
        m = _HOUR_FILE_RE.match(f.name)
        assert m is not None  # _hour_files only returns matches
        here = (day_dir.name, int(m.group("hour")))
        for row in table.to_pylist():
            report.rows_read += 1
            want = target_of(row)
            if want is None or date.fromisoformat(want[0]) >= cutoff:
                want = here  # unplaceable, or owned by a live collector
            elif want != here:
                moved += 1
            buckets.setdefault(want, []).append(row)

    # An hour already in compacted form, holding only its own rows and no
    # duplicates, is left completely alone — rewriting the archive to change
    # nothing is how a repair tool becomes the thing that breaks it.
    deduped = {k: _dedupe(v) for k, v in buckets.items()}
    dupes = sum(n for _, n in deduped.values())
    tidy = all(
        f.name == f"{stream}-{h:02d}.parquet" for f in sources if (h := _hour(f)) is not None
    )
    if moved == 0 and dupes == 0 and tidy:
        return

    # Pull in any target that already exists outside this unit (the cross-day
    # case) before writing, so a read failure aborts before any destruction.
    targets: dict[tuple[str, int], Path] = {
        key: day_dir.parent / key[0] / f"{stream}-{key[1]:02d}.parquet" for key in deduped
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
        rows, extra = _dedupe(existing.to_pylist() + deduped[key][0])
        deduped[key] = (rows, deduped[key][1] + extra)

    try:
        schema = pa.unify_schemas([t.schema for t in tables.values()])
    except Exception:
        schema = None  # let pyarrow infer rather than refuse to repair

    report.rows_moved += moved
    report.rows_deduped += sum(n for _, n in deduped.values())
    if dry_run:
        return

    for key, (rows, _) in deduped.items():
        path = targets[key]
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".parquet.tmp")
        pq.write_table(
            pa.Table.from_pylist(rows, schema=schema),
            tmp,
            compression="zstd",
            compression_level=3,
        )
        tmp.replace(path)
        report.files_written += 1
    for f in sources:
        if f not in targets.values():
            f.unlink(missing_ok=True)
            report.files_removed += 1


def _hour(path: Path) -> int | None:
    m = _HOUR_FILE_RE.match(path.name)
    return int(m.group("hour")) if m else None


def repartition_tree(root: Path, dry_run: bool = True, before: date | None = None) -> Report:
    """Repair every closed day under `root`. See the module docstring."""
    cutoff = before or datetime.now(UTC).date()
    report = Report()
    for day_dir in sorted(p for p in root.rglob("*") if p.is_dir() and _DAY_RE.match(p.name)):
        if date.fromisoformat(day_dir.name) >= cutoff:
            continue
        streams = {
            m.group("stream") for f in day_dir.iterdir() if (m := _HOUR_FILE_RE.match(f.name))
        }
        for stream in sorted(streams):
            _repartition_unit(day_dir, stream, cutoff, dry_run, report)
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
        "--before",
        default=None,
        help="YYYY-MM-DD; days at or after this are left to the live collectors "
        "(default: today UTC)",
    )
    args = parser.parse_args()

    before = date.fromisoformat(args.before) if args.before else None
    report = repartition_tree(Path(args.root), dry_run=args.dry_run, before=before)
    print(("DRY RUN " if args.dry_run else "") + str(report))
    for s in report.skipped:
        print(f"  SKIPPED {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
