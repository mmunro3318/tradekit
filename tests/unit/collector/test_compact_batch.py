"""Tests for scripts/compact_batch.py — the manual, batched compaction driver.

Compaction moved off the 15-minute watchdog on 2026-08-23 (the passive pass
rescanned the whole archive every run). This driver is what replaces it, so
the properties that matter are the ones an operator relies on when running it
by hand against a live archive: it does nothing without --execute, it honours
a work budget so a run can be bounded and resumed, and it reports what it
stopped on.

The compaction itself is injected, so none of this touches parquet.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import collector_core as cc
import compact_batch as cb


def _units(n: int) -> list[tuple[Path, str, int]]:
    return [(Path(f"/day/{i}"), "trades", i % 24) for i in range(n)]


def _counting_compact(calls: list[tuple[Path, str, int]], rows: int = 10) -> Callable[..., int]:
    def compact(day_dir: Path, stream: str, hour: int) -> int:
        calls.append((day_dir, stream, hour))
        return rows

    return compact


class TestDryRunIsTheDefaultPosture:
    def test_dry_run_never_compacts_but_still_sizes_the_job(self) -> None:
        calls: list[tuple[Path, str, int]] = []

        stats = cb.run_batches(
            _units(5), compact=_counting_compact(calls), execute=False, emit=lambda _: None
        )

        assert calls == []
        assert stats.units_done == 5
        assert stats.rows == 0

    def test_execute_compacts_every_unit_and_sums_rows(self) -> None:
        calls: list[tuple[Path, str, int]] = []

        stats = cb.run_batches(
            _units(3), compact=_counting_compact(calls), execute=True, emit=lambda _: None
        )

        assert len(calls) == 3
        assert stats.units_done == 3
        assert stats.rows == 30


class TestWorkBudget:
    """A bounded run is what makes this safe to invoke on a live archive."""

    def test_max_units_caps_the_run_and_names_the_reason(self) -> None:
        calls: list[tuple[Path, str, int]] = []

        stats = cb.run_batches(
            _units(100),
            compact=_counting_compact(calls),
            execute=True,
            max_units=4,
            emit=lambda _: None,
        )

        assert len(calls) == 4
        assert stats.units_done == 4
        assert stats.stopped_early == "max-units"

    def test_max_seconds_stops_between_units(self) -> None:
        calls: list[tuple[Path, str, int]] = []
        ticks = iter([0.0, 1.0, 2.0, 3.0, 4.0])

        stats = cb.run_batches(
            _units(100),
            compact=_counting_compact(calls),
            execute=True,
            max_seconds=2.0,
            clock=lambda: next(ticks),
            emit=lambda _: None,
        )

        # t0=0; unit0 at t=1 (<2, runs); unit1 at t=2 (budget spent, stop)
        assert len(calls) == 1
        assert stats.stopped_early == "max-seconds"

    def test_a_completed_run_reports_no_early_stop(self) -> None:
        stats = cb.run_batches(
            _units(3), compact=_counting_compact([]), execute=True, emit=lambda _: None
        )

        assert stats.stopped_early is None

    def test_no_work_is_not_an_error(self) -> None:
        stats = cb.run_batches([], compact=_counting_compact([]), execute=True, emit=lambda _: None)

        assert stats.units_done == 0
        assert stats.rows == 0
        assert stats.stopped_early is None


class TestProgressReporting:
    def test_emits_one_progress_line_per_batch(self) -> None:
        lines: list[str] = []

        cb.run_batches(
            _units(10),
            compact=_counting_compact([]),
            execute=True,
            batch_size=4,
            emit=lines.append,
        )

        # 10 units at batch_size 4 -> progress after 4 and 8, plus a final line
        assert len(lines) == 3


class TestArchiveLock:
    """Two concurrent compactions of one hour can duplicate every row.

    compact_hour merges the existing hourly file TOGETHER WITH the parts, so
    an interleaved second run can read the already-merged output and re-add
    the parts on top. The watchdog used to prevent this with a process-name
    check; a hand-run tool needs a real lock.
    """

    def test_lock_is_exclusive_while_held(self, tmp_path: Path) -> None:
        with cb.archive_lock(tmp_path):
            with pytest.raises(cb.LockHeld):
                with cb.archive_lock(tmp_path):
                    pass

    def test_lock_is_released_after_the_block(self, tmp_path: Path) -> None:
        with cb.archive_lock(tmp_path):
            pass

        with cb.archive_lock(tmp_path):  # must not raise
            pass

    def test_lock_is_released_even_when_the_body_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError):
            with cb.archive_lock(tmp_path):
                raise RuntimeError("boom")

        with cb.archive_lock(tmp_path):
            pass

    def test_force_breaks_a_stale_lock(self, tmp_path: Path) -> None:
        (tmp_path / cb.LOCK_NAME).write_text("pid=1 from a run that was killed")

        with cb.archive_lock(tmp_path, force=True):
            pass

        assert not (tmp_path / cb.LOCK_NAME).exists()


class TestDryRunLeavesNoTrace:
    """The banner promises nothing is modified; a lock file would break that."""

    def test_dry_run_writes_no_lock_file(self, tmp_path: Path, monkeypatch) -> None:
        (tmp_path / "ticks").mkdir()
        monkeypatch.setattr(
            sys, "argv", ["compact_batch.py", "--root", str(tmp_path), "--tree", "ticks"]
        )

        assert cb.main() == 0
        assert not (tmp_path / cb.LOCK_NAME).exists()

    def test_execute_releases_its_lock_on_the_way_out(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        (tmp_path / "ticks").mkdir()
        monkeypatch.setattr(
            sys,
            "argv",
            ["compact_batch.py", "--root", str(tmp_path), "--tree", "ticks", "--execute"],
        )

        assert cb.main() == 0
        assert not (tmp_path / cb.LOCK_NAME).exists()


class TestEndToEndAgainstRealParquet:
    """The whole CLI over parquet the production sink actually wrote.

    This tool DELETES part files once it has merged them, so row conservation
    is the property that matters most and it is worth proving against real
    files rather than an injected compactor.
    """

    DAYS = ("2026-08-20", "2026-08-21", "2026-08-22")

    def _seed(self, root: Path) -> int:
        """Write parts across several days/hours/symbols. Returns total rows."""
        base = root / "ticks"
        sink = cc.PartitionedParquetSink(base, partition=False)
        written = 0
        for day in self.DAYS:
            y, m, d = (int(x) for x in day.split("-"))
            for hour in (8, 9):
                for symbol in ("BTC/USD", "ETH/USD"):
                    ts = datetime(y, m, d, hour, 5, tzinfo=UTC)
                    for i in range(3):
                        sink.add(symbol, "trades", {"ts": ts.isoformat(), "price": float(i)}, ts)
                        written += 1
                    sink.flush(symbol, "trades")
        return written

    def _rows_on_disk(self, root: Path) -> int:
        import pyarrow.parquet as pq

        return sum(pq.ParquetFile(p).metadata.num_rows for p in root.rglob("*.parquet"))

    def _run(self, monkeypatch, root: Path, *extra: str) -> int:
        monkeypatch.setattr(
            sys, "argv", ["compact_batch.py", "--root", str(root), "--tree", "ticks", *extra]
        )
        return cb.main()

    def test_execute_conserves_every_row_and_removes_the_parts(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        expected = self._seed(tmp_path)
        assert self._rows_on_disk(tmp_path) == expected

        assert self._run(monkeypatch, tmp_path, "--execute") == 0

        assert self._rows_on_disk(tmp_path) == expected
        assert list(tmp_path.rglob("*.part-*.parquet")) == []
        assert list(tmp_path.rglob("trades-08.parquet"))

    def test_dry_run_leaves_the_parts_exactly_as_they_were(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        self._seed(tmp_path)
        before = sorted(p.name for p in tmp_path.rglob("*.part-*.parquet"))

        assert self._run(monkeypatch, tmp_path) == 0

        assert sorted(p.name for p in tmp_path.rglob("*.part-*.parquet")) == before

    def test_window_compacts_only_days_inside_it(self, tmp_path: Path, monkeypatch) -> None:
        self._seed(tmp_path)

        self._run(
            monkeypatch, tmp_path, "--execute", "--since", "2026-08-21", "--until", "2026-08-21"
        )

        remaining = {p.parent.name for p in tmp_path.rglob("*.part-*.parquet")}
        assert remaining == {"2026-08-20", "2026-08-22"}

    def test_a_budgeted_run_resumes_where_it_stopped(self, tmp_path: Path, monkeypatch) -> None:
        expected = self._seed(tmp_path)

        self._run(monkeypatch, tmp_path, "--execute", "--max-units", "2")
        assert list(tmp_path.rglob("*.part-*.parquet")) != []  # deliberately unfinished

        while list(tmp_path.rglob("*.part-*.parquet")):
            self._run(monkeypatch, tmp_path, "--execute", "--max-units", "2")

        assert self._rows_on_disk(tmp_path) == expected
