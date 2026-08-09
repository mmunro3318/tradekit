"""Move the archive from a flat <SYMBOL>/ tree to <asset-class>/<SYMBOL>/.

The archive started as 11 crypto/USD pairs where one flat directory per
symbol was fine. It is now 56 tick pairs across stablecoins, fiat crosses,
RWAs and crypto-quoted ratios, heading for more — mixing all of those in one
listing makes the tree hard to reason about and hard to publish selectively
(the open-source release will likely ship the stablecoin and RWA sleeves on
different cadences from the majors).

Classes come from `collector_core.asset_class`, so the on-disk layout and the
collectors' idea of it cannot drift.

    before:  D:/tradekit-data/ticks/USDC_USD/2026-08-08/book-09.parquet
    after:   D:/tradekit-data/ticks/stables/USDC_USD/2026-08-08/book-09.parquet

SAFETY. This mutates several GB of irreplaceable collected data, so:
  * `--dry-run` is the DEFAULT; nothing moves without `--apply`.
  * It REFUSES to run while any collector process is alive — a live writer
    holding an open handle would either fail the move or, worse, keep writing
    into the old path afterwards and silently split the archive in two.
  * Moves are per-symbol `Path.rename` within the same filesystem, so each is
    atomic; an interruption leaves some symbols moved and some not, and
    re-running finishes the job.
  * It never merges into an existing destination — a collision aborts that
    symbol and is reported rather than risking two sources into one dir.

AFTER APPLYING you must set `PARTITION_BY_CLASS = True` in collector_core.py
and restart the collectors, or new writes will go back to the flat paths.

    uv run python scripts/migrate_layout.py                 # dry run
    uv run python scripts/migrate_layout.py --apply
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collector_core import EXTERNAL_DATA_ROOT, asset_class

# Roots holding a flat <SYMBOL>/ tree. Each is migrated independently.
ARCHIVE_ROOTS = [
    Path("ticks"),
    Path("books/coinbase"),
    Path("books/binance"),
    Path("books/okx"),
    Path("trades/coinbase"),
    Path("trades/binance_us"),
    Path("trades/okx"),
]

_SYMBOL_DIR = re.compile(r"^[A-Z0-9]+_[A-Z0-9]+$")
_KNOWN_CLASSES = {"crypto", "stables", "rwa", "fx", "cross"}


def symbol_from_dirname(name: str) -> str:
    """"BTC_USD" -> "BTC/USD" so asset_class() can match its rules."""
    return name.replace("_", "/", 1)


def live_collectors() -> list[str]:
    """Command lines of any running collector process (empty when safe)."""
    try:
        out = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                "Where-Object { $_.CommandLine -match 'collect_' } | "
                "ForEach-Object { $_.CommandLine }",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    except Exception as exc:
        print(f"WARN: could not check for live collectors ({exc!r}) — assuming unsafe")
        return ["<unknown>"]


def plan_moves(root: Path) -> list[tuple[Path, Path]]:
    """(source, destination) for every flat symbol dir under `root`.

    Already-partitioned directories are skipped, so this is idempotent.
    """
    if not root.is_dir():
        return []
    moves: list[tuple[Path, Path]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name in _KNOWN_CLASSES:
            continue
        if not _SYMBOL_DIR.match(child.name):
            print(f"NOTE: skipping unrecognised directory {child}")
            continue
        cls = asset_class(symbol_from_dirname(child.name))
        moves.append((child, root / cls / child.name))
    return moves


def apply_moves(moves: list[tuple[Path, Path]]) -> tuple[int, int]:
    moved = failed = 0
    for src, dst in moves:
        if dst.exists():
            print(f"ABORT {src.name}: destination already exists ({dst}) — merge by hand")
            failed += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            src.rename(dst)
            moved += 1
        except OSError as exc:
            print(f"ABORT {src.name}: {exc!r}")
            failed += 1
    return moved, failed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="actually move (default: dry run)")
    parser.add_argument("--root", default=str(EXTERNAL_DATA_ROOT))
    args = parser.parse_args()

    base = Path(args.root)
    if not base.is_dir():
        print(f"ERROR: archive root {base} not found")
        sys.exit(2)

    if args.apply:
        live = live_collectors()
        if live:
            print("REFUSING to migrate — these collector processes are running:")
            for ln in live:
                print(f"  {ln}")
            print("\nStop them first, migrate, flip PARTITION_BY_CLASS, then restart.")
            sys.exit(1)

    grand_total = 0
    for rel in ARCHIVE_ROOTS:
        root = base / rel
        moves = plan_moves(root)
        if not moves:
            continue
        print(f"\n=== {rel} ({len(moves)} symbol dirs) ===")
        by_class: dict[str, list[str]] = {}
        for src, dst in moves:
            by_class.setdefault(dst.parent.name, []).append(src.name)
        for cls in sorted(by_class):
            print(f"  {cls:8} {len(by_class[cls]):3}  {' '.join(sorted(by_class[cls]))}")
        grand_total += len(moves)
        if args.apply:
            moved, failed = apply_moves(moves)
            print(f"  -> moved {moved}, failed {failed}")

    if not args.apply:
        print(f"\nDRY RUN — {grand_total} directories would move. Re-run with --apply.")
        print("Then set PARTITION_BY_CLASS = True in scripts/collector_core.py.")


if __name__ == "__main__":
    main()
