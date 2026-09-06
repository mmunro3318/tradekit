"""Manual, batched compaction of closed hours. Run by hand, not by the watchdog.

Compaction came off the 15-minute watchdog schedule on 2026-08-23. The passive
pass re-walked the ENTIRE archive every run to discover work, so its cost grew
with the archive rather than with the backlog: by 263k files, runs that merged
nothing at all were taking up to 671 s and starting to overrun the 15-minute
interval (96 runs/day had slipped to 92).

Deferring compaction is safe and lossless — part files are self-contained
parquet, `PartitionedParquetSink._next_part` seeds its counter from disk so a
restart never reuses an index, and `compact_hour` merges any pre-existing
hourly file together with the parts. Nothing prunes parts except compaction
itself. What deferral costs is file count: roughly 2,800 part files per hour
(~68k/day) accumulate until this is run.

Dry-run is the default. Nothing is modified without --execute.

    # what would happen, whole archive
    uv run python scripts/compact_batch.py

    # actually compact the last three days
    uv run python scripts/compact_batch.py --days 3 --execute

    # bounded chunk: stop after 10 minutes, then just run it again
    uv run python scripts/compact_batch.py --execute --max-seconds 600
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collector_core import compact_hour, iter_compaction_units, resolve_data_root
from compact_archive import ARCHIVE_TREES

Unit = tuple[Path, str, int]

DEFAULT_BATCH_SIZE = 200
LOCK_NAME = ".compact-batch.lock"


class LockHeld(RuntimeError):
    """Another compaction run owns the archive."""


@contextmanager
def archive_lock(root: Path, *, force: bool = False) -> Iterator[Path]:
    """Exclusive whole-archive lock for the duration of the block.

    Not belt-and-braces. `compact_hour` merges the existing hourly file
    TOGETHER WITH the parts, so two runs interleaved on one hour can have the
    second read the already-merged output and re-add the parts on top of it —
    silently duplicating every row of that hour. The watchdog used to prevent
    this by checking for a running compact_archive.py; a tool invoked by hand
    needs a real lock.
    """
    path = root / LOCK_NAME
    if force:
        path.unlink(missing_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise LockHeld(
            f"{path} exists - another compaction run is in progress. "
            "If you are certain none is, re-run with --force."
        ) from None
    try:
        os.write(fd, f"pid={os.getpid()} started={datetime.now(UTC).isoformat()}\n".encode())
    finally:
        os.close(fd)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


@dataclass
class BatchStats:
    units_done: int = 0
    rows: int = 0
    seconds: float = 0.0
    stopped_early: str | None = None


def _echo(message: str) -> None:
    print(message, flush=True)


def run_batches(
    units: Iterable[Unit],
    *,
    compact: Callable[[Path, str, int], int],
    execute: bool,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_units: int | None = None,
    max_seconds: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    emit: Callable[[str], None] = _echo,
) -> BatchStats:
    """Compact `units`, reporting every `batch_size` and honouring a budget.

    The budget is checked BETWEEN units, never inside one: `compact_hour` is
    atomic per hour and must be allowed to finish, so `--max-seconds` bounds
    when the run stops taking new work rather than killing work in progress.
    Stopping early needs no bookkeeping — a re-run rediscovers whatever is
    left, because the work list is derived from the parts still on disk.
    """
    stats = BatchStats()
    started = clock()
    for day_dir, stream, hour in units:
        if max_units is not None and stats.units_done >= max_units:
            stats.stopped_early = "max-units"
            break
        if max_seconds is not None and clock() - started >= max_seconds:
            stats.stopped_early = "max-seconds"
            break
        if execute:
            stats.rows += compact(day_dir, stream, hour)
        stats.units_done += 1
        if stats.units_done % batch_size == 0:
            emit(
                f"  ... {stats.units_done:>6,} hours  {stats.rows:>12,} rows  "
                f"{clock() - started:>6.1f}s"
            )
    stats.seconds = clock() - started
    verb = "compacted" if execute else "would compact"
    tail = f"  (stopped early: {stats.stopped_early})" if stats.stopped_early else ""
    emit(f"{verb} {stats.units_done:,} hours, {stats.rows:,} rows in {stats.seconds:.1f}s{tail}")
    return stats


def _window(args: argparse.Namespace, now: datetime) -> tuple[str | None, str | None]:
    if args.days is not None:
        return (now - timedelta(days=args.days)).strftime("%Y-%m-%d"), None
    return args.since, args.until


def _iter_all(
    root: Path, trees: list[str], now: datetime, since: str | None, until: str | None
) -> Iterator[Unit]:
    for tree in trees:
        base = root / tree
        if base.is_dir():
            yield from iter_compaction_units(base, now, since, until)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", default=None, help="archive root (default: resolved)")
    parser.add_argument(
        "--tree", action="append", dest="trees", help="restrict to a tree (repeatable)"
    )
    parser.add_argument("--days", type=int, default=None, help="only days within the last N")
    parser.add_argument("--since", default=None, help="earliest day, YYYY-MM-DD (inclusive)")
    parser.add_argument("--until", default=None, help="latest day, YYYY-MM-DD (inclusive)")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-units", type=int, default=None, help="stop after N hours")
    parser.add_argument("--max-seconds", type=float, default=None, help="stop taking work after S")
    parser.add_argument(
        "--execute", action="store_true", help="actually compact (default: dry run)"
    )
    parser.add_argument("--force", action="store_true", help="break a stale lock")
    args = parser.parse_args()

    if args.days is not None and (args.since or args.until):
        parser.error("--days is mutually exclusive with --since/--until")

    root = Path(args.root) if args.root else resolve_data_root()
    if not root.is_dir():
        print(f"archive root {root} does not exist", file=sys.stderr)
        return 2

    trees = args.trees or ARCHIVE_TREES
    now = datetime.now(UTC)
    since, until = _window(args, now)

    scope = f"{since or 'start'}..{until or 'now'}"
    # ASCII only in emitted text: this lands in log files read through a
    # console codepage that mangles non-ASCII (see the "heartbeat timeout ?"
    # entries the collectors already leave behind).
    mode = "EXECUTE" if args.execute else "DRY RUN - nothing will be modified (use --execute)"
    print(f"root={root}  trees={len(trees)}  window={scope}\n{mode}", flush=True)

    # A dry run modifies nothing, so it takes no lock — writing a lock file
    # into the archive would contradict the banner it just printed, and it has
    # nothing to exclude anyone from.
    guard = archive_lock(root, force=args.force) if args.execute else nullcontext()
    try:
        with guard:
            stats = run_batches(
                _iter_all(root, trees, now, since, until),
                compact=compact_hour,
                execute=args.execute,
                batch_size=args.batch_size,
                max_units=args.max_units,
                max_seconds=args.max_seconds,
            )
    except LockHeld as exc:
        print(str(exc), file=sys.stderr)
        return 3

    if stats.stopped_early:
        print("re-run to continue where this left off", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
