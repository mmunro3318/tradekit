"""Tests for scripts/repartition_archive.py — offline repair of misfiled rows.

Exercised against real temp-dir parquet, never mocks: the whole point of the
tool is what ends up on disk. The destructive path (source files removed) is
what most of these guard.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import repartition_archive as ra


def write_file(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)
    return path


def row(ts: str, price: float = 1.0) -> dict[str, Any]:
    return {"ts": ts, "price": price}


def rows_in(path: Path) -> list[dict[str, Any]]:
    return pq.read_table(path).to_pylist()


def all_rows(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in sorted(root.rglob("*.parquet")):
        out.extend(rows_in(f))
    return out


BEFORE = date(2026, 8, 9)  # everything in the fixtures is older than this


class TestRepartition:
    def test_a_misfiled_row_moves_to_the_hour_its_timestamp_names(self, tmp_path: Path) -> None:
        # Filed under hour 12, stamped 10:30 — the straggler shape.
        src = write_file(
            tmp_path / "BTC_USD" / "2026-08-08" / "trades-12.parquet",
            [row("2026-08-08T10:30:00Z"), row("2026-08-08T12:05:00Z", 2.0)],
        )

        ra.repartition_tree(tmp_path, dry_run=False, before=BEFORE)

        moved = tmp_path / "BTC_USD" / "2026-08-08" / "trades-10.parquet"
        assert [r["ts"] for r in rows_in(moved)] == ["2026-08-08T10:30:00Z"]
        assert [r["ts"] for r in rows_in(src)] == ["2026-08-08T12:05:00Z"]

    def test_a_row_stamped_a_different_day_moves_to_that_day(self, tmp_path: Path) -> None:
        write_file(
            tmp_path / "RIOT" / "2026-08-09" / "trades-03.parquet",
            [row("2026-08-07T23:59:51Z")],
        )

        ra.repartition_tree(tmp_path, dry_run=False, before=date(2026, 8, 10))

        assert rows_in(tmp_path / "RIOT" / "2026-08-07" / "trades-23.parquet") == [
            row("2026-08-07T23:59:51Z")
        ]
        assert not (tmp_path / "RIOT" / "2026-08-09" / "trades-03.parquet").exists()

    def test_rows_already_in_the_right_place_are_left_untouched(self, tmp_path: Path) -> None:
        # No rewrite at all — not even a byte-identical one. Rewriting the
        # whole archive to change nothing is how a repair tool becomes the
        # thing that corrupts it.
        good = write_file(
            tmp_path / "BTC_USD" / "2026-08-08" / "trades-10.parquet",
            [row("2026-08-08T10:00:00Z"), row("2026-08-08T10:59:00Z", 2.0)],
        )
        before_bytes = good.read_bytes()

        report = ra.repartition_tree(tmp_path, dry_run=False, before=BEFORE)

        assert good.read_bytes() == before_bytes
        assert report.rows_moved == 0

    def test_dry_run_reports_the_work_but_writes_nothing(self, tmp_path: Path) -> None:
        src = write_file(
            tmp_path / "BTC_USD" / "2026-08-08" / "trades-12.parquet",
            [row("2026-08-08T10:30:00Z")],
        )
        before_bytes = src.read_bytes()

        report = ra.repartition_tree(tmp_path, dry_run=True, before=BEFORE)

        assert report.rows_moved == 1
        assert src.read_bytes() == before_bytes
        assert not (tmp_path / "BTC_USD" / "2026-08-08" / "trades-10.parquet").exists()

    def test_exact_duplicate_rows_are_collapsed_when_asked(self, tmp_path: Path) -> None:
        # The Alpaca shape: the same print re-stored on every poll, scattered
        # across the partitions it was misfiled into.
        dup = row("2026-08-07T23:59:51Z")
        write_file(tmp_path / "RIOT" / "2026-08-07" / "trades-23.parquet", [dup])
        write_file(tmp_path / "RIOT" / "2026-08-08" / "trades-04.parquet", [dup, dup])

        report = ra.repartition_tree(tmp_path, dry_run=False, before=BEFORE, dedupe=True)

        assert all_rows(tmp_path) == [dup]
        assert report.rows_deduped == 2

    def test_duplicates_are_KEPT_by_default(self, tmp_path: Path) -> None:
        # Deleting rows is a bigger decision than moving them. On a stream that
        # is not de-duplicated at the source — Kraken's unthrottled book
        # re-writes an unchanged top-10, ~23% of its rows — identical rows may
        # be a resolution choice rather than an error, and a PARTITION repair
        # must not quietly make that call.
        dup = row("2026-08-07T23:59:51Z")
        write_file(tmp_path / "RIOT" / "2026-08-08" / "trades-04.parquet", [dup, dup])

        report = ra.repartition_tree(tmp_path, dry_run=False, before=BEFORE)

        assert all_rows(tmp_path) == [dup, dup]
        assert report.rows_deduped == 0

    def test_a_distinct_row_at_the_same_timestamp_is_not_collapsed(self, tmp_path: Path) -> None:
        # Two prints can share an instant. Only byte-identical rows are dupes.
        a, b = row("2026-08-08T10:00:00Z", 1.0), row("2026-08-08T10:00:00Z", 2.0)
        write_file(tmp_path / "BTC_USD" / "2026-08-08" / "trades-12.parquet", [a, b])

        ra.repartition_tree(tmp_path, dry_run=False, before=BEFORE, dedupe=True)

        assert sorted(r["price"] for r in all_rows(tmp_path)) == [1.0, 2.0]

    def test_merging_into_an_existing_target_loses_nothing(self, tmp_path: Path) -> None:
        write_file(
            tmp_path / "BTC_USD" / "2026-08-08" / "trades-10.parquet",
            [row("2026-08-08T10:00:00Z", 1.0)],
        )
        write_file(
            tmp_path / "BTC_USD" / "2026-08-08" / "trades-12.parquet",
            [row("2026-08-08T10:30:00Z", 2.0)],
        )

        ra.repartition_tree(tmp_path, dry_run=False, before=BEFORE)

        assert sorted(r["price"] for r in all_rows(tmp_path)) == [1.0, 2.0]

    def test_a_second_run_is_a_no_op(self, tmp_path: Path) -> None:
        write_file(
            tmp_path / "BTC_USD" / "2026-08-08" / "trades-12.parquet",
            [row("2026-08-08T10:30:00Z"), row("2026-08-08T12:05:00Z", 2.0)],
        )
        ra.repartition_tree(tmp_path, dry_run=False, before=BEFORE)
        settled = {p: p.read_bytes() for p in sorted(tmp_path.rglob("*.parquet"))}

        second = ra.repartition_tree(tmp_path, dry_run=False, before=BEFORE)

        assert second.rows_moved == 0
        assert {p: p.read_bytes() for p in sorted(tmp_path.rglob("*.parquet"))} == settled

    def test_part_files_are_repartitioned_too_not_just_compacted_ones(
        self, tmp_path: Path
    ) -> None:
        write_file(
            tmp_path / "BTC_USD" / "2026-08-08" / "trades-12.part-0003.parquet",
            [row("2026-08-08T10:30:00Z")],
        )

        ra.repartition_tree(tmp_path, dry_run=False, before=BEFORE)

        assert rows_in(tmp_path / "BTC_USD" / "2026-08-08" / "trades-10.parquet") == [
            row("2026-08-08T10:30:00Z")
        ]


class TestSafety:
    """Everything here protects a source file from being deleted by mistake.

    The tool removes source files, so any bug in it destroys the archive it
    was written to repair.
    """

    def test_an_unreadable_source_is_skipped_and_never_deleted(self, tmp_path: Path) -> None:
        # A real one exists: books/coinbase/.../CAKE_USD/2026-08-08/book-05.parquet
        # was left with no footer by a kill mid read-modify-write. Rewriting
        # the hour around it would silently drop whatever it still holds.
        day = tmp_path / "BTC_USD" / "2026-08-08"
        write_file(day / "trades-12.parquet", [row("2026-08-08T10:30:00Z")])
        corrupt = day / "trades-12.part-0001.parquet"
        corrupt.write_bytes(b"not a parquet file")

        report = ra.repartition_tree(tmp_path, dry_run=False, before=BEFORE)

        assert corrupt.exists()
        assert (day / "trades-12.parquet").exists()  # its hour was left alone
        assert report.rows_moved == 0
        assert any("trades-12.part-0001.parquet" in s for s in report.skipped)

    def test_days_at_or_after_the_cutoff_are_left_alone(self, tmp_path: Path) -> None:
        # A live collector still owns today, and can legitimately write into
        # an hour that has just closed.
        today = write_file(
            tmp_path / "BTC_USD" / "2026-08-09" / "trades-12.parquet",
            [row("2026-08-09T10:30:00Z")],
        )
        before_bytes = today.read_bytes()

        report = ra.repartition_tree(tmp_path, dry_run=False, before=BEFORE)

        assert today.read_bytes() == before_bytes
        assert report.rows_moved == 0

    def test_the_default_cutoff_is_today_so_live_data_is_never_touched(
        self, tmp_path: Path
    ) -> None:
        today = datetime.now(UTC)
        live = write_file(
            tmp_path / "BTC_USD" / f"{today:%Y-%m-%d}" / "trades-12.parquet",
            [row(f"{today:%Y-%m-%d}T10:30:00Z")],
        )
        before_bytes = live.read_bytes()

        ra.repartition_tree(tmp_path, dry_run=False)

        assert live.read_bytes() == before_bytes

    def test_a_file_that_is_not_an_hour_file_is_ignored(self, tmp_path: Path) -> None:
        day = tmp_path / "BTC_USD" / "2026-08-08"
        write_file(day / "trades-12.parquet", [row("2026-08-08T10:30:00Z")])
        stray = day / "notes.txt"
        stray.write_text("hello", encoding="utf-8")

        ra.repartition_tree(tmp_path, dry_run=False, before=BEFORE)

        assert stray.read_text(encoding="utf-8") == "hello"

    def test_a_row_with_no_usable_timestamp_stays_where_it_is(self, tmp_path: Path) -> None:
        # Never guess. An unparseable ts means we do not know where the row
        # belongs, and moving it on a guess is worse than leaving it.
        src = write_file(
            tmp_path / "BTC_USD" / "2026-08-08" / "trades-12.parquet",
            [{"ts": "", "price": 1.0}, row("2026-08-08T12:10:00Z", 2.0)],
        )

        report = ra.repartition_tree(tmp_path, dry_run=False, before=BEFORE)

        assert sorted(r["price"] for r in rows_in(src)) == [1.0, 2.0]
        assert report.rows_moved == 0

    def test_a_row_belonging_to_a_live_day_is_left_where_it_is(self, tmp_path: Path) -> None:
        # Misfiled the other way: an old partition holding a row stamped today.
        # Writing it into today's directory would race the live collector and
        # whatever compaction is doing to that hour, so it stays put.
        src = write_file(
            tmp_path / "BTC_USD" / "2026-08-08" / "trades-12.parquet",
            [row("2026-08-09T04:00:00Z")],
        )
        before_bytes = src.read_bytes()

        report = ra.repartition_tree(tmp_path, dry_run=False, before=BEFORE)

        assert src.read_bytes() == before_bytes
        assert not (tmp_path / "BTC_USD" / "2026-08-09").exists()
        assert report.rows_moved == 0


class TestEmptiedDirectories:
    def test_a_day_directory_emptied_of_every_row_is_removed(self, tmp_path: Path) -> None:
        # Leaving the husk behind is not cosmetic: collect_equities_alpaca
        # resumes from the newest day directory, and an empty one made it
        # fall back to the lookback floor and re-store five days of tape on
        # every poll.
        write_file(
            tmp_path / "RIOT" / "2026-08-08" / "trades-04.parquet",
            [row("2026-08-07T23:59:51Z")],
        )

        ra.repartition_tree(tmp_path, dry_run=False, before=BEFORE)

        assert (tmp_path / "RIOT" / "2026-08-07").is_dir()
        assert not (tmp_path / "RIOT" / "2026-08-08").exists()

    def test_a_directory_still_holding_anything_is_kept(self, tmp_path: Path) -> None:
        day = tmp_path / "RIOT" / "2026-08-08"
        write_file(day / "trades-04.parquet", [row("2026-08-07T23:59:51Z")])
        (day / "notes.txt").write_text("keep me", encoding="utf-8")

        ra.repartition_tree(tmp_path, dry_run=False, before=BEFORE)

        assert day.is_dir()
        assert (day / "notes.txt").read_text(encoding="utf-8") == "keep me"


class TestConcurrencyLock:
    """Two repairs on one tree must not race — the tool deletes source files.

    Hit for real on 2026-08-09: a second run was launched while the first was
    still working, and both were reading the same 698 MB symbol. Nothing was
    lost, but only because all reads happen before any write and both were
    still in the read phase. The window is real: run A reads, run B reads, A
    writes its targets and deletes the sources, B then writes targets built
    from its now-stale read and deletes sources again.

    Failing closed is the right trade. A stale lock costs one manual delete;
    a race costs rows.
    """

    def test_a_second_run_on_the_same_tree_refuses(self, tmp_path: Path) -> None:
        write_file(
            tmp_path / "BTC_USD" / "2026-08-08" / "trades-12.parquet",
            [row("2026-08-08T10:30:00Z")],
        )
        held = ra.tree_lock(tmp_path)
        held.__enter__()
        try:
            with pytest.raises(RuntimeError, match="already"):
                ra.repartition_tree(tmp_path, dry_run=False, before=BEFORE)
        finally:
            held.__exit__(None, None, None)

    def test_the_lock_is_released_so_the_next_run_proceeds(self, tmp_path: Path) -> None:
        write_file(
            tmp_path / "BTC_USD" / "2026-08-08" / "trades-12.parquet",
            [row("2026-08-08T10:30:00Z")],
        )
        ra.repartition_tree(tmp_path, dry_run=False, before=BEFORE)

        second = ra.repartition_tree(tmp_path, dry_run=False, before=BEFORE)

        assert second.rows_moved == 0
        assert not (tmp_path / ra.LOCK_NAME).exists()

    def test_a_dry_run_takes_the_lock_too(self, tmp_path: Path) -> None:
        # A dry run writes nothing, but it reads the whole tree to decide what
        # WOULD move. Letting it overlap a real run reports a plan built from
        # a tree that is being rewritten underneath it.
        held = ra.tree_lock(tmp_path)
        held.__enter__()
        try:
            with pytest.raises(RuntimeError, match="already"):
                ra.repartition_tree(tmp_path, dry_run=True, before=BEFORE)
        finally:
            held.__exit__(None, None, None)

    def test_the_lock_names_the_process_so_a_stale_one_can_be_judged(
        self, tmp_path: Path
    ) -> None:
        import os

        held = ra.tree_lock(tmp_path)
        held.__enter__()
        try:
            text = (tmp_path / ra.LOCK_NAME).read_text(encoding="utf-8")
        finally:
            held.__exit__(None, None, None)
        assert str(os.getpid()) in text
