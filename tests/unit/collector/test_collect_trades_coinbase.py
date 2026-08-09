"""Tests for scripts/collect_trades_coinbase.py — the Coinbase trade adapter
built on collector_core's VenueSpec. No network. Frame shape is the real
sample from the module docstring (probed 2026-08-08).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import collect_trades_coinbase as cbt

NOW = datetime(2026, 8, 8, 9, 29, 38, tzinfo=UTC)


class TestParse:
    def test_extracts_fields_from_real_sample_frame(self) -> None:
        msg = {
            "channel": "market_trades",
            "events": [
                {
                    "type": "update",
                    "trades": [
                        {
                            "product_id": "BTC-USD",
                            "trade_id": "1068307673",
                            "price": "64975.28",
                            "size": "0.01149823",
                            "time": "2026-08-08T09:29:38.161179Z",
                            "side": "BUY",
                        }
                    ],
                }
            ],
        }
        rows = cbt.parse(msg, NOW)
        assert len(rows) == 1
        symbol, stream, row = rows[0]
        assert symbol == "BTC/USD"
        assert stream == "trades"
        assert row["price"] == 64975.28
        assert row["qty"] == 0.01149823
        assert row["side"] == "buy"
        assert row["trade_id"] == "1068307673"
        assert row["ts"] == "2026-08-08T09:29:38.161179Z"

    def test_side_is_lowercased(self) -> None:
        msg = {
            "channel": "market_trades",
            "events": [
                {
                    "type": "update",
                    "trades": [
                        {
                            "product_id": "ETH-USD",
                            "trade_id": "1",
                            "price": "1.0",
                            "size": "1.0",
                            "time": "t",
                            "side": "SELL",
                        }
                    ],
                }
            ],
        }
        _, _, row = cbt.parse(msg, NOW)[0]
        assert row["side"] == "sell"

    def test_product_id_maps_dash_to_slash_symbol(self) -> None:
        msg = {
            "channel": "market_trades",
            "events": [
                {
                    "type": "update",
                    "trades": [
                        {
                            "product_id": "SOL-USD",
                            "trade_id": "1",
                            "price": "100.0",
                            "size": "1.0",
                            "time": "t",
                            "side": "buy",
                        }
                    ],
                }
            ],
        }
        symbol, _, _ = cbt.parse(msg, NOW)[0]
        assert symbol == "SOL/USD"

    def test_snapshot_events_are_ignored(self) -> None:
        # Coinbase replays recent trade history as a "snapshot" event on
        # connect; taking it would duplicate rows across reconnects.
        msg = {
            "channel": "market_trades",
            "events": [
                {
                    "type": "snapshot",
                    "trades": [
                        {
                            "product_id": "BTC-USD",
                            "trade_id": "1",
                            "price": "1.0",
                            "size": "1.0",
                            "time": "t",
                            "side": "buy",
                        }
                    ],
                }
            ],
        }
        assert cbt.parse(msg, NOW) == []

    def test_mixed_snapshot_and_update_events_only_takes_update(self) -> None:
        msg = {
            "channel": "market_trades",
            "events": [
                {
                    "type": "snapshot",
                    "trades": [
                        {
                            "product_id": "BTC-USD",
                            "trade_id": "old",
                            "price": "1.0",
                            "size": "1.0",
                            "time": "t",
                            "side": "buy",
                        }
                    ],
                },
                {
                    "type": "update",
                    "trades": [
                        {
                            "product_id": "BTC-USD",
                            "trade_id": "new",
                            "price": "2.0",
                            "size": "2.0",
                            "time": "t2",
                            "side": "sell",
                        }
                    ],
                },
            ],
        }
        rows = cbt.parse(msg, NOW)
        assert len(rows) == 1
        assert rows[0][2]["trade_id"] == "new"

    def test_non_market_trades_channel_returns_empty(self) -> None:
        assert cbt.parse({"channel": "heartbeats"}, NOW) == []
        assert cbt.parse({"channel": "subscriptions", "events": [{}]}, NOW) == []
        assert cbt.parse({}, NOW) == []

    def test_multiple_trades_in_one_frame_all_come_through(self) -> None:
        msg = {
            "channel": "market_trades",
            "events": [
                {
                    "type": "update",
                    "trades": [
                        {
                            "product_id": "BTC-USD",
                            "trade_id": "1",
                            "price": "1.0",
                            "size": "1.0",
                            "time": "t1",
                            "side": "buy",
                        },
                        {
                            "product_id": "ETH-USD",
                            "trade_id": "2",
                            "price": "2.0",
                            "size": "2.0",
                            "time": "t2",
                            "side": "sell",
                        },
                        {
                            "product_id": "BTC-USD",
                            "trade_id": "3",
                            "price": "3.0",
                            "size": "3.0",
                            "time": "t3",
                            "side": "buy",
                        },
                    ],
                }
            ],
        }
        rows = cbt.parse(msg, NOW)
        assert len(rows) == 3
        assert [r[2]["trade_id"] for r in rows] == ["1", "2", "3"]


class TestErrorOf:
    def test_error_frame_returns_message(self) -> None:
        msg = {"type": "error", "message": "too many L2 streams requested"}
        assert cbt.error_of(msg) == "too many L2 streams requested"

    def test_non_error_frame_returns_none(self) -> None:
        assert cbt.error_of({"type": "subscriptions"}) is None
        assert cbt.error_of({"channel": "market_trades"}) is None
        assert cbt.error_of({}) is None
