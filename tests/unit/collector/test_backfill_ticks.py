"""Pure-logic tests for scripts/backfill_ticks.py.

No network — gap detection over a fake directory tree, REST-tuple ->
row mapping, the skip-existing-hour rule, and pagination cursor
handling from canned response dicts. Style mirrors
tests/unit/collector/test_collect_ticks.py.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import backfill_ticks as bt


def _mk_hour(base: Path, pair: str, day: str, hh: int) -> None:
    # Directory derived from the writer's own layout helper (asset-class
    # partitioned), not a private flat join — see bt.present_trade_hours.
    day_dt = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC)
    d = bt.ct.trade_file_path(base, pair, day_dt).parent
    d.mkdir(parents=True, exist_ok=True)
    (d / f"trades-{hh:02d}.parquet").touch()


class TestGapDetection:
    def test_present_trade_hours_reads_tree(self, tmp_path: Path) -> None:
        _mk_hour(tmp_path, "ETH/USD", "2026-07-19", 13)
        _mk_hour(tmp_path, "ETH/USD", "2026-07-20", 0)
        hours = bt.present_trade_hours(tmp_path, "ETH/USD")
        assert hours == {
            datetime(2026, 7, 19, 13, tzinfo=UTC),
            datetime(2026, 7, 20, 0, tzinfo=UTC),
        }

    def test_present_ignores_book_files_and_junk_dirs(self, tmp_path: Path) -> None:
        day_dt = datetime(2026, 7, 19, tzinfo=UTC)
        d = bt.ct.trade_file_path(tmp_path, "ETH/USD", day_dt).parent
        d.mkdir(parents=True)
        (d / "book-05.parquet").touch()
        (d.parent / "not-a-date").mkdir()
        assert bt.present_trade_hours(tmp_path, "ETH/USD") == set()

    def test_missing_hours_between_first_and_now(self) -> None:
        present = {
            datetime(2026, 7, 19, 13, tzinfo=UTC),
            datetime(2026, 7, 19, 16, tzinfo=UTC),
        }
        now = datetime(2026, 7, 19, 17, 30, tzinfo=UTC)
        assert bt.missing_hours(present, now) == [
            datetime(2026, 7, 19, 14, tzinfo=UTC),
            datetime(2026, 7, 19, 15, tzinfo=UTC),
        ]

    def test_current_in_progress_hour_is_not_missing(self) -> None:
        present = {datetime(2026, 7, 19, 13, tzinfo=UTC)}
        now = datetime(2026, 7, 19, 14, 10, tzinfo=UTC)
        assert bt.missing_hours(present, now) == []

    def test_no_data_means_no_gaps(self) -> None:
        assert bt.missing_hours(set(), datetime(2026, 7, 19, tzinfo=UTC)) == []

    def test_gap_spans_groups_contiguous_hours(self) -> None:
        h = lambda hh: datetime(2026, 7, 19, hh, tzinfo=UTC)  # noqa: E731
        spans = bt.gap_spans([h(1), h(2), h(3), h(7), h(9), h(10)])
        assert spans == [(h(1), h(3)), (h(7), h(7)), (h(9), h(10))]


class TestRestMapping:
    def test_tuple_maps_to_collector_schema(self) -> None:
        t = ["2500.50000", "1.25000000", 1784900977.708706, "b", "m", "", 123]
        row = bt.rest_trade_to_row(t)
        assert row["price"] == 2500.5
        assert row["qty"] == 1.25
        assert row["side"] == "buy"
        assert row["ord_type"] == "market"
        assert row["ts"].endswith("Z")
        assert datetime.fromisoformat(row["ts"].replace("Z", "+00:00")) == datetime.fromtimestamp(
            1784900977.708706, tz=UTC
        )

    def test_sell_limit_mapping(self) -> None:
        row = bt.rest_trade_to_row(["100.1", "3.0", 1784900000.0, "s", "l", ""])
        assert row["side"] == "sell"
        assert row["ord_type"] == "limit"

    def test_bucket_rows_by_hour(self) -> None:
        rows = [
            bt.rest_trade_to_row(["1", "1", 1784901600.0, "b", "m", ""]),
            bt.rest_trade_to_row(["1", "1", 1784901660.0, "s", "l", ""]),
            bt.rest_trade_to_row(["1", "1", 1784905200.0, "b", "l", ""]),
        ]
        buckets = bt.bucket_rows_by_hour(rows)
        assert sorted(len(v) for v in buckets.values()) == [1, 2]
        assert all(h.minute == 0 and h.second == 0 for h in buckets)


class TestPagination:
    def test_parse_trades_response_rows_and_cursor(self) -> None:
        body = {
            "error": [],
            "result": {
                "XETHZUSD": [
                    ["2500.5", "1.0", 1784900977.1, "b", "m", ""],
                    ["2500.6", "2.0", 1784900978.2, "s", "l", ""],
                ],
                "last": "1784900978200000000",
            },
        }
        rows, last = bt.parse_trades_response(body, "XETHZUSD")
        assert len(rows) == 2
        assert last == "1784900978200000000"

    def test_parse_tolerates_alias_pair_key(self) -> None:
        body = {
            "error": [],
            "result": {"XXRPZUSD": [["0.5", "10", 1784900000.0, "b", "l", ""]], "last": "1"},
        }
        rows, last = bt.parse_trades_response(body, "XRPUSD")
        assert rows[0]["price"] == 0.5
        assert last == "1"

    def test_parse_raises_on_api_error(self) -> None:
        with pytest.raises(RuntimeError, match="EGeneral"):
            bt.parse_trades_response({"error": ["EGeneral:Invalid arguments"]}, "XETHZUSD")

    def test_cursor_advances_monotonically(self) -> None:
        # backfill_span's loop invariant: a `last` <= since must terminate
        # paging. Exercised via the pure pieces: cursor comparison.
        since_ns = 1784900977_000000000
        body = {
            "error": [],
            "result": {"XETHZUSD": [["1", "1", 1784900977.0, "b", "m", ""]], "last": str(since_ns)},
        }
        _, last = bt.parse_trades_response(body, "XETHZUSD")
        assert int(last) <= since_ns  # no progress -> caller must stop


class TestSkipExistingHour:
    def test_write_hour_skips_when_file_exists(self, tmp_path: Path) -> None:
        hour = datetime(2026, 7, 19, 14, tzinfo=UTC)
        path = bt.ct.trade_file_path(tmp_path, "ETH/USD", hour)
        path.parent.mkdir(parents=True)
        path.write_bytes(b"collected-data-wins")
        rows = [bt.rest_trade_to_row(["1", "1", hour.timestamp(), "b", "m", ""])]
        assert bt.write_hour(tmp_path, "ETH/USD", hour, rows) is False
        assert path.read_bytes() == b"collected-data-wins"

    def test_write_hour_writes_missing_hour(self, tmp_path: Path) -> None:
        pytest.importorskip("pyarrow")
        import pyarrow.parquet as pq

        hour = datetime(2026, 7, 19, 15, tzinfo=UTC)
        rows = [
            bt.rest_trade_to_row(["2500.5", "1.25", hour.timestamp() + 60, "b", "m", ""]),
        ]
        assert bt.write_hour(tmp_path, "ETH/USD", hour, rows) is True
        table = pq.read_table(bt.ct.trade_file_path(tmp_path, "ETH/USD", hour))
        assert table.column_names == ["ts", "price", "qty", "side", "ord_type"]
        assert table.num_rows == 1


class TestInventoryReport:
    def test_inventory_reports_gaps(self, tmp_path: Path, capsys) -> None:
        _mk_hour(tmp_path, "ETH/USD", "2026-07-19", 13)
        _mk_hour(tmp_path, "ETH/USD", "2026-07-19", 16)
        now = datetime(2026, 7, 19, 18, tzinfo=UTC)
        report = bt.inventory(tmp_path, pairs=["ETH/USD"], now=now)
        assert report["ETH/USD"]["missing"] == [
            datetime(2026, 7, 19, 14, tzinfo=UTC),
            datetime(2026, 7, 19, 15, tzinfo=UTC),
            datetime(2026, 7, 19, 17, tzinfo=UTC),
        ]
        assert report["ETH/USD"]["spans"] == [
            (datetime(2026, 7, 19, 14, tzinfo=UTC), datetime(2026, 7, 19, 15, tzinfo=UTC)),
            (datetime(2026, 7, 19, 17, tzinfo=UTC), datetime(2026, 7, 19, 17, tzinfo=UTC)),
        ]
        out = capsys.readouterr().out
        assert "ETH/USD" in out

    def test_inventory_handles_pair_with_no_data(self, tmp_path: Path) -> None:
        report = bt.inventory(tmp_path, pairs=["TAO/USD"])
        assert report["TAO/USD"]["missing"] == []


def test_missing_hours_span_multiple_days(tmp_path: Path) -> None:
    _mk_hour(tmp_path, "AKT/USD", "2026-07-19", 23)
    _mk_hour(tmp_path, "AKT/USD", "2026-07-21", 1)
    present = bt.present_trade_hours(tmp_path, "AKT/USD")
    miss = bt.missing_hours(present, datetime(2026, 7, 21, 2, tzinfo=UTC))
    assert len(miss) == 25
    assert miss[0] == datetime(2026, 7, 20, 0, tzinfo=UTC)
    assert miss[-1] == datetime(2026, 7, 21, 0, tzinfo=UTC)
    assert bt.gap_spans(miss) == [(miss[0], miss[-1])]


class TestBookAnchoredInventory:
    """CTO adjudication 2026-07-26: a pair with book files but zero trades
    files anchors its backfill on the earliest book hour — every hour from
    that anchor to now counts as missing."""

    def test_earliest_book_hour_found_across_days(self, tmp_path):
        d1 = bt.ct.book_file_path(tmp_path, "PAXG/USD", datetime(2026, 7, 21, tzinfo=UTC)).parent
        d2 = bt.ct.book_file_path(tmp_path, "PAXG/USD", datetime(2026, 7, 20, tzinfo=UTC)).parent
        d1.mkdir(parents=True)
        d2.mkdir(parents=True)
        (d1 / "book-03.parquet").touch()
        (d2 / "book-17.parquet").touch()
        assert bt.earliest_book_hour(tmp_path, "PAXG/USD") == datetime(
            2026, 7, 20, 17, tzinfo=UTC
        )

    def test_earliest_book_hour_none_without_book_files(self, tmp_path):
        bt.ct.book_file_path(
            tmp_path, "PAXG/USD", datetime(2026, 7, 20, tzinfo=UTC)
        ).parent.mkdir(parents=True)
        assert bt.earliest_book_hour(tmp_path, "PAXG/USD") is None

    def test_inventory_book_anchored_pair_reports_all_hours_missing(self, tmp_path, capsys):
        d = bt.ct.book_file_path(tmp_path, "PAXG/USD", datetime(2026, 7, 25, tzinfo=UTC)).parent
        d.mkdir(parents=True)
        (d / "book-10.parquet").touch()
        now = datetime(2026, 7, 25, 14, 30, tzinfo=UTC)
        report = bt.inventory(tmp_path, pairs=["PAXG/USD"], now=now)
        missing = report["PAXG/USD"]["missing"]
        assert missing[0] == datetime(2026, 7, 25, 10, tzinfo=UTC)
        assert missing[-1] == datetime(2026, 7, 25, 13, tzinfo=UTC)
        assert len(missing) == 4
        assert "(book-anchored)" in capsys.readouterr().out
