"""Pure-logic tests for scripts/collect_ticks.py (SPRINT-P5-PROP §2c).

No network, no websockets/pyarrow required — collect_ticks must import
cleanly without either installed (AC-10 style guard, mirrors
tradekit.bridge._pywinauto). Covers message parsing, book state,
file-path rotation, prune-cutoff selection, and backoff schedule.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import collect_ticks as ct


class TestParseTradeRows:
    def test_single_trade(self) -> None:
        msg = {
            "channel": "trade",
            "type": "update",
            "data": [
                {
                    "symbol": "ETH/USD",
                    "side": "buy",
                    "price": 2500.5,
                    "qty": 1.25,
                    "ord_type": "market",
                    "trade_id": 123,
                    "timestamp": "2026-07-19T07:49:37.708706Z",
                }
            ],
        }
        rows = ct.parse_trade_rows(msg)
        assert rows == [
            {
                "ts": "2026-07-19T07:49:37.708706Z",
                "price": 2500.5,
                "qty": 1.25,
                "side": "buy",
                "ord_type": "market",
            }
        ]

    def test_multiple_trades_in_one_message(self) -> None:
        msg = {
            "channel": "trade",
            "type": "update",
            "data": [
                {
                    "symbol": "SOL/USD",
                    "side": "buy",
                    "price": 100.0,
                    "qty": 2.0,
                    "ord_type": "limit",
                    "timestamp": "2026-07-19T00:00:00Z",
                },
                {
                    "symbol": "SOL/USD",
                    "side": "sell",
                    "price": 100.1,
                    "qty": 3.0,
                    "ord_type": "market",
                    "timestamp": "2026-07-19T00:00:01Z",
                },
            ],
        }
        rows = ct.parse_trade_rows(msg)
        assert len(rows) == 2
        assert rows[0]["side"] == "buy"
        assert rows[1]["side"] == "sell"

    def test_non_trade_channel_returns_empty(self) -> None:
        assert ct.parse_trade_rows({"channel": "heartbeat"}) == []


class TestOrderBookState:
    def test_snapshot_then_row(self) -> None:
        book = ct.OrderBookState()
        book.apply_snapshot(
            {
                "bids": [{"price": 100.0, "qty": 1.0}, {"price": 99.5, "qty": 2.0}],
                "asks": [{"price": 100.5, "qty": 1.5}, {"price": 101.0, "qty": 2.5}],
            }
        )
        row = book.top_row(ts="2026-07-19T00:00:00Z", depth=2)
        assert row["ts"] == "2026-07-19T00:00:00Z"
        assert row["bid_price_1"] == 100.0
        assert row["bid_qty_1"] == 1.0
        assert row["bid_price_2"] == 99.5
        assert row["ask_price_1"] == 100.5
        assert row["ask_qty_1"] == 1.5
        assert row["ask_price_2"] == 101.0

    def test_update_removes_level_on_zero_qty(self) -> None:
        book = ct.OrderBookState()
        book.apply_snapshot(
            {
                "bids": [{"price": 100.0, "qty": 1.0}],
                "asks": [{"price": 100.5, "qty": 1.0}],
            }
        )
        book.apply_update({"bids": [{"price": 100.0, "qty": 0.0}], "asks": []})
        row = book.top_row(ts="t", depth=1)
        assert row.get("bid_price_1") is None

    def test_update_adds_new_level(self) -> None:
        book = ct.OrderBookState()
        book.apply_snapshot({"bids": [{"price": 100.0, "qty": 1.0}], "asks": []})
        book.apply_update({"bids": [{"price": 100.2, "qty": 0.5}], "asks": []})
        row = book.top_row(ts="t", depth=2)
        assert row["bid_price_1"] == 100.2
        assert row["bid_price_2"] == 100.0

    def test_missing_depth_levels_are_none(self) -> None:
        book = ct.OrderBookState()
        book.apply_snapshot({"bids": [{"price": 1.0, "qty": 1.0}], "asks": []})
        row = book.top_row(ts="t", depth=10)
        assert row["bid_price_1"] == 1.0
        assert row["bid_price_10"] is None
        assert row["ask_price_1"] is None


class TestFilePathRotation:
    def test_trade_file_path(self) -> None:
        base = Path("data/ticks")
        ts = datetime(2026, 7, 19, 14, 30, tzinfo=UTC)
        path = ct.trade_file_path(base, "ETH/USD", ts)
        assert path == base / "ETH_USD" / "2026-07-19" / "trades-14.parquet"

    def test_book_file_path(self) -> None:
        base = Path("data/ticks")
        ts = datetime(2026, 1, 1, 0, 5, tzinfo=UTC)
        path = ct.book_file_path(base, "SOL/USD", ts)
        assert path == base / "SOL_USD" / "2026-01-01" / "book-00.parquet"

    def test_pair_slash_is_sanitized_in_directory_name(self) -> None:
        base = Path("data/ticks")
        ts = datetime(2026, 7, 19, 23, 0, tzinfo=UTC)
        path = ct.trade_file_path(base, "LINK/USD", ts)
        assert "/" not in path.relative_to(base).parts[0]


class TestPruneCutoff:
    def test_prune_targets_selects_dirs_older_than_retention(self, tmp_path: Path) -> None:
        pair_dir = tmp_path / "ETH_USD"
        old_dir = pair_dir / "2020-01-01"
        new_dir = pair_dir / "2026-07-01"
        old_dir.mkdir(parents=True)
        new_dir.mkdir(parents=True)
        now = datetime(2026, 7, 19, tzinfo=UTC)
        targets = ct.prune_targets(tmp_path, now=now, retention_days=730)
        assert old_dir in targets
        assert new_dir not in targets

    def test_prune_cutoff_date(self) -> None:
        now = datetime(2026, 7, 19, tzinfo=UTC)
        cutoff = ct.prune_cutoff_date(now, retention_days=730)
        assert cutoff == (now - timedelta(days=730)).date()
        assert isinstance(cutoff, date)

    def test_prune_targets_ignores_non_date_dirs(self, tmp_path: Path) -> None:
        pair_dir = tmp_path / "ETH_USD"
        junk_dir = pair_dir / "not-a-date"
        junk_dir.mkdir(parents=True)
        now = datetime(2026, 7, 19, tzinfo=UTC)
        targets = ct.prune_targets(tmp_path, now=now, retention_days=730)
        assert junk_dir not in targets


class TestBackoffSchedule:
    def test_backoff_grows_exponentially_until_cap(self) -> None:
        delays = [ct.backoff_delay(attempt) for attempt in range(7)]
        assert delays[0] == 1.0
        assert delays[1] == 2.0
        assert delays[2] == 4.0
        assert delays[3] == 8.0
        # capped at 60s per pins
        assert delays[6] == 60.0

    def test_backoff_never_exceeds_cap(self) -> None:
        assert ct.backoff_delay(20) == 60.0


class TestImportsWithoutOptionalDeps:
    def test_module_imports_without_websockets_or_pyarrow(self) -> None:
        # collect_ticks itself imports fine in this test env (websockets IS
        # installed here); the guard contract is exercised structurally:
        # the module must not import websockets/pyarrow at module scope.
        import ast

        src = (Path(__file__).resolve().parents[3] / "scripts" / "collect_ticks.py").read_text()
        tree = ast.parse(src)
        top_level_imports: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_level_imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_level_imports.append(node.module)
        assert "websockets" not in top_level_imports
        assert "pyarrow" not in top_level_imports
