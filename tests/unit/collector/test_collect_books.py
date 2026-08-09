"""Pure-logic tests for scripts/collect_books_binance.py and
scripts/collect_books_coinbase.py.

No network, no websockets/pyarrow required — both scripts must import
cleanly without either installed (AC-10 style guard, mirrors
collect_ticks). Canned payloads are real observed shapes (WS probes,
2026-07-26). Covers symbol/product mapping, message parsing, Coinbase
book-state replay, file-path layout, and the 1 Hz row throttle.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import collect_books_binance as cbb
import collect_books_coinbase as cbc
import collector_core as cc


class TestBinanceSymbolMapping:
    def test_pair_to_symbol(self) -> None:
        assert cbb.pair_to_symbol("ETH/USD") == "ETHUSD"
        assert cbb.pair_to_symbol("RENDER/USD") == "RENDERUSD"

    def test_stream_name(self) -> None:
        assert cbb.stream_name("ETH/USD") == "ethusd@depth20@1000ms"

    def test_ws_url_combined_streams(self) -> None:
        url = cbb.ws_url(["ETH/USD", "SOL/USD"])
        assert url == (
            "wss://stream.binance.us:9443/stream"
            "?streams=ethusd@depth20@1000ms/solusd@depth20@1000ms"
        )


class TestBinanceParseDepthRow:
    # Observed combined-stream shape (probe 2026-07-26): string price/qty.
    MSG: ClassVar[dict[str, Any]] = {
        "stream": "ethusd@depth20@1000ms",
        "data": {
            "lastUpdateId": 3638293376,
            "bids": [["1882.04000000", "0.98580000"], ["1881.89000000", "0.13810000"]],
            "asks": [["1882.40000000", "0.71610000"]],
        },
    }

    def test_parses_stream_and_floats(self) -> None:
        parsed = cbb.parse_depth_row(self.MSG, ts="2026-07-26T00:00:00+00:00")
        assert parsed is not None
        stream, row = parsed
        assert stream == "ethusd@depth20@1000ms"
        assert row["ts"] == "2026-07-26T00:00:00+00:00"
        assert row["bid_price_1"] == 1882.04
        assert row["bid_qty_1"] == 0.9858
        assert row["bid_price_2"] == 1881.89
        assert row["ask_price_1"] == 1882.40
        assert row["ask_qty_1"] == 0.7161

    def test_pads_missing_depth_with_none(self) -> None:
        parsed = cbb.parse_depth_row(self.MSG, ts="t")
        assert parsed is not None
        _, row = parsed
        assert row["bid_price_3"] is None
        assert row["ask_price_2"] is None
        assert row["ask_qty_20"] is None
        # full schema: ts + 4*20 columns
        assert len(row) == 81

    def test_non_depth_message_returns_none(self) -> None:
        assert cbb.parse_depth_row({"result": None, "id": 1}, ts="t") is None
        assert cbb.parse_depth_row({}, ts="t") is None


class TestCoinbaseProductMapping:
    def test_pair_to_product(self) -> None:
        assert cbc.pair_to_product("ETH/USD") == "ETH-USD"
        assert cbc.pair_to_product("PAXG/USD") == "PAXG-USD"


class TestCoinbaseParseL2Events:
    def test_extracts_product_and_event(self) -> None:
        msg = {
            "channel": "l2_data",
            "timestamp": "2026-07-26T09:33:07.4Z",
            "sequence_num": 1,
            "events": [
                {
                    "type": "update",
                    "product_id": "ETH-USD",
                    "updates": [
                        {
                            "side": "bid",
                            "event_time": "2026-07-26T09:33:07.419487Z",
                            "price_level": "1881.6",
                            "new_quantity": "12.824662",
                        }
                    ],
                }
            ],
        }
        events = cbc.parse_l2_events(msg)
        assert len(events) == 1
        assert events[0][0] == "ETH-USD"
        assert events[0][1]["type"] == "update"

    def test_other_channels_ignored(self) -> None:
        assert cbc.parse_l2_events({"channel": "subscriptions", "events": [{}]}) == []
        assert cbc.parse_l2_events({"channel": "heartbeats"}) == []


class TestCoinbaseOrderBookState:
    @staticmethod
    def _upd(side: str, price: str, qty: str) -> dict[str, str]:
        return {
            "side": side,
            "event_time": "2026-07-26T09:33:07.3734Z",
            "price_level": price,
            "new_quantity": qty,
        }

    def test_snapshot_then_update_replay(self) -> None:
        book = cbc.OrderBookState()
        book.apply_event(
            {
                "type": "snapshot",
                "product_id": "ETH-USD",
                "updates": [
                    self._upd("bid", "1882.19", "3.89877"),
                    self._upd("bid", "1882.17", "0.58220119"),
                    self._upd("offer", "1882.40", "0.7161"),
                ],
            }
        )
        row = book.top_row(ts="t", depth=20)
        assert row["bid_price_1"] == 1882.19
        assert row["bid_price_2"] == 1882.17
        assert row["ask_price_1"] == 1882.40

        # Delta: better bid appears, old best ask removed (qty "0").
        book.apply_event(
            {
                "type": "update",
                "product_id": "ETH-USD",
                "updates": [
                    self._upd("bid", "1882.25", "1.5"),
                    self._upd("offer", "1882.40", "0"),
                    self._upd("offer", "1882.57", "1.151"),
                ],
            }
        )
        row = book.top_row(ts="t", depth=20)
        assert row["bid_price_1"] == 1882.25
        assert row["bid_qty_1"] == 1.5
        assert row["ask_price_1"] == 1882.57

    def test_new_snapshot_resets_book(self) -> None:
        book = cbc.OrderBookState()
        book.apply_event(
            {"type": "snapshot", "updates": [self._upd("bid", "100", "1")]}
        )
        book.apply_event(
            {"type": "snapshot", "updates": [self._upd("bid", "200", "2")]}
        )
        row = book.top_row(ts="t", depth=20)
        assert row["bid_price_1"] == 200.0
        assert row["bid_price_2"] is None

    def test_depth_truncated_to_top_20(self) -> None:
        book = cbc.OrderBookState()
        updates = [self._upd("bid", str(1000 + i), "1") for i in range(25)]
        book.apply_event({"type": "snapshot", "updates": updates})
        row = book.top_row(ts="t", depth=20)
        assert row["bid_price_1"] == 1024.0
        assert row["bid_price_20"] == 1005.0
        assert "bid_price_21" not in row


class TestPathLayout:
    TS = datetime(2026, 7, 26, 9, 5, tzinfo=UTC)

    # Layout delegated to collector_core.stream_dir (2026-08-08). Both venues
    # must agree with each other and with the tick collector, so pin them
    # against the flag rather than against a hardcoded shape.
    def test_binance_book_file_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cc, "PARTITION_BY_CLASS", True)
        p = cbb.book_file_path(Path("base"), "ETH/USD", self.TS)
        assert p == Path("base/crypto/ETH_USD/2026-07-26/book-09.parquet")

    def test_coinbase_book_file_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cc, "PARTITION_BY_CLASS", True)
        p = cbc.book_file_path(Path("base"), "SOL/USD", self.TS)
        assert p == Path("base/crypto/SOL_USD/2026-07-26/book-09.parquet")

    def test_both_venues_agree_on_layout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A divergence here is what silently splits the archive in two.
        for flag in (True, False):
            monkeypatch.setattr(cc, "PARTITION_BY_CLASS", flag)
            assert cbb.book_file_path(Path("b"), "USDC/EUR", self.TS) == cbc.book_file_path(
                Path("b"), "USDC/EUR", self.TS
            )

    def test_resolve_books_dir_prefers_external(self, tmp_path: Path) -> None:
        assert cbb.resolve_books_dir("binance", external_root=tmp_path) == (
            tmp_path / "books" / "binance"
        )
        assert cbc.resolve_books_dir("coinbase", external_root=tmp_path) == (
            tmp_path / "books" / "coinbase"
        )

    def test_resolve_books_dir_falls_back_when_external_absent(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope"
        assert cbb.resolve_books_dir("binance", external_root=missing) == Path(
            "data/books/binance"
        )
        assert cbc.resolve_books_dir("coinbase", external_root=missing) == Path(
            "data/books/coinbase"
        )


class TestRowThrottle:
    def test_coalesces_to_one_row_per_second(self) -> None:
        t = cbc.RowThrottle(interval_s=1.0)
        assert t.allow("ETH/USD", 100.0) is True
        assert t.allow("ETH/USD", 100.2) is False
        assert t.allow("ETH/USD", 100.99) is False
        assert t.allow("ETH/USD", 101.0) is True

    def test_keys_are_independent(self) -> None:
        t = cbb.RowThrottle(interval_s=1.0)
        assert t.allow("ETH/USD", 100.0) is True
        assert t.allow("SOL/USD", 100.1) is True
        assert t.allow("ETH/USD", 100.5) is False
        assert t.allow("SOL/USD", 100.5) is False


class TestBookSinksFileByEventTime:
    """Both book collectors must persist through the shared event-time sink.

    Each carried a private ParquetSink until 2026-08-09 that named the hourly
    file from FLUSH time and rewrote it in place on every flush. 0.74% of
    Coinbase book rows were misfiled on 2026-08-08, and one hourly file was
    left corrupt (no footer) by a kill mid-rewrite.
    """

    HOUR_9 = datetime(2026, 8, 8, 9, 59, 30, tzinfo=UTC)
    HOUR_10 = datetime(2026, 8, 8, 10, 0, 30, tzinfo=UTC)

    @pytest.mark.parametrize("mod", [cbb, cbc], ids=["binance", "coinbase"])
    def test_rows_reach_the_hourly_file_their_own_timestamp_names(
        self, mod: Any, tmp_path: Path
    ) -> None:
        sink = mod.PartitionedParquetSink(tmp_path)
        sink.add("ETH/USD", "book", {"ts": "t1", "bid_px": 1.0}, self.HOUR_9)
        sink.flush_all(self.HOUR_10, force=True)

        wanted = mod.book_file_path(tmp_path, "ETH/USD", self.HOUR_9)
        cc.compact_hour(wanted.parent, "book", self.HOUR_9.hour)
        assert wanted.exists()
        assert not mod.book_file_path(tmp_path, "ETH/USD", self.HOUR_10).exists()
