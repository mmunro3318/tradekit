"""Tests for scripts/collector_core.py — shared collector infrastructure.

Covers the pure logic (asset-class routing, path shape, sharding, throttle,
backoff) plus the parquet sink and hourly compaction, which are exercised
against real temp-dir parquet round-trips rather than mocks. No network.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import collector_core as cc


class TestAssetClass:
    """Routing rules in cc._CLASS_RULES: first match wins, narrow over broad.

    Load-bearing distinction (per the module's own comment): the BASE asset
    decides "stables" (peg monitoring, whatever it's quoted against) and the
    QUOTE asset decides "cross" (a basis/ratio series on whatever's quoted in
    crypto or a stablecoin). Mixing those up would bury majors like BTC/USDT
    in the depeg-monitoring sleeve instead of treating them as basis data.
    """

    def test_documented_examples(self) -> None:
        assert cc.asset_class("USDC/USD") == "stables"
        assert cc.asset_class("ETH/BTC") == "cross"
        assert cc.asset_class("PAXG/USD") == "rwa"
        assert cc.asset_class("BTC/EUR") == "fx"
        assert cc.asset_class("SOL/USD") == "crypto"

    def test_stable_base_routes_to_stables_regardless_of_quote(self) -> None:
        assert cc.asset_class("USDC/USD") == "stables"
        assert cc.asset_class("USDC/EUR") == "stables"

    def test_stable_quote_routes_to_cross_not_stables(self) -> None:
        # BTC/USDT and ETH/USDT are basis instruments quoted in a stablecoin,
        # not peg-monitoring data — they must NOT land in "stables".
        assert cc.asset_class("BTC/USDC") == "cross"
        assert cc.asset_class("ETH/USDT") == "cross"

    def test_eurc_base_is_stables_not_fx(self) -> None:
        # EURC is a stablecoin base (rule 1) and is NOT caught by the fx base
        # rule "^(USD|EUR|...)/ " (that needs literal "EUR/", and "EURC/"
        # fails that anchor) — no ambiguity in practice, but pin the intent:
        # a EURC pair is peg-monitoring data, not fx.
        assert cc.asset_class("EURC/USD") == "stables"

    def test_first_match_wins_rwa_over_cross(self) -> None:
        # PAXG/BTC matches BOTH the rwa rule (base PAXG) and the cross rule
        # (quote BTC). rwa is declared first -> rwa wins.
        assert cc.asset_class("PAXG/BTC") == "rwa"

    def test_first_match_wins_fx_base_over_stable_quote_cross(self) -> None:
        # EUR/USDC matches BOTH the fx-base rule (EUR is a fiat base) and the
        # cross rule (quote is a stablecoin). fx-base is declared first ->
        # fx wins.
        assert cc.asset_class("EUR/USDC") == "fx"

    def test_usd_base_is_fx_but_usd_quote_is_excluded_from_fiat_quote(self) -> None:
        # USD is folded into the fx BASE list (USD/JPY -> fx) but deliberately
        # excluded from the fiat QUOTE list, since "/USD$" would otherwise
        # pull every major (BTC/USD, ETH/USD, ...) into the fx sleeve.
        assert cc.asset_class("USD/JPY") == "fx"
        assert cc.asset_class("BTC/USD") == "crypto"

    def test_fx_base_and_quote_rules(self) -> None:
        assert cc.asset_class("EUR/USD") == "fx"
        assert cc.asset_class("BTC/EUR") == "fx"

    def test_unmatched_pair_defaults_to_crypto(self) -> None:
        assert cc.asset_class("DOGE/USD") == "crypto"
        assert cc.asset_class("LINK/ETH") == "cross"

    def test_regression_stablecoin_quoted_major_is_not_stables(self) -> None:
        # Bug fixed 2026-08-08: a stablecoin QUOTE (BTC/USDT, BTC/USDC) was
        # landing in "stables" alongside genuine peg-monitoring pairs like
        # USDC/USD. That would have buried ~20 majors, quoted in a
        # stablecoin, in the depeg sleeve instead of treating them as basis
        # instruments. Only a stablecoin BASE is "stables".
        assert cc.asset_class("BTC/USDT") != "stables"
        assert cc.asset_class("BTC/USDT") == "cross"
        assert cc.asset_class("BTC/USDC") != "stables"
        assert cc.asset_class("BTC/USDC") == "cross"

    def test_regression_plain_usd_quoted_major_is_not_fx(self) -> None:
        # Bug fixed 2026-08-08: a naive "/USD$" fiat-quote rule would have
        # swallowed every major (BTC/USD, ETH/USD, ...) into "fx", since USD
        # is the archive's default quote currency, not a foreign one. Only a
        # NON-USD fiat quote (EUR/GBP/AUD/CHF/CAD/JPY) implies fx.
        assert cc.asset_class("BTC/USD") != "fx"
        assert cc.asset_class("BTC/USD") == "crypto"
        assert cc.asset_class("ETH/USD") != "fx"
        assert cc.asset_class("ETH/USD") == "crypto"

    def test_every_greenlist_group_routes_to_its_intended_class(self) -> None:
        # Ties the on-disk layout to the INTENT encoded by the _PAIRS_* groups
        # in collect_ticks.py, rather than to a pair count. Counting pairs made
        # this test fail every time the greenlist grew, which is churn, not
        # protection; what actually matters is that a pair filed under the
        # stablecoin group never lands in fx/ (or vice versa), because that is
        # the silent misfile that would bury peg data in the wrong sleeve.
        import collect_ticks as ct

        expected = {
            "crypto": [
                *ct._PAIRS_L1,
                *ct._PAIRS_INFRA,
                *ct._PAIRS_ACADEMIC,
                *ct._PAIRS_BRIDGE,
                *ct._PAIRS_DEX,
            ],
            "rwa": ct._PAIRS_RWA,
            "stables": [*ct._PAIRS_STABLE, *ct._PAIRS_STABLE_FX],
            "fx": ct._PAIRS_FX,
            "cross": ct._PAIRS_CROSS,
        }
        misfiled = {
            pair: (cls, cc.asset_class(pair))
            for cls, pairs in expected.items()
            for pair in pairs
            if cc.asset_class(pair) != cls
        }
        assert not misfiled, f"pairs routed to the wrong class (pair: expected, got): {misfiled}"

    def test_every_greenlist_pair_gets_a_known_class(self) -> None:
        from collect_ticks import GREENLIST_PAIRS

        known = {"crypto", "stables", "fx", "cross", "rwa"}
        assert {cc.asset_class(p) for p in GREENLIST_PAIRS} <= known


class TestSymbolDirname:
    def test_slash_and_colon_are_sanitized(self) -> None:
        assert cc.symbol_dirname("BTC/USD") == "BTC_USD"
        assert cc.symbol_dirname("BTC-PERP:USD") == "BTC-PERP_USD"


class TestStreamDir:
    TS = datetime(2026, 8, 8, 9, 5, tzinfo=UTC)

    def test_partition_off(self) -> None:
        d = cc.stream_dir(Path("base"), "BTC/USD", self.TS, partition=False)
        assert d == Path("base/BTC_USD/2026-08-08")

    def test_partition_on_inserts_asset_class_dir(self) -> None:
        d = cc.stream_dir(Path("base"), "PAXG/USD", self.TS, partition=True)
        assert d == Path("base/rwa/PAXG_USD/2026-08-08")

    def test_partition_none_follows_module_partition_by_class_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # `partition=None` is not "off" — it's "whatever the archive is
        # currently deployed as". The module constant is the single switch
        # for the whole archive layout; pin that contract explicitly rather
        # than assuming a particular default value.
        monkeypatch.setattr(cc, "PARTITION_BY_CLASS", True)
        assert cc.stream_dir(Path("base"), "BTC/USD", self.TS, partition=None) == Path(
            "base/crypto/BTC_USD/2026-08-08"
        )

        monkeypatch.setattr(cc, "PARTITION_BY_CLASS", False)
        assert cc.stream_dir(Path("base"), "BTC/USD", self.TS, partition=None) == Path(
            "base/BTC_USD/2026-08-08"
        )


class TestHourFilePath:
    TS = datetime(2026, 8, 8, 9, 5, tzinfo=UTC)

    def test_compacted_file_no_part(self) -> None:
        p = cc.hour_file_path(Path("base"), "BTC/USD", "trades", self.TS, partition=False)
        assert p == Path("base/BTC_USD/2026-08-08/trades-09.parquet")

    def test_part_file_is_zero_padded_4_digits(self) -> None:
        p = cc.hour_file_path(Path("base"), "BTC/USD", "trades", self.TS, part=7, partition=False)
        assert p.name == "trades-09.part-0007.parquet"

    def test_part_file_high_number_still_4_digits(self) -> None:
        p = cc.hour_file_path(
            Path("base"), "BTC/USD", "trades", self.TS, part=12345, partition=False
        )
        assert p.name == "trades-09.part-12345.parquet"

    def test_symbol_with_slash_is_filesystem_safe(self) -> None:
        p = cc.hour_file_path(Path("base"), "ETH/BTC", "trades", self.TS, partition=False)
        assert "/" not in p.relative_to(Path("base")).parts[0]
        assert p.relative_to(Path("base")).parts[0] == "ETH_BTC"


class TestShard:
    def test_no_cap_returns_one_chunk(self) -> None:
        items = [f"P{i}" for i in range(50)]
        assert cc.shard(items, None) == [items]

    def test_exact_multiple_splits_evenly(self) -> None:
        items = [f"P{i}" for i in range(6)]
        chunks = cc.shard(items, 2)
        assert chunks == [["P0", "P1"], ["P2", "P3"], ["P4", "P5"]]

    def test_remainder_forms_a_shorter_final_chunk(self) -> None:
        items = [f"P{i}" for i in range(7)]
        chunks = cc.shard(items, 3)
        assert chunks == [["P0", "P1", "P2"], ["P3", "P4", "P5"], ["P6"]]

    def test_size_greater_than_or_equal_to_len_returns_one_chunk(self) -> None:
        items = ["A", "B", "C"]
        assert cc.shard(items, 3) == [items]
        assert cc.shard(items, 10) == [items]

    def test_size_none_or_zero_means_no_cap(self) -> None:
        items = ["A", "B", "C"]
        assert cc.shard(items, None) == [items]
        assert cc.shard(items, 0) == [items]


class TestBackoffDelay:
    def test_doubles_each_attempt(self) -> None:
        assert cc.backoff_delay(0) == 1.0
        assert cc.backoff_delay(1) == 2.0
        assert cc.backoff_delay(2) == 4.0
        assert cc.backoff_delay(3) == 8.0

    def test_capped(self) -> None:
        assert cc.backoff_delay(6) == 60.0
        assert cc.backoff_delay(20) == 60.0

    def test_custom_base_and_cap(self) -> None:
        assert cc.backoff_delay(0, base=0.5, cap=10.0) == 0.5
        assert cc.backoff_delay(10, base=0.5, cap=10.0) == 10.0


class TestRowThrottle:
    def test_allows_first_row(self) -> None:
        t = cc.RowThrottle(interval_s=1.0)
        assert t.allow("BTC/USD", 100.0) is True

    def test_suppresses_within_interval(self) -> None:
        t = cc.RowThrottle(interval_s=1.0)
        t.allow("BTC/USD", 100.0)
        assert t.allow("BTC/USD", 100.5) is False
        assert t.allow("BTC/USD", 100.999) is False

    def test_allows_again_after_interval_elapses(self) -> None:
        t = cc.RowThrottle(interval_s=1.0)
        t.allow("BTC/USD", 100.0)
        assert t.allow("BTC/USD", 101.0) is True

    def test_keys_are_independent(self) -> None:
        t = cc.RowThrottle(interval_s=1.0)
        assert t.allow("BTC/USD", 100.0) is True
        assert t.allow("ETH/USD", 100.1) is True
        assert t.allow("BTC/USD", 100.5) is False
        assert t.allow("ETH/USD", 100.5) is False


class TestPartitionedParquetSink:
    TS = datetime(2026, 8, 8, 9, 5, tzinfo=UTC)

    def test_flush_writes_a_readable_part_file_with_exact_columns(self, tmp_path: Path) -> None:
        import pyarrow.parquet as pq

        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        sink.add("BTC/USD", "trades", {"ts": "t1", "price": 1.0, "qty": 2.0}, self.TS)
        sink.add("BTC/USD", "trades", {"ts": "t2", "price": 1.1, "qty": 2.1}, self.TS)
        n = sink.flush("BTC/USD", "trades")
        assert n == 2

        path = cc.hour_file_path(tmp_path, "BTC/USD", "trades", self.TS, part=0, partition=False)
        assert path.exists()
        table = pq.read_table(path)
        assert table.num_rows == 2
        assert set(table.column_names) == {"ts", "price", "qty"}
        assert table.column("price").to_pylist() == [1.0, 1.1]

    def test_part_numbers_increment_per_symbol_stream_independently(self, tmp_path: Path) -> None:
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        sink.add("BTC/USD", "trades", {"ts": "t1", "price": 1.0}, self.TS)
        sink.flush("BTC/USD", "trades")
        sink.add("BTC/USD", "trades", {"ts": "t2", "price": 2.0}, self.TS)
        sink.flush("BTC/USD", "trades")

        p0 = cc.hour_file_path(tmp_path, "BTC/USD", "trades", self.TS, part=0, partition=False)
        p1 = cc.hour_file_path(tmp_path, "BTC/USD", "trades", self.TS, part=1, partition=False)
        assert p0.exists()
        assert p1.exists()

    def test_part_numbers_do_not_collide_across_symbols_or_streams(self, tmp_path: Path) -> None:
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        sink.add("BTC/USD", "trades", {"ts": "t1", "price": 1.0}, self.TS)
        sink.add("ETH/USD", "trades", {"ts": "t1", "price": 2.0}, self.TS)
        sink.add("BTC/USD", "book", {"ts": "t1", "bid": 1.0}, self.TS)
        sink.flush("BTC/USD", "trades")
        sink.flush("ETH/USD", "trades")
        sink.flush("BTC/USD", "book")

        # each (symbol, stream) buffer starts its own part sequence at 0
        assert cc.hour_file_path(
            tmp_path, "BTC/USD", "trades", self.TS, part=0, partition=False
        ).exists()
        assert cc.hour_file_path(
            tmp_path, "ETH/USD", "trades", self.TS, part=0, partition=False
        ).exists()
        assert cc.hour_file_path(
            tmp_path, "BTC/USD", "book", self.TS, part=0, partition=False
        ).exists()

    def test_add_auto_flushes_at_flush_row_limit(self, tmp_path: Path) -> None:
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        for i in range(cc.FLUSH_ROW_LIMIT):
            sink.add("BTC/USD", "trades", {"ts": str(i), "price": float(i)}, self.TS)
        # limit reached mid-loop -> exactly one auto-flush happened, buffer now empty
        assert sink.buffered_rows() == 0
        assert sink.rows_written == cc.FLUSH_ROW_LIMIT
        assert cc.hour_file_path(
            tmp_path, "BTC/USD", "trades", self.TS, part=0, partition=False
        ).exists()

    def test_quiet_buffer_waits_rather_than_writing_a_tiny_file(self, tmp_path: Path) -> None:
        # A handful of rows does not earn a parquet file: at 232 symbols the
        # fixed per-file overhead dominated everything (measured 6 rows/file,
        # 572 bytes/row vs 126 on the same schema elsewhere). The guarantees
        # that keep this from becoming the old data-loss bug are bounded
        # waiting and forced drains — pinned in the three tests below.
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        sink.add("QUIET/USD", "trades", {"ts": "t1", "price": 3.0}, self.TS)
        assert sink.flush_all(self.TS) == 0
        assert sink.buffered_rows() == 1

    def test_quiet_buffer_is_flushed_once_it_exceeds_max_age(self, tmp_path: Path) -> None:
        # The bound that replaces "drains everything": no row waits longer
        # than MAX_BUFFER_AGE_S, so a crash can lose at most that much.
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        sink.add("QUIET/USD", "trades", {"ts": "t1", "price": 3.0}, self.TS)
        later = self.TS + timedelta(seconds=cc.MAX_BUFFER_AGE_S + 1)
        assert sink.flush_all(later) == 1
        assert sink.buffered_rows() == 0

    def test_quiet_buffer_is_flushed_before_crossing_an_hour(self, tmp_path: Path) -> None:
        # Filing is by event time now, so a straggler can no longer be
        # misfiled — but holding it keeps a closed hour out of compaction's
        # reach indefinitely. Write it out at the boundary instead.
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        sink.add("QUIET/USD", "trades", {"ts": "t1", "price": 3.0}, self.TS)
        next_hour = self.TS + timedelta(hours=1)
        assert sink.flush_all(next_hour) == 1
        assert sink.buffered_rows() == 0

    def test_force_drains_every_buffer_including_quiet_ones(self, tmp_path: Path) -> None:
        # Shutdown path: a small buffer is better written than lost.
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        sink.add("BTC/USD", "trades", {"ts": "t1", "price": 1.0}, self.TS)
        sink.add("ETH/USD", "trades", {"ts": "t1", "price": 2.0}, self.TS)
        sink.add("QUIET/USD", "trades", {"ts": "t1", "price": 3.0}, self.TS)

        assert sink.flush_all(self.TS, force=True) == 3
        assert sink.buffered_rows() == 0
        for sym in ("BTC/USD", "ETH/USD", "QUIET/USD"):
            assert cc.hour_file_path(
                tmp_path, sym, "trades", self.TS, part=0, partition=False
            ).exists()

    def test_busy_buffer_flushes_immediately_at_min_part_rows(self, tmp_path: Path) -> None:
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        for i in range(cc.MIN_PART_ROWS):
            sink.add("BTC/USD", "trades", {"ts": f"t{i}", "price": 1.0}, self.TS)
        assert sink.flush_all(self.TS) == cc.MIN_PART_ROWS

    def test_flushing_an_empty_buffer_is_a_noop_returning_zero(self, tmp_path: Path) -> None:
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        sink.add("BTC/USD", "trades", {"ts": "t1", "price": 1.0}, self.TS)
        sink.flush("BTC/USD", "trades")
        # buffer now empty; flushing again must be a no-op, no new part file
        n = sink.flush("BTC/USD", "trades")
        assert n == 0
        assert not cc.hour_file_path(
            tmp_path, "BTC/USD", "trades", self.TS, part=1, partition=False
        ).exists()

    def test_flushing_a_never_touched_key_is_a_noop(self, tmp_path: Path) -> None:
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        assert sink.flush("NEVER/USD", "trades") == 0

    def test_buffered_rows_and_rows_written_accounting(self, tmp_path: Path) -> None:
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        sink.add("BTC/USD", "trades", {"ts": "t1", "price": 1.0}, self.TS)
        sink.add("BTC/USD", "trades", {"ts": "t2", "price": 2.0}, self.TS)
        sink.add("ETH/USD", "trades", {"ts": "t3", "price": 3.0}, self.TS)
        assert sink.buffered_rows() == 3
        assert sink.rows_written == 0

        sink.flush("BTC/USD", "trades")
        assert sink.buffered_rows() == 1
        assert sink.rows_written == 2

        sink.flush("ETH/USD", "trades")
        assert sink.buffered_rows() == 0
        assert sink.rows_written == 3


class TestPartitionedParquetSinkPartNumberingAcrossInstances:
    """`_next_part` seeds from disk (max existing + 1) rather than trusting an
    in-memory counter alone. Regression coverage for the data-loss bug fixed
    2026-08-08: a second sink instance writing the same hour used to rewrite
    part-0000 over the first instance's rows with no error. See
    docs/FRICTION.md 2026-08-08 entry."""

    TS = datetime(2026, 8, 8, 11, 5, tzinfo=UTC)

    def test_regression_separate_sink_instances_same_hour_all_rows_survive(
        self, tmp_path: Path
    ) -> None:
        import pyarrow.parquet as pq

        for i in range(3):
            sink = cc.PartitionedParquetSink(tmp_path, partition=False)
            sink.add("BTC/USD", "trades", {"ts": f"t{i}", "price": float(i)}, self.TS)
            sink.flush("BTC/USD", "trades")

        day_dir = cc.stream_dir(tmp_path, "BTC/USD", self.TS, partition=False)
        parts = cc.part_files(day_dir, "trades", self.TS.hour)
        assert len(parts) == 3  # three distinct part files, none overwritten

        all_ts = set()
        for p in parts:
            all_ts.update(pq.read_table(p).column("ts").to_pylist())
        assert all_ts == {"t0", "t1", "t2"}  # every row from every instance survived

    def test_part_numbering_restarts_at_zero_for_a_new_hour(self, tmp_path: Path) -> None:
        hour_11 = self.TS
        hour_12 = self.TS.replace(hour=12)
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        for i in range(3):
            sink.add("BTC/USD", "trades", {"ts": f"h11-{i}", "price": float(i)}, hour_11)
            sink.flush("BTC/USD", "trades")
        assert cc.hour_file_path(
            tmp_path, "BTC/USD", "trades", hour_11, part=2, partition=False
        ).exists()

        sink.add("BTC/USD", "trades", {"ts": "h12-0", "price": 0.0}, hour_12)
        sink.flush("BTC/USD", "trades")

        assert cc.hour_file_path(
            tmp_path, "BTC/USD", "trades", hour_12, part=0, partition=False
        ).exists()

    def test_numbering_independent_per_symbol_and_stream_across_instances(
        self, tmp_path: Path
    ) -> None:
        # Two fresh sinks, one per (symbol, stream), both writing hour 11:
        # each must independently seed to 0 rather than sharing a counter.
        sink_a = cc.PartitionedParquetSink(tmp_path, partition=False)
        sink_a.add("BTC/USD", "trades", {"ts": "a", "price": 1.0}, self.TS)
        sink_a.flush("BTC/USD", "trades")

        sink_b = cc.PartitionedParquetSink(tmp_path, partition=False)
        sink_b.add("ETH/USD", "trades", {"ts": "b", "price": 2.0}, self.TS)
        sink_b.flush("ETH/USD", "trades")

        sink_c = cc.PartitionedParquetSink(tmp_path, partition=False)
        sink_c.add("BTC/USD", "book", {"ts": "c", "bid": 3.0}, self.TS)
        sink_c.flush("BTC/USD", "book")

        assert cc.hour_file_path(
            tmp_path, "BTC/USD", "trades", self.TS, part=0, partition=False
        ).exists()
        assert cc.hour_file_path(
            tmp_path, "ETH/USD", "trades", self.TS, part=0, partition=False
        ).exists()
        assert cc.hour_file_path(
            tmp_path, "BTC/USD", "book", self.TS, part=0, partition=False
        ).exists()

    def test_seeding_skips_malformed_part_filenames_without_raising(
        self, tmp_path: Path
    ) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        day_dir = cc.stream_dir(tmp_path, "BTC/USD", self.TS, partition=False)
        day_dir.mkdir(parents=True)
        # a real part already on disk, part-0000
        pq.write_table(
            pa.Table.from_pylist([{"ts": "existing", "price": 1.0}]),
            day_dir / "trades-11.part-0000.parquet",
        )
        # junk that must be tolerated, not crash the seed scan
        (day_dir / "trades-11.part-XXXX.parquet").write_bytes(b"not a part file")
        (day_dir / "trades-11.notapart.parquet").write_bytes(b"also junk")

        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        sink.add("BTC/USD", "trades", {"ts": "new", "price": 2.0}, self.TS)
        n = sink.flush("BTC/USD", "trades")  # must not raise

        assert n == 1
        # continues from the real part (0000 -> 0001), ignoring the junk
        assert (day_dir / "trades-11.part-0001.parquet").exists()

    def test_compact_then_new_sink_writes_more_then_compact_again_no_loss(
        self, tmp_path: Path
    ) -> None:
        import pyarrow.parquet as pq

        day_dir = cc.stream_dir(tmp_path, "BTC/USD", self.TS, partition=False)

        sink1 = cc.PartitionedParquetSink(tmp_path, partition=False)
        sink1.add("BTC/USD", "trades", {"ts": "t1", "price": 1.0}, self.TS)
        sink1.add("BTC/USD", "trades", {"ts": "t2", "price": 2.0}, self.TS)
        sink1.flush("BTC/USD", "trades")
        first_merge = cc.compact_hour(day_dir, "trades", self.TS.hour)
        assert first_merge == 2

        # simulates a watchdog-relaunched collector: a brand-new sink writes
        # more rows into the same (now-partially-compacted) hour
        sink2 = cc.PartitionedParquetSink(tmp_path, partition=False)
        sink2.add("BTC/USD", "trades", {"ts": "t3", "price": 3.0}, self.TS)
        sink2.flush("BTC/USD", "trades")
        second_merge = cc.compact_hour(day_dir, "trades", self.TS.hour)

        assert second_merge == 3  # 2 previously-compacted rows + 1 new, none lost
        table = pq.read_table(day_dir / "trades-11.parquet")
        assert sorted(table.column("ts").to_pylist()) == ["t1", "t2", "t3"]
        assert cc.part_files(day_dir, "trades", self.TS.hour) == []

    def test_long_lived_sink_numbers_sequentially_without_rescanning_disk(
        self, tmp_path: Path
    ) -> None:
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        sink.add("BTC/USD", "trades", {"ts": "t0", "price": 0.0}, self.TS)
        sink.flush("BTC/USD", "trades")
        part0 = cc.hour_file_path(
            tmp_path, "BTC/USD", "trades", self.TS, part=0, partition=False
        )
        assert part0.exists()

        # Remove the part file from disk after the first flush seeded the
        # in-memory counter. If numbering re-scanned disk on every flush, the
        # next write would see an empty directory and collide back at
        # part-0000; a memoised counter instead continues at part-0001.
        part0.unlink()

        sink.add("BTC/USD", "trades", {"ts": "t1", "price": 1.0}, self.TS)
        sink.flush("BTC/USD", "trades")

        assert cc.hour_file_path(
            tmp_path, "BTC/USD", "trades", self.TS, part=1, partition=False
        ).exists()
        assert not part0.exists()


class TestCompactHour:
    TS = datetime(2026, 8, 8, 9, 5, tzinfo=UTC)

    def _make_sink(self, tmp_path: Path) -> cc.PartitionedParquetSink:
        return cc.PartitionedParquetSink(tmp_path, partition=False)

    def test_merges_parts_into_single_hourly_file_and_deletes_parts(
        self, tmp_path: Path
    ) -> None:
        import pyarrow.parquet as pq

        sink = self._make_sink(tmp_path)
        sink.add("BTC/USD", "trades", {"ts": "t1", "price": 1.0}, self.TS)
        sink.flush("BTC/USD", "trades")
        sink.add("BTC/USD", "trades", {"ts": "t2", "price": 2.0}, self.TS)
        sink.flush("BTC/USD", "trades")

        day_dir = cc.stream_dir(tmp_path, "BTC/USD", self.TS, partition=False)
        n = cc.compact_hour(day_dir, "trades", 9)

        assert n == 2
        merged = day_dir / "trades-09.parquet"
        assert merged.exists()
        table = pq.read_table(merged)
        assert table.num_rows == 2
        assert sorted(table.column("ts").to_pylist()) == ["t1", "t2"]
        # parts deleted
        assert cc.part_files(day_dir, "trades", 9) == []

    def test_no_parts_is_a_noop_returning_zero(self, tmp_path: Path) -> None:
        day_dir = tmp_path / "BTC_USD" / "2026-08-08"
        day_dir.mkdir(parents=True)
        assert cc.compact_hour(day_dir, "trades", 9) == 0

    def test_idempotent_second_run_is_safe(self, tmp_path: Path) -> None:
        sink = self._make_sink(tmp_path)
        sink.add("BTC/USD", "trades", {"ts": "t1", "price": 1.0}, self.TS)
        sink.flush("BTC/USD", "trades")
        day_dir = cc.stream_dir(tmp_path, "BTC/USD", self.TS, partition=False)

        first = cc.compact_hour(day_dir, "trades", 9)
        second = cc.compact_hour(day_dir, "trades", 9)

        assert first == 1
        assert second == 0  # nothing left to compact
        merged = day_dir / "trades-09.parquet"
        assert merged.exists()

    def test_merges_into_existing_compacted_file_without_losing_rows(
        self, tmp_path: Path
    ) -> None:
        import pyarrow.parquet as pq

        sink = self._make_sink(tmp_path)
        day_dir = cc.stream_dir(tmp_path, "BTC/USD", self.TS, partition=False)

        # first round: one part, compact it into the hourly file
        sink.add("BTC/USD", "trades", {"ts": "t1", "price": 1.0}, self.TS)
        sink.flush("BTC/USD", "trades")
        cc.compact_hour(day_dir, "trades", 9)

        # second round: new part arrives after the hourly file already exists
        sink.add("BTC/USD", "trades", {"ts": "t2", "price": 2.0}, self.TS)
        sink.flush("BTC/USD", "trades")
        n = cc.compact_hour(day_dir, "trades", 9)

        assert n == 2  # merged file now has both old + new rows
        table = pq.read_table(day_dir / "trades-09.parquet")
        assert sorted(table.column("ts").to_pylist()) == ["t1", "t2"]

    def test_unreadable_part_file_is_skipped_not_fatal(self, tmp_path: Path) -> None:
        import pyarrow.parquet as pq

        sink = self._make_sink(tmp_path)
        day_dir = cc.stream_dir(tmp_path, "BTC/USD", self.TS, partition=False)

        sink.add("BTC/USD", "trades", {"ts": "t1", "price": 1.0}, self.TS)
        sink.flush("BTC/USD", "trades")

        # simulate a part truncated by a hard kill
        garbage = day_dir / "trades-09.part-0001.parquet"
        garbage.write_bytes(b"not a parquet file")

        n = cc.compact_hour(day_dir, "trades", 9)

        assert n == 1  # only the good row landed
        table = pq.read_table(day_dir / "trades-09.parquet")
        assert table.column("ts").to_pylist() == ["t1"]
        # the garbage part is left behind (unlink happens for the full `parts`
        # list, which includes the garbage file since it matched the glob)
        assert not garbage.exists()


class TestCompactClosedHours:
    def test_skips_current_hour(self, tmp_path: Path) -> None:
        now = datetime(2026, 8, 8, 9, 30, tzinfo=UTC)
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        sink.add("BTC/USD", "trades", {"ts": "t1", "price": 1.0}, now)
        sink.flush("BTC/USD", "trades")

        merged = cc.compact_closed_hours(tmp_path, now=now)

        assert merged == 0
        day_dir = cc.stream_dir(tmp_path, "BTC/USD", now, partition=False)
        assert cc.part_files(day_dir, "trades", 9) != []  # untouched
        assert not (day_dir / "trades-09.parquet").exists()

    def test_compacts_past_hours(self, tmp_path: Path) -> None:
        past = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
        now = datetime(2026, 8, 8, 9, 30, tzinfo=UTC)
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        sink.add("BTC/USD", "trades", {"ts": "t1", "price": 1.0}, past)
        sink.flush("BTC/USD", "trades")

        merged = cc.compact_closed_hours(tmp_path, now=now)

        assert merged == 1
        day_dir = cc.stream_dir(tmp_path, "BTC/USD", past, partition=False)
        assert (day_dir / "trades-08.parquet").exists()
        assert cc.part_files(day_dir, "trades", 8) == []

    def test_compacts_multiple_streams_and_symbols_but_not_current_hour(
        self, tmp_path: Path
    ) -> None:
        past = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
        now = datetime(2026, 8, 8, 9, 30, tzinfo=UTC)
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        sink.add("BTC/USD", "trades", {"ts": "t1", "price": 1.0}, past)
        sink.flush("BTC/USD", "trades")
        sink.add("ETH/USD", "book", {"ts": "t1", "bid": 1.0}, past)
        sink.flush("ETH/USD", "book")
        sink.add("BTC/USD", "trades", {"ts": "t2", "price": 2.0}, now)
        sink.flush("BTC/USD", "trades")

        merged = cc.compact_closed_hours(tmp_path, now=now)

        assert merged == 2
        btc_day = cc.stream_dir(tmp_path, "BTC/USD", past, partition=False)
        eth_day = cc.stream_dir(tmp_path, "ETH/USD", past, partition=False)
        assert (btc_day / "trades-08.parquet").exists()
        assert (eth_day / "book-08.parquet").exists()
        # current-hour part for BTC/USD trades is untouched
        now_day = cc.stream_dir(tmp_path, "BTC/USD", now, partition=False)
        assert not (now_day / "trades-09.parquet").exists()


class TestStreamNameGuard:
    """Regression coverage for the second data-loss bug fixed 2026-08-08:
    `_PART_RE` was anchored to `[a-z_]+`, so a stream name with a capital
    letter or a digit ("aggTrades", "book5") matched nothing. `part_files()`
    then returned empty for parts that were genuinely on disk, which broke
    BOTH consumers silently: `compact_hour` became a permanent no-op, and
    `_next_part` always saw zero existing parts and returned 0, so every
    flush overwrote part-0000. Verified before the fix: three sink instances
    writing stream "aggTrades" to the same hour left ONE file with only the
    last row — no error either time. `_assert_stream_name` now makes that
    class of bug loud. See docs/FRICTION.md 2026-08-08 entries."""

    TS = datetime(2026, 8, 8, 13, 5, tzinfo=UTC)

    @pytest.mark.parametrize(
        "stream",
        ["trades", "book", "ctx", "aggTrades", "book5", "orderbook", "open_interest"],
    )
    def test_regression_stream_name_survives_across_instances_and_compacts(
        self, tmp_path: Path, stream: str
    ) -> None:
        import pyarrow.parquet as pq

        for i in range(3):
            sink = cc.PartitionedParquetSink(tmp_path, partition=False)
            sink.add("BTC/USD", stream, {"ts": f"t{i}", "price": float(i)}, self.TS)
            sink.flush("BTC/USD", stream)

        day_dir = cc.stream_dir(tmp_path, "BTC/USD", self.TS, partition=False)
        parts = cc.part_files(day_dir, stream, self.TS.hour)
        assert len(parts) == 3  # three distinct part files, none overwritten

        all_ts = set()
        for p in parts:
            all_ts.update(pq.read_table(p).column("ts").to_pylist())
        assert all_ts == {"t0", "t1", "t2"}  # every row from every instance survived

        merged = cc.compact_hour(day_dir, stream, self.TS.hour)
        assert merged == 3  # compact_hour is not a silent no-op for this name

    def test_part_files_finds_parts_for_a_mixed_case_stream_name(self, tmp_path: Path) -> None:
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        sink.add("BTC/USD", "aggTrades", {"ts": "t1", "price": 1.0}, self.TS)
        sink.flush("BTC/USD", "aggTrades")

        day_dir = cc.stream_dir(tmp_path, "BTC/USD", self.TS, partition=False)
        parts = cc.part_files(day_dir, "aggTrades", self.TS.hour)
        assert len(parts) == 1
        assert parts[0].name == "aggTrades-13.part-0000.parquet"

    @pytest.mark.parametrize("bad_stream", ["agg-trades", "book.5"])
    def test_stream_name_with_dash_or_dot_raises_on_add(
        self, tmp_path: Path, bad_stream: str
    ) -> None:
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        with pytest.raises(ValueError):
            sink.add("BTC/USD", bad_stream, {"ts": "t1", "price": 1.0}, self.TS)

    @pytest.mark.parametrize(
        "good_stream", ["trades", "book", "aggTrades", "book5", "open_interest"]
    )
    def test_valid_stream_names_do_not_raise_on_add(
        self, tmp_path: Path, good_stream: str
    ) -> None:
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        sink.add("BTC/USD", good_stream, {"ts": "t1", "price": 1.0}, self.TS)  # must not raise
        assert sink.buffered_rows() == 1

    def test_guard_fires_on_the_first_add_before_anything_is_written(
        self, tmp_path: Path
    ) -> None:
        # A bad name must never silently write anything — the guard fires on
        # the very first add for a (symbol, stream), before any row is even
        # buffered, let alone flushed to disk.
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        with pytest.raises(ValueError):
            sink.add("BTC/USD", "agg-trades", {"ts": "t1", "price": 1.0}, self.TS)
        assert sink.buffered_rows() == 0
        assert sink.flush_all(self.TS, force=True) == 0
        day_dir = cc.stream_dir(tmp_path, "BTC/USD", self.TS, partition=False)
        assert not day_dir.exists()


class _FakeWsConnection:
    """Stands in for a `websockets.connect(...)` async context manager.

    `recv()` returns queued frames in order, then blocks (never resolving
    within any timeout used here) so `run_ws_collector`'s heartbeat/keepalive
    polling loop drives its own timing deterministically instead of racing a
    real socket.
    """

    def __init__(self) -> None:
        self.sent: list[str] = []
        self._frames: list[str] = []

    def queue(self, *frames: str) -> None:
        self._frames.extend(frames)

    async def __aenter__(self) -> _FakeWsConnection:
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def recv(self) -> str:
        if self._frames:
            return self._frames.pop(0)
        await asyncio.sleep(3600)  # never resolves inside any test timeout
        raise AssertionError("unreachable")  # pragma: no cover


class _FakeConnectFactory:
    """Replaces `websockets.connect`; hands out fresh connections per call so
    reconnects are observable via `.calls`."""

    def __init__(self, make_conn: Callable[[], _FakeWsConnection]) -> None:
        self.calls = 0
        self._make_conn = make_conn

    def __call__(self, url: str, **kwargs: object) -> _FakeWsConnection:
        self.calls += 1
        return self._make_conn()


def _trade_spec(**overrides: object) -> cc.VenueSpec:
    def parse(msg: dict, now: datetime) -> list:
        if msg.get("type") != "trade":
            return []
        return [("BTC/USD", "trades", {"ts": now.isoformat(), "price": msg["price"]})]

    defaults: dict[str, object] = dict(
        name="fake",
        ws_url="wss://fake.example",
        subscribe=lambda symbols: [{"type": "subscribe", "symbols": symbols}],
        parse=parse,
        heartbeat_timeout_s=0.08,
    )
    defaults.update(overrides)
    return cc.VenueSpec(**defaults)


class TestRunWsCollectorKeepaliveAndLiveness:
    """No network: `websockets.connect` is monkeypatched to a fake connection
    so the reconnect/keepalive/liveness logic in `run_ws_collector` runs for
    real against deterministic, queued frames.

    Regression coverage for the OKX idle-close bug fixed 2026-08-08: OKX
    closes a connection ~30s idle and does not honour protocol-level pings,
    so the sparse liquidation feed reconnected ~10x/240s. Fixed by an
    application-level `keepalive_text` sent on a schedule, liveness judged by
    time since the last MESSAGE rather than any single recv timing out, and
    tolerating a non-JSON reply (OKX answers "ping" with a bare "pong")."""

    def test_non_json_frame_does_not_abort_the_loop_and_next_frame_still_lands(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json as json_mod

        conn = _FakeWsConnection()
        conn.queue("pong", json_mod.dumps({"type": "trade", "price": 100.0}))
        factory = _FakeConnectFactory(lambda: conn)
        import websockets

        monkeypatch.setattr(websockets, "connect", factory)

        spec = _trade_spec(heartbeat_timeout_s=5.0)
        counts = asyncio.run(
            cc.run_ws_collector(spec, ["BTC/USD"], tmp_path, duration_s=0.2, partition=False)
        )

        assert counts["BTC/USD"] == 1  # the non-JSON frame didn't crash parsing
        assert factory.calls == 1  # and didn't force a reconnect either

        day_dir = cc.stream_dir(tmp_path, "BTC/USD", datetime.now(UTC), partition=False)
        assert cc.part_files(day_dir, "trades", datetime.now(UTC).hour) or list(
            day_dir.rglob("trades-*.parquet")
        )  # forced flush on shutdown actually wrote the row

    def test_keepalive_text_is_sent_when_configured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = _FakeWsConnection()
        factory = _FakeConnectFactory(lambda: conn)
        import websockets

        monkeypatch.setattr(websockets, "connect", factory)

        spec = _trade_spec(
            heartbeat_timeout_s=5.0, keepalive_text="ping", keepalive_interval_s=0.05
        )
        asyncio.run(
            cc.run_ws_collector(spec, ["BTC/USD"], tmp_path, duration_s=0.2, partition=False)
        )

        assert "ping" in conn.sent

    def test_no_keepalive_text_means_no_extra_sends(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = _FakeWsConnection()
        factory = _FakeConnectFactory(lambda: conn)
        import websockets

        monkeypatch.setattr(websockets, "connect", factory)

        spec = _trade_spec(heartbeat_timeout_s=5.0)  # keepalive_text=None (default)
        asyncio.run(
            cc.run_ws_collector(spec, ["BTC/USD"], tmp_path, duration_s=0.2, partition=False)
        )

        # only the initial subscribe payload was ever sent
        assert len(conn.sent) == 1

    def test_recv_timeouts_shorter_than_heartbeat_do_not_trigger_a_reconnect(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = _FakeWsConnection()
        factory = _FakeConnectFactory(lambda: conn)
        import websockets

        monkeypatch.setattr(websockets, "connect", factory)

        # heartbeat_timeout_s is generous relative to duration_s: several recv
        # slices will individually time out, but total elapsed time never
        # reaches the heartbeat threshold, so the connection must not drop.
        spec = _trade_spec(heartbeat_timeout_s=1.0)
        asyncio.run(
            cc.run_ws_collector(spec, ["BTC/USD"], tmp_path, duration_s=0.15, partition=False)
        )

        assert factory.calls == 1  # never reconnected

    def test_recv_timeout_exceeding_heartbeat_triggers_a_reconnect(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = _FakeWsConnection()
        factory = _FakeConnectFactory(lambda: conn)
        import websockets

        monkeypatch.setattr(websockets, "connect", factory)

        # heartbeat_timeout_s is short relative to duration_s: silence past
        # the threshold must force at least one reconnect.
        spec = _trade_spec(heartbeat_timeout_s=0.05)
        asyncio.run(
            cc.run_ws_collector(spec, ["BTC/USD"], tmp_path, duration_s=0.3, partition=False)
        )

        assert factory.calls > 1  # reconnected at least once


class TestPartitionedParquetSinkEventTimePartitioning:
    """Every row must land in the day/hour ITS OWN timestamp names.

    Regression cover for the archive-wide misfiling found 2026-08-09: the sink
    named the target file from FLUSH time, so a row's on-disk hour recorded
    when we ingested it rather than when it happened. On the live websocket
    feeds those two are close enough that it only leaked at hour boundaries
    (~0.7% of rows), but on the delayed Alpaca poller they diverge by design
    and 100% of a weekend's rows were filed under the wrong day. Measured over
    5,150,262 stored equity prints: 14.7-18.5% wrong-hour on trading days.

    Hour-partitioning that cannot be trusted is worse than none — it invites
    time-ranged reads that silently return the wrong rows.
    """

    DAY = datetime(2026, 8, 8, tzinfo=UTC)

    @staticmethod
    def _rows_at(path: Path) -> list[dict[str, object]]:
        import pyarrow.parquet as pq

        return pq.read_table(path).to_pylist()

    def test_regression_rows_are_filed_by_their_own_event_hour_not_the_flush_hour(
        self, tmp_path: Path
    ) -> None:
        # Discriminating: filing by flush time puts all five rows in hour 12;
        # filing by the buffer's first row puts all five in hour 10. Only
        # per-row event time produces 3-in-10 and 2-in-11 with nothing in 12.
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        for i in range(3):
            ts = self.DAY.replace(hour=10, minute=i)
            sink.add("BTC/USD", "trades", {"ts": ts.isoformat(), "price": float(i)}, ts)
        for i in range(2):
            ts = self.DAY.replace(hour=11, minute=i)
            sink.add("BTC/USD", "trades", {"ts": ts.isoformat(), "price": 100.0 + i}, ts)

        flushed_at = self.DAY.replace(hour=12)
        assert sink.flush_all(flushed_at, force=True) == 5

        h10 = cc.hour_file_path(
            tmp_path, "BTC/USD", "trades", self.DAY.replace(hour=10), part=0, partition=False
        )
        h11 = cc.hour_file_path(
            tmp_path, "BTC/USD", "trades", self.DAY.replace(hour=11), part=0, partition=False
        )
        h12 = cc.hour_file_path(
            tmp_path, "BTC/USD", "trades", flushed_at, part=0, partition=False
        )
        assert [r["price"] for r in self._rows_at(h10)] == [0.0, 1.0, 2.0]
        assert [r["price"] for r in self._rows_at(h11)] == [100.0, 101.0]
        assert not h12.exists()

    def test_rows_spanning_a_day_boundary_land_in_their_own_day_directories(
        self, tmp_path: Path
    ) -> None:
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        late = self.DAY.replace(hour=23, minute=59)
        early = self.DAY + timedelta(days=1, minutes=1)
        sink.add("BTC/USD", "trades", {"ts": late.isoformat(), "price": 1.0}, late)
        sink.add("BTC/USD", "trades", {"ts": early.isoformat(), "price": 2.0}, early)
        sink.flush_all(early + timedelta(hours=2), force=True)

        d1 = cc.hour_file_path(tmp_path, "BTC/USD", "trades", late, part=0, partition=False)
        d2 = cc.hour_file_path(tmp_path, "BTC/USD", "trades", early, part=0, partition=False)
        assert d1.parent.name == "2026-08-08"
        assert d2.parent.name == "2026-08-09"
        assert [r["price"] for r in self._rows_at(d1)] == [1.0]
        assert [r["price"] for r in self._rows_at(d2)] == [2.0]

    def test_regression_a_two_day_old_backfill_does_not_land_in_the_ingest_hour(
        self, tmp_path: Path
    ) -> None:
        # The delayed-poller shape: a batch fetched now but stamped days ago.
        # This is the case that put a whole Friday tape under Sunday's date.
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        event = self.DAY.replace(hour=19, minute=30)
        ingest = self.DAY + timedelta(days=2, hours=3)
        sink.add("RIOT", "trades", {"ts": event.isoformat(), "price": 9.0}, event)
        sink.flush_all(ingest, force=True)

        written = list(tmp_path.rglob("*.parquet"))
        assert len(written) == 1
        assert written[0].parent.name == "2026-08-08"
        assert written[0].name == "trades-19.part-0000.parquet"

    def test_part_numbering_is_independent_per_target_hour(self, tmp_path: Path) -> None:
        # A single shared counter would emit part-0000 and part-0001 across two
        # different hours, then collide or skip on the next flush.
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        for round_ in range(2):
            for hour in (10, 11):
                ts = self.DAY.replace(hour=hour, minute=round_)
                sink.add("BTC/USD", "trades", {"ts": ts.isoformat(), "price": 1.0}, ts)
            sink.flush_all(self.DAY.replace(hour=12), force=True)

        for hour in (10, 11):
            at = self.DAY.replace(hour=hour)
            for part in (0, 1):
                assert cc.hour_file_path(
                    tmp_path, "BTC/USD", "trades", at, part=part, partition=False
                ).exists(), f"hour {hour} part {part} missing"

    def test_row_order_within_an_hour_survives_the_split(self, tmp_path: Path) -> None:
        # Grouping must be stable: interleaved arrival, per-hour order kept.
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        for i in range(6):
            ts = self.DAY.replace(hour=10 + i % 2, minute=i)
            sink.add("BTC/USD", "trades", {"ts": ts.isoformat(), "price": float(i)}, ts)
        sink.flush_all(self.DAY.replace(hour=13), force=True)

        h10 = cc.hour_file_path(
            tmp_path, "BTC/USD", "trades", self.DAY.replace(hour=10), part=0, partition=False
        )
        h11 = cc.hour_file_path(
            tmp_path, "BTC/USD", "trades", self.DAY.replace(hour=11), part=0, partition=False
        )
        assert [r["price"] for r in self._rows_at(h10)] == [0.0, 2.0, 4.0]
        assert [r["price"] for r in self._rows_at(h11)] == [1.0, 3.0, 5.0]

    def test_rows_written_accounting_covers_every_hour_the_flush_split_into(
        self, tmp_path: Path
    ) -> None:
        sink = cc.PartitionedParquetSink(tmp_path, partition=False)
        for hour in (8, 9, 10):
            ts = self.DAY.replace(hour=hour)
            sink.add("BTC/USD", "trades", {"ts": ts.isoformat(), "price": 1.0}, ts)
        assert sink.flush("BTC/USD", "trades") == 3
        assert sink.rows_written == 3
        assert sink.buffered_rows() == 0
