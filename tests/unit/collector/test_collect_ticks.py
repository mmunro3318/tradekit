"""Pure-logic tests for scripts/collect_ticks.py (SPRINT-P5-PROP §2c).

No network, no websockets/pyarrow required — collect_ticks must import
cleanly without either installed (AC-10 style guard, mirrors
tradekit.bridge._pywinauto). Covers message parsing, book state,
file-path rotation, prune-cutoff selection, and backoff schedule.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import collect_ticks as ct
import collector_core as cc


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
    """Layout is delegated to collector_core.stream_dir (2026-08-08) so every
    collector agrees on where a pair lives and PARTITION_BY_CLASS moves them
    all together. These pin the hourly rotation and the file naming; the
    directory shape itself is owned and tested in test_collector_core.py.
    """

    def test_trade_file_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cc, "PARTITION_BY_CLASS", True)
        base = Path("data/ticks")
        ts = datetime(2026, 7, 19, 14, 30, tzinfo=UTC)
        path = ct.trade_file_path(base, "ETH/USD", ts)
        assert path == base / "crypto" / "ETH_USD" / "2026-07-19" / "trades-14.parquet"

    def test_book_file_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cc, "PARTITION_BY_CLASS", True)
        base = Path("data/ticks")
        ts = datetime(2026, 1, 1, 0, 5, tzinfo=UTC)
        path = ct.book_file_path(base, "SOL/USD", ts)
        assert path == base / "crypto" / "SOL_USD" / "2026-01-01" / "book-00.parquet"

    def test_paths_follow_the_partition_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The flag is the single switch for the whole archive — a collector
        # that ignored it would silently split the tree in half.
        base = Path("data/ticks")
        ts = datetime(2026, 7, 19, 14, 30, tzinfo=UTC)
        monkeypatch.setattr(cc, "PARTITION_BY_CLASS", False)
        assert ct.book_file_path(base, "ETH/USD", ts) == (
            base / "ETH_USD" / "2026-07-19" / "book-14.parquet"
        )

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


class TestResolveDataDir:
    """External-drive preference (Mike, 2026-07-26): ticks land on
    D:/tradekit-data/ticks when the external root exists, repo-local
    data/ticks otherwise — collection never stops for a missing drive."""

    def test_prefers_external_ticks_dir_when_root_exists(self, tmp_path):
        external = tmp_path / "tradekit-data"
        external.mkdir()
        assert ct.resolve_data_dir(
            external_root=external, local_dir=Path("data/ticks")
        ) == external / "ticks"

    def test_falls_back_to_local_when_external_root_absent(self, tmp_path):
        assert ct.resolve_data_dir(
            external_root=tmp_path / "no-such-drive", local_dir=Path("data/ticks")
        ) == Path("data/ticks")


class TestTickSinkFilesByEventTime:
    """The tick collector must persist through the shared event-time sink.

    It carried a private ParquetSink until 2026-08-09 with both defects the
    shared one has since been fixed for: the hourly file was named from FLUSH
    time, and writes were read-modify-write. Measured on 2026-08-08 alone,
    1.87% of 24,236,349 Kraken book rows sat in the wrong hour and 38,148 of
    them in the wrong day.
    """

    HOUR_9 = datetime(2026, 8, 8, 9, 59, 30, tzinfo=UTC)
    HOUR_10 = datetime(2026, 8, 8, 10, 0, 30, tzinfo=UTC)

    def test_rows_reach_the_hourly_file_their_own_timestamp_names(self, tmp_path: Path) -> None:
        # Buffered at 09:59:30, flushed at 10:00:30 — the straggler case that
        # made thin-pair hour attribution unrecoverable.
        sink = ct.PartitionedParquetSink(tmp_path)
        sink.add("BTC/USD", "trades", {"ts": "t1", "price": 1.0, "qty": 2.0}, self.HOUR_9)
        sink.add("BTC/USD", "book", {"ts": "t1", "bid_px": 1.0}, self.HOUR_9)
        sink.flush_all(self.HOUR_10, force=True)

        for stream, path_of in (("trades", ct.trade_file_path), ("book", ct.book_file_path)):
            wanted = path_of(tmp_path, "BTC/USD", self.HOUR_9)
            cc.compact_hour(wanted.parent, stream, self.HOUR_9.hour)
            assert wanted.exists(), f"{stream} row did not reach hour 09"
            assert not path_of(tmp_path, "BTC/USD", self.HOUR_10).exists()


class _FakeWs:
    """Replays queued frames, then blocks so the run's own deadline ends it."""

    def __init__(self, frames: list[str]) -> None:
        self.frames = list(frames)
        self.sent: list[str] = []

    async def __aenter__(self) -> _FakeWs:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def recv(self) -> str:
        if self.frames:
            return self.frames.pop(0)
        await asyncio.sleep(3600)  # never resolves inside the test deadline
        raise AssertionError("unreachable")  # pragma: no cover


