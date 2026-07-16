"""tests for tradekit.mae._data.macro (SPRINT-P1C story 0, yfinance macro
provider; Mike-approved 2026-07-16).

TEST-PATH EXCEPTION (extends ASSUMPTIONS 23/29/39): this file imports
`tradekit.mae._data.macro` directly — no public verb wires macro.py into a
pipeline yet this batch (non-gating per the addendum).

Zero-network: `_fetch_rows` is monkeypatched directly with fixture rows.
yfinance does not go through httpx, so the suite's autouse `respx_mock`
guard (`tests/conftest.py`) never sees these calls either way — this file
does NOT respx-mock Yahoo's internals (addendum instruction).

Status: `macro.py` is a P1C batch A STUB — every test below currently fails
with NotImplementedError (the expected red state). Assertions describe the
REAL degradation contract the dev agent implements next: NEVER raise; warm
cache -> stale=True + cached bars; cold cache -> stale=True + empty bars.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from tradekit.mae._data import macro
from tradekit.mae._data.cache import BarCache

_Row = tuple[date, str, str, str, str, str]

# Known fixture rows for ^GSPC — weekdays only (yfinance never returns
# weekend rows for equities/indices), STRING prices (mirrors the real
# _fetch_rows contract: never leave prices as float).
_FIXTURE_ROWS: list[tuple[date, str, str, str, str, str]] = [
    (date(2026, 7, 13), "6270.50", "6288.10", "6255.00", "6281.25", "2500000000"),
    (date(2026, 7, 14), "6281.25", "6301.75", "6270.00", "6295.60", "2400000000"),
    (date(2026, 7, 15), "6295.60", "6310.00", "6280.40", "6303.15", "2600000000"),
]


def test_happy_path_returns_ascending_utc_bars_via_fetch_rows(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        macro,
        "_fetch_rows",
        lambda ticker, start, end: _FIXTURE_ROWS,
    )
    cache = BarCache(tmp_path / "cache.db")

    result = macro.get_macro_bars("^GSPC", lookback_days=5, cache=cache)

    assert result.source == "yfinance"
    assert result.stale is False
    opens = [b.ts_open for b in result.bars]
    assert opens == sorted(opens), "bars must be strictly ascending by ts_open"
    for b in result.bars:
        assert b.ts_open.tzinfo is not None, "ts_open must be aware (UTC), never naive"
        assert b.ts_open.utcoffset().total_seconds() == 0, "ts_open must be UTC"
    assert result.bars[0].close == Decimal("6281.25"), (
        "prices must round-trip via Decimal(str(x)) exactly, never through a raw float"
    )
    assert len(result.bars) == 3


def test_fetch_failure_with_warm_cache_returns_cached_bars_stale_never_raises(
    tmp_path, monkeypatch
) -> None:
    cache = BarCache(tmp_path / "cache.db")

    # Warm the cache with one successful call first.
    monkeypatch.setattr(macro, "_fetch_rows", lambda ticker, start, end: _FIXTURE_ROWS)
    first = macro.get_macro_bars("^VIX", lookback_days=5, cache=cache)
    assert first.stale is False
    assert len(first.bars) == 3

    # Now the fetch fails (rate limit / network / malformed response).
    def _boom(ticker: str, start: datetime, end: datetime) -> list[_Row]:
        raise RuntimeError("simulated yfinance failure")

    monkeypatch.setattr(macro, "_fetch_rows", _boom)

    second = macro.get_macro_bars("^VIX", lookback_days=5, cache=cache)

    assert second.stale is True, (
        "a fetch failure with a warm cache must degrade to stale=True, never raise"
    )
    assert second.source == "yfinance"
    assert len(second.bars) == 3, (
        "the cached bars from the earlier successful call must be returned"
    )
    assert {b.ts_open for b in second.bars} == {b.ts_open for b in first.bars}


def test_fetch_failure_with_cold_cache_returns_empty_stale_series_never_raises(
    tmp_path, monkeypatch
) -> None:
    cache = BarCache(tmp_path / "cache.db")

    def _boom(ticker: str, start: datetime, end: datetime) -> list[_Row]:
        raise RuntimeError("simulated yfinance failure, nothing cached yet")

    monkeypatch.setattr(macro, "_fetch_rows", _boom)

    result = macro.get_macro_bars("DX-Y.NYB", lookback_days=5, cache=cache)

    assert result.stale is True
    assert result.source == "yfinance"
    assert result.bars == [], (
        "cold cache (nothing ever fetched for this ticker) must degrade to an "
        "EMPTY stale BarSeries, never raise (P1A supplementary-data rule)"
    )


def test_macro_tickers_constant_matches_addendum() -> None:
    assert macro.MACRO_TICKERS == ("^GSPC", "^VIX", "DX-Y.NYB", "GLD", "TLT")
