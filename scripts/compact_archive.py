"""Merge finished part files into one file per hour, across the whole archive.

Collectors flush to append-only `<stream>-<HH>.part-NNNN.parquet` so a crash
can never corrupt an hour (see collector_core). The cost is file count, and
parquet's per-file footer/schema overhead is charged whether a file holds
6 rows or 6000. This is the other half of that design: once an hour is
closed, its parts become one file.

Run from the watchdog (every 15 min) — it is idempotent, skips the current
hour so a live collector's parts are never merged out from under it, and is
safe to interrupt (each hour is written to a temp name and renamed).

    uv run python scripts/compact_archive.py
    uv run python scripts/compact_archive.py --root D:/tradekit-data --verbose
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collector_core import compact_closed_hours, resolve_data_root

# Trees holding collector output. Anything else under the root (logs/, and the
# vendor-backfill trees, which arrive pre-compacted) is left alone.
ARCHIVE_TREES = [
    "ticks",
    "books/coinbase",
    "books/okx",
    "books/binance",
    "trades/coinbase",
    "trades/okx",
    "trades/binance_us",
    "liquidations/okx",
    "perps/hyperliquid",
    "equities/alpaca",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=None, help="archive root (default: resolved)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    root = Path(args.root) if args.root else resolve_data_root()
    now = datetime.now(UTC)
    grand_rows = 0
    grand_secs = 0.0

    for tree in ARCHIVE_TREES:
        base = root / tree
        if not base.is_dir():
            continue
        t0 = time.perf_counter()
        rows = compact_closed_hours(base, now)
        el = time.perf_counter() - t0
        grand_rows += rows
        grand_secs += el
        if args.verbose and rows:
            print(f"{tree:26} merged {rows:>10,} rows in {el:6.1f}s")

    stamp = now.isoformat(timespec="seconds")
    print(f"{stamp} compacted {grand_rows:,} rows in {grand_secs:.1f}s")


if __name__ == "__main__":
    main()