def _book_frame(pair: str, best_bid: float) -> str:
    return json.dumps(
        {
            "channel": "book",
            "type": "update",
            "data": [
                {
                    "symbol": pair,
                    "bids": [{"price": best_bid, "qty": 1.0}],
                    "asks": [{"price": best_bid + 1.0, "qty": 1.0}],
                }
            ],
        }
    )


def _trade_frame(pair: str, price: float, ts: str) -> str:
    return json.dumps(
        {
            "channel": "trade",
            "type": "update",
            "data": [
                {
                    "symbol": pair,
                    "timestamp": ts,
                    "price": price,
                    "qty": 1.0,
                    "side": "buy",
                    "ord_type": "market",
                }
            ],
        }
    )


class TestKrakenBookIsThrottledLikeEveryOtherVenue:
    """Kraken book must coalesce to 1 Hz, as Coinbase and OKX books already do.

    `collect_ticks` never had a throttle — it predates collector_core and
    never inherited the default. Every other book stream goes through
    `RowThrottle` at BOOK_ROW_INTERVAL_S, so the archive's LARGEST stream was
    the only one sampled at venue chattiness rather than at a fixed rate,
    which breaks the "aligned cross-venue timestamps" premise: a 1 Hz stream
    cannot be joined against an 18 Hz one at better than 1 Hz.

    Measured on 2026-08-08, all 77 symbols: 23,213,832 book rows stored where
    a 1 Hz throttle keeps 2,347,045 — 9.9x. TAO_USD alone wrote 2,114,430 rows
    in one day, more than ETH.

    Trades are NOT throttled here and must never be: every print matters.
    """

    def _run(
        self, frames: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> dict[str, dict[str, int]]:
        import websockets

        monkeypatch.setattr(ct, "verify_pairs", lambda pairs, **_: dict.fromkeys(pairs, True))
        ws = _FakeWs(frames)
        monkeypatch.setattr(websockets, "connect", lambda *a, **k: ws)
        return asyncio.run(ct.run_collector(["BTC/USD"], tmp_path, duration_s=0.4))

    def test_a_burst_of_book_updates_in_one_second_writes_one_row(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Twenty distinct book states arriving back-to-back. Unthrottled that
        # is twenty rows; at 1 Hz it is one.
        frames = [_book_frame("BTC/USD", 100.0 + i) for i in range(20)]

        counts = self._run(frames, tmp_path, monkeypatch)

        written = [
            r
            for f in tmp_path.rglob("book-*.parquet")
            for r in __import__("pyarrow.parquet", fromlist=["x"]).read_table(f).to_pylist()
        ]
        assert len(written) == 1, f"expected 1 coalesced book row, got {len(written)}"
        assert counts["BTC/USD"]["book_updates"] == 1

    def test_every_trade_survives_the_throttle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The counter-test. Coalescing the book must not touch trades — a
        # dropped print is a hole in the tape that cannot be reconstructed.
        frames = [
            _trade_frame("BTC/USD", 100.0 + i, f"2026-08-09T15:00:0{i}.000000Z") for i in range(5)
        ]

        counts = self._run(frames, tmp_path, monkeypatch)

        written = [
            r
            for f in tmp_path.rglob("trades-*.parquet")
            for r in __import__("pyarrow.parquet", fromlist=["x"]).read_table(f).to_pylist()
        ]
        assert len(written) == 5
        assert counts["BTC/USD"]["trades"] == 5

    def test_the_interval_is_the_shared_one_not_a_private_copy(self) -> None:
        # Divergence here is what split the archive's resolution in the first
        # place: one venue quietly sampling at a different rate from the rest.
        assert ct.BOOK_ROW_INTERVAL_S == cc.BOOK_ROW_INTERVAL_S
