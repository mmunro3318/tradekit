"""Tests for scripts/collect_equities_alpaca.py — the delayed SIP poller.

The venue wire is the only thing faked: `httpx.Client` is replaced with a stub
that records the query it was asked for and answers with real Alpaca-shaped
response dicts. Everything downstream of that — the resume cursor, the
de-duplication and the on-disk layout — runs for real against a temp tree,
because those are exactly the parts that were silently wrong.

Fixture timestamps are built relative to `now` so the suite cannot rot the
moment the poller's 5-day lookback floor moves past a hard-coded date.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import collect_equities_alpaca as alpaca


def _ts(when: datetime, nanos: int) -> str:
    """An Alpaca RFC-3339 timestamp: whole seconds plus 9 fractional digits."""
    return f"{when:%Y-%m-%dT%H:%M:%S}.{nanos:09d}Z"


def _trade(ts: str, trade_id: str, price: float = 10.0) -> dict[str, Any]:
    """One row shaped exactly like the venue's /v2/stocks/trades payload."""
    return {"t": ts, "p": price, "s": 100, "x": "V", "c": ["@"], "z": "C", "i": trade_id}


def _seed_stored_trade(base: Path, symbol: str, when: datetime, ts: str, trade_id: str) -> Path:
    """Write a stored row directly with pyarrow — never via the code under test."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    day_dir = base / symbol / f"{when:%Y-%m-%d}"
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"trades-{when:%H}.part-0000.parquet"
    pq.write_table(pa.Table.from_pylist([alpaca.trade_row(_trade(ts, trade_id))]), path)
    return path


class _Wire:
    """Records every request and replays a canned page per (symbol, endpoint)."""

    def __init__(self, pages: dict[tuple[str, str], list[dict[str, Any]]]) -> None:
        self.pages = pages
        self.calls: list[dict[str, Any]] = []

    def client_factory(self) -> Any:
        wire = self

        class _Client:
            def __init__(self, **_: Any) -> None: ...

            def __enter__(self) -> _Client:
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def get(self, url: str, params: dict[str, Any]) -> Any:
                endpoint = url.rsplit("/", 1)[-1]
                wire.calls.append({"endpoint": endpoint, **params})
                rows = wire.pages.get((params["symbols"], endpoint), [])
                return _Response({endpoint: {params["symbols"]: rows}, "next_page_token": None})

        return _Client


class _Response:
    status_code = 200

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        return None


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("ALPACA_API_KEY_ID", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")

    def _install(pages: dict[tuple[str, str], list[dict[str, Any]]]) -> _Wire:
        wire = _Wire(pages)
        monkeypatch.setattr(alpaca.httpx, "Client", wire.client_factory())
        return wire

    return _install


def _read_all(base: Path) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq

    out: list[dict[str, Any]] = []
    for f in sorted(base.rglob("*.parquet")):
        for row in pq.read_table(f).to_pylist():
            out.append({**row, "_path": f})
    return out


class TestResumeCursor:
    """The cursor must resume at a nanosecond, not at the top of a second.

    Alpaca's `start` is INCLUSIVE and its timestamps carry nanoseconds, so a
    cursor is caught between two failure modes: ask for too much and you
    re-store rows forever, ask for too little and you drop prints. The poller
    formatted `start` with `%H:%M:%SZ`, which threw away the fractional part
    and re-requested the entire final second on every pass. Measured
    2026-08-09 over the weekend, when the tape was closed and the cursor could
    not advance: 15 distinct prints re-written 176 times each, 2,625 redundant
    rows in 8 seconds of tape.
    """

    def test_regression_start_is_the_stored_instant_not_the_top_of_its_second(
        self, tmp_path: Path, wired: Any
    ) -> None:
        when = datetime.now(UTC) - timedelta(hours=26)
        stored = _ts(when, 123_456_789)
        _seed_stored_trade(tmp_path, "RIOT", when, stored, "A1")
        wire = wired({("RIOT", "trades"): [_trade(stored, "A1")]})

        alpaca.run_once(["RIOT"], tmp_path)

        assert wire.calls, "the poller never asked the venue for anything"
        assert wire.calls[0]["start"] == stored

    def test_regression_the_row_already_stored_at_the_cursor_is_not_written_twice(
        self, tmp_path: Path, wired: Any
    ) -> None:
        when = datetime.now(UTC) - timedelta(hours=26)
        stored = _ts(when, 500_000_000)
        _seed_stored_trade(tmp_path, "RIOT", when, stored, "A1")
        # An inclusive `start` means the venue MUST hand this row back.
        wired({("RIOT", "trades"): [_trade(stored, "A1")]})

        written = alpaca.run_once(["RIOT"], tmp_path)

        rows = _read_all(tmp_path)
        assert [r["trade_id"] for r in rows] == ["A1"]
        assert written.get("RIOT/trades", 0) == 0

    def test_a_different_print_at_the_same_instant_is_still_kept(
        self, tmp_path: Path, wired: Any
    ) -> None:
        # The counter-test: suppressing the boundary must not degenerate into
        # "drop everything at the cursor". Two venues can print the same
        # nanosecond, and the second one is real data.
        when = datetime.now(UTC) - timedelta(hours=26)
        stored = _ts(when, 500_000_000)
        _seed_stored_trade(tmp_path, "RIOT", when, stored, "A1")
        wired({("RIOT", "trades"): [_trade(stored, "A1"), _trade(stored, "B2", price=11.0)]})

        written = alpaca.run_once(["RIOT"], tmp_path)

        assert sorted(r["trade_id"] for r in _read_all(tmp_path)) == ["A1", "B2"]
        assert written.get("RIOT/trades", 0) == 1

    def test_a_later_print_inside_the_cursor_second_is_kept(
        self, tmp_path: Path, wired: Any
    ) -> None:
        # The exact rows the old second-truncating cursor re-fetched forever.
        when = datetime.now(UTC) - timedelta(hours=26)
        stored = _ts(when, 100_000_000)
        later = _ts(when, 900_000_000)
        _seed_stored_trade(tmp_path, "RIOT", when, stored, "A1")
        wired({("RIOT", "trades"): [_trade(stored, "A1"), _trade(later, "C3", price=12.0)]})

        alpaca.run_once(["RIOT"], tmp_path)

        assert sorted(r["trade_id"] for r in _read_all(tmp_path)) == ["A1", "C3"]

    def test_with_nothing_stored_the_poller_starts_at_the_lookback_floor(
        self, tmp_path: Path, wired: Any
    ) -> None:
        wire = wired({("RIOT", "trades"): []})

        alpaca.run_once(["RIOT"], tmp_path, max_lookback_days=3.0)

        start = datetime.fromisoformat(wire.calls[0]["start"].replace("Z", "+00:00"))
        expected = datetime.now(UTC) - timedelta(seconds=alpaca.SIP_DELAY_S, days=3)
        assert abs((start - expected).total_seconds()) < 60


class TestOnDiskLayout:
    def test_regression_equities_are_filed_under_the_venue_tree_not_an_asset_class(
        self, tmp_path: Path, wired: Any
    ) -> None:
        # RIOT matched no _CLASS_RULES rule, so class partitioning dropped an
        # equity into `crypto/`. The venue tree IS the asset class here.
        when = datetime.now(UTC) - timedelta(hours=26)
        wired({("RIOT", "trades"): [_trade(_ts(when, 1), "A1")]})

        alpaca.run_once(["RIOT"], tmp_path)

        assert not (tmp_path / "crypto").exists()
        assert (tmp_path / "RIOT" / f"{when:%Y-%m-%d}").is_dir()

    def test_regression_prints_are_filed_by_trade_time_not_by_poll_time(
        self, tmp_path: Path, wired: Any
    ) -> None:
        # The poller flushes with `now - 16min`; a print from two days ago must
        # not inherit that. This is the defect that filed a whole Friday tape
        # under Sunday's date.
        old = datetime.now(UTC) - timedelta(days=2, hours=5)
        wired({("RIOT", "trades"): [_trade(_ts(old, 42), "A1")]})

        alpaca.run_once(["RIOT"], tmp_path)

        files = list(tmp_path.rglob("*.parquet"))
        assert len(files) == 1
        assert files[0].parent.name == f"{old:%Y-%m-%d}"
        assert files[0].name.startswith(f"trades-{old:%H}.")

    def test_a_batch_spanning_hours_is_split_across_those_hours(
        self, tmp_path: Path, wired: Any
    ) -> None:
        first = datetime.now(UTC) - timedelta(hours=30)
        second = first + timedelta(hours=1)
        wired(
            {
                ("RIOT", "trades"): [
                    _trade(_ts(first, 1), "A1"),
                    _trade(_ts(second, 2), "B2"),
                ]
            }
        )

        alpaca.run_once(["RIOT"], tmp_path)

        names = sorted(f.name for f in tmp_path.rglob("*.parquet"))
        assert names == [
            f"trades-{first:%H}.part-0000.parquet",
            f"trades-{second:%H}.part-0000.parquet",
        ]
