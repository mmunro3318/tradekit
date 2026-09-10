"""Fragment-aware present-hour detection for scripts/backfill_ticks.py.

The archive stores each hour as either a compacted `trades-<HH>.parquet` /
`book-<HH>.parquet` or one-or-more append-only `<stream>-<HH>.part-NNNN.parquet`
fragments (merged later by compaction). Both forms are valid, self-contained
parquet — see docs/ARCHIVE-README.md "path grammar". Before this fix,
`present_trade_hours`/`earliest_book_hour` globbed `trades-*.parquet` /
`book-*.parquet` (which DOES match fragments) but then parsed the hour with
`int(f.stem.split("-", 1)[1])`, which raises ValueError on a fragment stem
(e.g. "trades-18.part-0000") and is silently skipped — so every
fragment-only hour is reported as a gap and re-downloaded/duplicated.

No network — behavior tests over hand-built tmp_path archive trees, mirroring
the import mechanism of tests/unit/collector/test_backfill_ticks.py.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import backfill_ticks as bt


class TestPresentTradeHoursSeesFragments:
    """BEHAVIOR: an hour counts as present when ANY present-form file for
    it exists (compacted or fragment). Breaks (pre-fix) because fragment
    stems raise ValueError in the int-parse and are dropped, so hour 04
    would be reported as still-missing despite two fragments on disk."""

    def test_fragments_and_compacted_hours_are_present_others_ignored(
        self, tmp_path: Path
    ) -> None:
        d = bt.ct.trade_file_path(tmp_path, "BTC/USD", datetime(2026, 9, 6, tzinfo=UTC)).parent
        d.mkdir(parents=True)
        (d / "trades-03.parquet").touch()
        (d / "trades-04.part-0000.parquet").touch()
        (d / "trades-04.part-0001.parquet").touch()
        (d / "trades-05.parquet.corrupt-no-footer").touch()
        (d / "trades-06.parquet.tmp").touch()

        hours = bt.present_trade_hours(tmp_path, "BTC/USD")

        assert hours == {
            datetime(2026, 9, 6, 3, tzinfo=UTC),
            datetime(2026, 9, 6, 4, tzinfo=UTC),
        }


class TestEarliestBookHourSeesFragments:
    """BEHAVIOR: the book anchor helper applies the identical present-form
    rule. Breaks (pre-fix) the same way — a book fragment's hour is dropped
    by the int-parse, so the anchor would skip past real fragment data."""

    def test_fragment_only_hour_is_the_earliest_anchor(self, tmp_path: Path) -> None:
        # The earliest hour (03) exists ONLY as a fragment; a later hour
        # (05) is compacted. Pre-fix, the fragment's hour fails to parse
        # and is dropped, so the anchor would wrongly land on hour 05.
        d = bt.ct.book_file_path(tmp_path, "BTC/USD", datetime(2026, 9, 6, tzinfo=UTC)).parent
        d.mkdir(parents=True)
        (d / "book-03.part-0000.parquet").touch()
        (d / "book-05.parquet").touch()
        (d / "book-01.parquet.corrupt-no-footer").touch()
        (d / "book-02.parquet.tmp").touch()

        assert bt.earliest_book_hour(tmp_path, "BTC/USD") == datetime(
            2026, 9, 6, 3, tzinfo=UTC
        )


class TestWriteHourRefusesOnFragment:
    """BEHAVIOR: write_hour must refuse to write an hour that already has
    ANY present-form file, not just the exact compacted path. Breaks
    (pre-fix) because write_hour only checks `trade_file_path(...).exists()`
    (the compacted name) — it would happily write trades-04.parquet next to
    an existing fragment, producing a name collision / duplicate data for
    an hour collection already has."""

    def test_refuses_and_writes_nothing_for_fragment_only_hour(
        self, tmp_path: Path
    ) -> None:
        pytest.importorskip("pyarrow")
        import pyarrow as pa
        import pyarrow.parquet as pq

        hour = datetime(2026, 9, 6, 4, tzinfo=UTC)
        # Mirror TestSkipExistingHour in test_backfill_ticks.py: derive the
        # real (possibly asset-class-partitioned) directory from
        # trade_file_path rather than assuming a flat layout.
        d = bt.ct.trade_file_path(tmp_path, "BTC/USD", hour).parent
        d.mkdir(parents=True)
        frag = d / "trades-04.part-0000.parquet"
        pq.write_table(pa.table({"ts": ["2026-09-06T04:00:00Z"]}), frag)

        rows = [bt.rest_trade_to_row(["1", "1", hour.timestamp(), "b", "m", ""])]
        assert bt.write_hour(tmp_path, "BTC/USD", hour, rows) is False

        assert sorted(p.name for p in d.iterdir()) == ["trades-04.part-0000.parquet"]


class TestPresentTradeHoursUsesPartitionedLayout:
    """BEHAVIOR: present_trade_hours must read through the SAME layout
    helper the writer uses (ct.trade_file_path -> stream_dir), never a
    private flat path join. Breaks (pre-fix): present_trade_hours builds
    `base_dir / pair.replace("/", "_")`, the retired flat layout, so a
    partitioned tree (where the writer actually puts files) is invisible --
    0 hours reported despite real data on disk. A stale flat tree sitting
    next to it must NOT resurrect hours either -- no fallback to the
    retired layout."""

    def test_partitioned_tree_is_read_flat_sibling_is_not(self, tmp_path: Path) -> None:
        d = bt.ct.trade_file_path(tmp_path, "BTC/USD", datetime(2026, 9, 6, tzinfo=UTC)).parent
        d.mkdir(parents=True)
        (d / "trades-03.parquet").touch()
        (d / "trades-04.part-0000.parquet").touch()

        flat = tmp_path / "BTC_USD" / "2026-09-06"
        flat.mkdir(parents=True)
        (flat / "trades-07.parquet").touch()

        hours = bt.present_trade_hours(tmp_path, "BTC/USD")

        assert hours == {
            datetime(2026, 9, 6, 3, tzinfo=UTC),
            datetime(2026, 9, 6, 4, tzinfo=UTC),
        }


class TestEarliestBookHourUsesPartitionedLayout:
    """BEHAVIOR: earliest_book_hour applies the identical layout-delegation
    rule as present_trade_hours above."""

    def test_partitioned_tree_is_read_flat_sibling_is_not(self, tmp_path: Path) -> None:
        d = bt.ct.book_file_path(tmp_path, "BTC/USD", datetime(2026, 9, 6, tzinfo=UTC)).parent
        d.mkdir(parents=True)
        (d / "book-03.parquet").touch()

        flat = tmp_path / "BTC_USD" / "2026-09-06"
        flat.mkdir(parents=True)
        (flat / "book-01.parquet").touch()

        assert bt.earliest_book_hour(tmp_path, "BTC/USD") == datetime(
            2026, 9, 6, 3, tzinfo=UTC
        )
