"""tests/contract/test_marketdata_port.py — story 8: MarketDataPort
conformance suite (TD-18 ring 2, DESIGN §9.1).

ONE parametrized suite every current `MarketDataPort` provider must pass:
Kraken, Alpaca-equity, Alpaca-crypto. `CoinGeckoProvider` is deliberately
EXCLUDED — it exposes `get_global`/`get_markets`, not `get_bars`, so it does
not implement this Protocol at all (ASSUMPTIONS 34; see test_coingecko.py).

Each case is built by its own factory function (`_kraken_case`,
`_alpaca_equity_case`, `_alpaca_crypto_case`), owns its own respx URL +
success-body fixture, and is registered once in `CASE_BUILDERS`. Adding a
future provider to this suite is exactly ONE new factory function + ONE new
`CASE_BUILDERS` entry — nothing else in this file changes (that one-entry
property is the point of a conformance suite, TD-18).

Pins per provider, all five checked identically via the shared `case`
fixture:
  - bars come back ascending by `ts_open`
  - every `ts_open` is aware-UTC
  - every OHLCV field is `Decimal`
  - `BarSeries.asset` / `BarSeries.timeframe` echo the request
  - `BarSeries.source` is the provider's own literal name
  - a simulated HTTP 5xx raises the typed `ProviderUnavailable` (never a
    bare httpx exception, never a silent `stale=True` — that flag is
    reserved for macro/supplementary providers, sprint doc trap)

TDD status: the Kraken cases are already implemented (stories 3-5, green);
the Alpaca cases target the story-6 stub
(`src/tradekit/mae/_data/alpaca_data.py`, currently `NotImplementedError`)
and are expected RED until story 6 lands. Mixed red/green within one
parametrized suite is expected here — nothing in this file is implementation,
only the conformance pins.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest

from tradekit.contracts import AssetRef
from tradekit.mae._data.alpaca_data import (
    ALPACA_API_KEY_ID_ENV,
    ALPACA_API_SECRET_ENV,
    ALPACA_CRYPTO_BARS_URL,
    ALPACA_EQUITY_BARS_URL_TEMPLATE,
    AlpacaDataProvider,
)
from tradekit.mae._data.errors import ProviderUnavailable
from tradekit.mae._data.kraken import KRAKEN_OHLC_URL, KrakenProvider
from tradekit.mae._data.port import MarketDataPort


def _no_op_sleeper(_seconds: float) -> None:
    """No real sleep in tests (ASSUMPTIONS 30) — with retry wired into every
    provider (H2), the 5xx conformance case would otherwise back off with
    real time.sleep."""


@dataclass(frozen=True)
class Case:
    """One MarketDataPort-conformant provider's request window + respx
    wiring for this suite."""

    id: str
    provider: MarketDataPort
    asset: AssetRef
    timeframe: str
    start: datetime
    end: datetime
    url: str
    success_body: Any
    expected_source: str


def _kraken_case(monkeypatch: pytest.MonkeyPatch) -> Case:
    t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    asset = AssetRef(
        symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01")
    )
    rows = [
        [int(t0.timestamp()), "68100.0", "68150.0", "68050.0", "68123.4", "68110.0", "12.5", 50],
        [
            int((t0 + timedelta(hours=1)).timestamp()),
            "68123.4",
            "68300.0",
            "68100.0",
            "68250.0",
            "68200.0",
            "9.1",
            40,
        ],
    ]
    body = {"error": [], "result": {"XXBTZUSD": rows, "last": rows[-1][0]}}
    return Case(
        id="kraken",
        provider=KrakenProvider(sleeper=_no_op_sleeper),
        asset=asset,
        timeframe="1h",
        start=t0,
        end=t0 + timedelta(hours=2),
        url=KRAKEN_OHLC_URL,
        success_body=body,
        expected_source="kraken",
    )


def _alpaca_bar(t: datetime, o: float, h: float, low: float, c: float, v: float) -> dict:
    return {"t": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "o": o, "h": h, "l": low, "c": c, "v": v}


def _alpaca_equity_case(monkeypatch: pytest.MonkeyPatch) -> Case:
    monkeypatch.setenv(ALPACA_API_KEY_ID_ENV, "AKFAKE00000000000000")
    monkeypatch.setenv(ALPACA_API_SECRET_ENV, "fakeSecretValueXYZ")
    t0 = datetime(2026, 1, 2, 14, 0, 0, tzinfo=UTC)
    asset = AssetRef(
        symbol="AAPL", venue="alpaca", asset_class="equity", tick_size=Decimal("0.01")
    )
    rows = [
        _alpaca_bar(t0, 189.43, 189.90, 189.10, 189.75, 1_500_000),
        _alpaca_bar(t0 + timedelta(hours=1), 189.75, 190.20, 189.60, 190.05, 1_200_000),
    ]
    body = {"bars": rows, "next_page_token": None}
    return Case(
        id="alpaca-equity",
        provider=AlpacaDataProvider(sleeper=_no_op_sleeper),
        asset=asset,
        timeframe="1h",
        start=t0,
        end=t0 + timedelta(hours=2),
        url=ALPACA_EQUITY_BARS_URL_TEMPLATE.format(symbol="AAPL"),
        success_body=body,
        expected_source="alpaca",
    )


def _alpaca_crypto_case(monkeypatch: pytest.MonkeyPatch) -> Case:
    monkeypatch.setenv(ALPACA_API_KEY_ID_ENV, "AKFAKE00000000000000")
    monkeypatch.setenv(ALPACA_API_SECRET_ENV, "fakeSecretValueXYZ")
    t0 = datetime(2026, 1, 2, 14, 0, 0, tzinfo=UTC)
    asset = AssetRef(
        symbol="BTC/USD", venue="alpaca", asset_class="crypto", tick_size=Decimal("0.01")
    )
    rows = [
        _alpaca_bar(t0, 68123.4, 68300.0, 68050.0, 68210.5, 12.5),
        _alpaca_bar(t0 + timedelta(hours=1), 68210.5, 68400.0, 68150.0, 68300.0, 9.1),
    ]
    # H1: the multi-symbol crypto endpoint keys `bars` BY SYMBOL — never a
    # flat list (that shape belongs to the single-symbol equity endpoint).
    body = {"bars": {"BTC/USD": rows}, "next_page_token": None}
    return Case(
        id="alpaca-crypto",
        provider=AlpacaDataProvider(sleeper=_no_op_sleeper),
        asset=asset,
        timeframe="1h",
        start=t0,
        end=t0 + timedelta(hours=2),
        url=ALPACA_CRYPTO_BARS_URL,
        success_body=body,
        expected_source="alpaca",
    )


# One entry per provider this suite conforms — the ONLY place a future
# provider needs to be added (TD-18 "one factory entry" property).
CASE_BUILDERS: dict[str, Callable[[pytest.MonkeyPatch], Case]] = {
    "kraken": _kraken_case,
    "alpaca-equity": _alpaca_equity_case,
    "alpaca-crypto": _alpaca_crypto_case,
}


@pytest.fixture(params=list(CASE_BUILDERS), ids=list(CASE_BUILDERS))
def case(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Case:
    return CASE_BUILDERS[request.param](monkeypatch)


def test_bars_ascending_by_ts_open(case: Case, respx_mock) -> None:
    respx_mock.get(case.url).mock(return_value=httpx.Response(200, json=case.success_body))
    series = case.provider.get_bars(case.asset, case.timeframe, case.start, case.end)
    opens = [b.ts_open for b in series.bars]
    assert opens == sorted(opens), f"[{case.id}] bars must be ascending by ts_open"


def test_all_ts_open_are_aware_utc(case: Case, respx_mock) -> None:
    respx_mock.get(case.url).mock(return_value=httpx.Response(200, json=case.success_body))
    series = case.provider.get_bars(case.asset, case.timeframe, case.start, case.end)
    assert series.bars, f"[{case.id}] fixture must yield at least one bar to check"
    for bar in series.bars:
        assert bar.ts_open.tzinfo is not None, f"[{case.id}] ts_open must be aware, never naive"
        offset = bar.ts_open.utcoffset()
        assert offset is not None and offset.total_seconds() == 0, (
            f"[{case.id}] ts_open must be UTC, got offset {offset}"
        )


def test_all_ohlcv_fields_are_decimal(case: Case, respx_mock) -> None:
    respx_mock.get(case.url).mock(return_value=httpx.Response(200, json=case.success_body))
    series = case.provider.get_bars(case.asset, case.timeframe, case.start, case.end)
    assert series.bars, f"[{case.id}] fixture must yield at least one bar to check"
    for bar in series.bars:
        for field in ("open", "high", "low", "close", "volume"):
            value = getattr(bar, field)
            assert isinstance(value, Decimal), (
                f"[{case.id}] Bar.{field} must be Decimal, got {type(value).__name__}"
            )


def test_asset_and_timeframe_echo_the_request(case: Case, respx_mock) -> None:
    respx_mock.get(case.url).mock(return_value=httpx.Response(200, json=case.success_body))
    series = case.provider.get_bars(case.asset, case.timeframe, case.start, case.end)
    assert series.asset == case.asset, f"[{case.id}] BarSeries.asset must echo the request"
    assert series.timeframe == case.timeframe, (
        f"[{case.id}] BarSeries.timeframe must echo the request"
    )


def test_source_is_the_providers_literal_name(case: Case, respx_mock) -> None:
    respx_mock.get(case.url).mock(return_value=httpx.Response(200, json=case.success_body))
    series = case.provider.get_bars(case.asset, case.timeframe, case.start, case.end)
    assert series.source == case.expected_source, (
        f"[{case.id}] BarSeries.source must be the literal {case.expected_source!r}"
    )
    assert series.stale is False, (
        f"[{case.id}] a healthy primary-OHLCV response must never be marked stale — "
        "that flag is reserved for macro/supplementary providers (L7)"
    )


def test_http_5xx_raises_typed_provider_unavailable(case: Case, respx_mock) -> None:
    respx_mock.get(case.url).mock(return_value=httpx.Response(500, text="upstream error"))
    with pytest.raises(ProviderUnavailable):
        case.provider.get_bars(case.asset, case.timeframe, case.start, case.end)
