"""Tests for scripts/downsample_book.py — bring stored book history to 1 Hz.

Real temp-dir parquet throughout: this tool deletes rows, so what ends up on
disk is the only thing worth asserting.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import downsample_book as db
import repartition_archive as ra

DAY = "2026-08-08"
BEFORE = datetime(2026, 8, 9, tzinfo=UTC).date()


def book_row(ts: str, bid: float = 1.0) -> dict[str, Any]:
    return {"ts": ts, "bid_price_1": bid, "ask_price_1": bid + 1.0}


def at(hour: int, second: float, bid: float = 1.0) -> dict[str, Any]:
    base = datetime(2026, 8, 8, hour, tzinfo=UTC) + timedelta(seconds=second)
    return book_row(base.isoformat().replace("+00:00", "Z"), bid)


def write_file(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)
    return path


def all_rows(root: Path, stream: str = "book") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in sorted(root.rglob(f"{stream}-*.parquet")):
        out.extend(pq.read_table(f).to_pylist())
    return out


class TestCoalescing:
    """One row per symbol per interval, keeping the FIRST of each window.

    That is what the live `RowThrottle` does — it emits an update, then blocks
    for `interval` from the row it emitted — so the batch pass has to make the
    same choice or history and new data end up sampled differently.
    """

    def test_a_burst_inside_one_interval_collapses_to_its_first_row(
        self, tmp_path: Path
    ) -> None:
        rows = [at(12, i * 0.2, bid=100.0 + i) for i in range(5)]  # 0.0 .. 0.8s
        write_file(tmp_path / "BTC_USD" / DAY / "book-12.parquet", rows)

        report = db.downsample_tree(tmp_path, dry_run=False, before=BEFORE)

        kept = all_rows(tmp_path)
        assert len(kept) == 1
        assert kept[0]["bid_price_1"] == 100.0, "kept the wrong row — must be the first"
        assert report.rows_dropped == 4

    def test_rows_at_least_an_interval_apart_all_survive(self, tmp_path: Path) -> None:
        rows = [at(12, i * 1.0, bid=100.0 + i) for i in range(5)]
        write_file(tmp_path / "BTC_USD" / DAY / "book-12.parquet", rows)

        db.downsample_tree(tmp_path, dry_run=False, before=BEFORE)

        assert len(all_rows(tmp_path)) == 5

    def test_the_window_runs_from_the_kept_row_not_from_a_fixed_grid(
        self, tmp_path: Path
    ) -> None:
        # Engineered so the two policies disagree. Offsets 0.0, 0.5, 1.2, 1.4,
        # 2.1 seconds:
        #   calendar-second buckets -> 0.0, 1.2, 2.1   (first of seconds 0,1,2)
        #   sliding from last kept  -> 0.0, 1.2        (2.1 is only 0.9s later)
        # The live RowThrottle slides, so the batch pass must slide too.
        rows = [
            at(12, 0.0, 1.0),
            at(12, 0.5, 2.0),
            at(12, 1.2, 3.0),
            at(12, 1.4, 4.0),
            at(12, 2.1, 5.0),
        ]
        write_file(tmp_path / "BTC_USD" / DAY / "book-12.parquet", rows)

        db.downsample_tree(tmp_path, dry_run=False, before=BEFORE)

        assert [r["bid_price_1"] for r in all_rows(tmp_path)] == [1.0, 3.0]

    def test_the_pass_spans_the_whole_day_not_each_hour_separately(
        self, tmp_path: Path
    ) -> None:
        # Per-hour passes would always keep the first row of every hour, even
        # one arriving milliseconds after the last row of the hour before.
        write_file(tmp_path / "BTC_USD" / DAY / "book-12.parquet", [at(12, 3599.5, 1.0)])
        write_file(tmp_path / "BTC_USD" / DAY / "book-13.parquet", [at(12, 3599.9, 2.0)])

        db.downsample_tree(tmp_path, dry_run=False, before=BEFORE)

        assert [r["bid_price_1"] for r in all_rows(tmp_path)] == [1.0]

    def test_kept_rows_land_in_the_hour_their_own_timestamp_names(
        self, tmp_path: Path
    ) -> None:
        # The rewrite must not tip a whole day into one file. Includes a row
        # that IS dropped, so the rewrite path actually runs.
        write_file(
            tmp_path / "BTC_USD" / DAY / "book-12.parquet",
            [at(12, 0.0, 1.0), at(12, 0.5, 9.0), at(13, 0.0, 2.0)],
        )

        db.downsample_tree(tmp_path, dry_run=False, before=BEFORE)

        h12 = pq.read_table(tmp_path / "BTC_USD" / DAY / "book-12.parquet").to_pylist()
        h13 = pq.read_table(tmp_path / "BTC_USD" / DAY / "book-13.parquet").to_pylist()
        assert [r["bid_price_1"] for r in h12] == [1.0]
        assert [r["bid_price_1"] for r in h13] == [2.0]

    def test_a_unit_with_nothing_to_drop_is_not_rewritten(self, tmp_path: Path) -> None:
        src = write_file(
            tmp_path / "BTC_USD" / DAY / "book-12.parquet",
            [at(12, 0.0, 1.0), at(12, 5.0, 2.0)],
        )
        before_bytes = src.read_bytes()

        db.downsample_tree(tmp_path, dry_run=False, before=BEFORE)

        assert src.read_bytes() == before_bytes

    def test_regression_a_whole_second_timestamp_still_sorts_before_a_later_one(
        self, tmp_path: Path
    ) -> None:
        # ISO-8601 does not sort lexicographically across mixed fractional
        # precision: "12:00:00Z" > "12:00:00.5Z" as text, because "." < "Z",
        # and isoformat() drops the fraction when it is exactly zero. Ordering
        # by string kept the 0.5s row and dropped the 0.0s one — backwards.
        write_file(
            tmp_path / "BTC_USD" / DAY / "book-12.parquet",
            [at(12, 0.5, 2.0), at(12, 0.0, 1.0)],
        )

        db.downsample_tree(tmp_path, dry_run=False, before=BEFORE)

        assert [r["bid_price_1"] for r in all_rows(tmp_path)] == [1.0]

    def test_a_second_run_changes_nothing(self, tmp_path: Path) -> None:
        write_file(
            tmp_path / "BTC_USD" / DAY / "book-12.parquet",
            [at(12, i * 0.2, bid=100.0 + i) for i in range(20)],
        )
        db.downsample_tree(tmp_path, dry_run=False, before=BEFORE)
        settled = {p: p.read_bytes() for p in sorted(tmp_path.rglob("*.parquet"))}

        second = db.downsample_tree(tmp_path, dry_run=False, before=BEFORE)

        assert second.rows_dropped == 0
        assert {p: p.read_bytes() for p in sorted(tmp_path.rglob("*.parquet"))} == settled


class TestScopeAndSafety:
    """This deletes rows. Everything here bounds what it is allowed to delete."""

    def test_trades_are_never_touched(self, tmp_path: Path) -> None:
        # A dropped print is a hole in the tape. Only the named stream moves.
        trades = [
            {"ts": at(12, i * 0.01)["ts"], "price": 1.0, "qty": 1.0} for i in range(50)
        ]
        src = write_file(tmp_path / "BTC_USD" / DAY / "trades-12.parquet", trades)
        before_bytes = src.read_bytes()
        write_file(
            tmp_path / "BTC_USD" / DAY / "book-12.parquet",
            [at(12, i * 0.1) for i in range(20)],
        )

        db.downsample_tree(tmp_path, dry_run=False, before=BEFORE)

        assert src.read_bytes() == before_bytes
        assert len(all_rows(tmp_path, "trades")) == 50

    def test_days_at_or_after_the_cutoff_are_untouched(self, tmp_path: Path) -> None:
        live = write_file(
            tmp_path / "BTC_USD" / "2026-08-09" / "book-12.parquet",
            [at(12, i * 0.1) for i in range(20)],
        )
        before_bytes = live.read_bytes()

        report = db.downsample_tree(tmp_path, dry_run=False, before=BEFORE)

        assert live.read_bytes() == before_bytes
        assert report.rows_dropped == 0

    def test_dry_run_reports_the_work_but_writes_nothing(self, tmp_path: Path) -> None:
        src = write_file(
            tmp_path / "BTC_USD" / DAY / "book-12.parquet",
            [at(12, i * 0.2) for i in range(5)],
        )
        before_bytes = src.read_bytes()

        report = db.downsample_tree(tmp_path, dry_run=True, before=BEFORE)

        assert report.rows_dropped == 4
        assert src.read_bytes() == before_bytes

    def test_a_row_with_an_unreadable_timestamp_is_kept_not_dropped(
        self, tmp_path: Path
    ) -> None:
        # Dropping is this tool's whole job, which is exactly why a row it
        # cannot place in time must survive rather than be discarded on a guess.
        write_file(
            tmp_path / "BTC_USD" / DAY / "book-12.parquet",
            [at(12, 0.0, 1.0), book_row("", 2.0), at(12, 0.1, 3.0)],
        )

        db.downsample_tree(tmp_path, dry_run=False, before=BEFORE)

        assert sorted(r["bid_price_1"] for r in all_rows(tmp_path)) == [1.0, 2.0]

    def test_an_unreadable_source_file_aborts_the_unit(self, tmp_path: Path) -> None:
        day = tmp_path / "BTC_USD" / DAY
        good = write_file(day / "book-12.parquet", [at(12, i * 0.1) for i in range(20)])
        before_bytes = good.read_bytes()
        corrupt = day / "book-13.parquet"
        corrupt.write_bytes(b"not a parquet file")

        report = db.downsample_tree(tmp_path, dry_run=False, before=BEFORE)

        assert good.read_bytes() == before_bytes
        assert corrupt.exists()
        assert report.rows_dropped == 0
        assert any("book-13.parquet" in s for s in report.skipped)

    def test_it_refuses_to_run_while_another_repair_holds_the_tree(
        self, tmp_path: Path
    ) -> None:
        # Shares repartition_archive's lock deliberately: both rewrite the same
        # files, so they must exclude each other, not just themselves.
        write_file(tmp_path / "BTC_USD" / DAY / "book-12.parquet", [at(12, 0.0)])
        held = ra.tree_lock(tmp_path)
        held.__enter__()
        try:
            with pytest.raises(RuntimeError, match="already"):
                db.downsample_tree(tmp_path, dry_run=False, before=BEFORE)
        finally:
            held.__exit__(None, None, None)
