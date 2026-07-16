"""tests/unit/mae_data/test_kraken.py — story 4: Kraken public OHLC provider
(`/0/public/OHLC`, no key).

Fixtures below mirror Kraken's REAL response shape: `result` is keyed by the
venue's own pair spelling ("XXBTZUSD"), rows are
[ts_sec, open, high, low, close, vwap, volume, count] with STRING prices, the
LAST row is the still-open bar, and a top-level "last" field (next `since`
cursor) sits alongside the pair key inside `result`.

Kraken's cursed pair-spelling split (request param "XBTUSD" vs response key
"XXBTZUSD") is normalized INSIDE KrakenProvider — nothing outside
tradekit.mae._data ever sees either spelling (sprint doc trap).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from tradekit.contracts import AssetRef
from tradekit.mae._data.errors import ProviderRangeError, ProviderRequestError, ProviderUnavailable
from tradekit.mae._data.kraken import KRAKEN_OHLC_URL, KrakenProvider

BTC_USD = AssetRef(
    symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01")
)


def _no_op_sleeper(_seconds: float) -> None:
    """No real sleep in unit tests (ASSUMPTIONS 30) — retries/backoff must
    never block the suite; provider construction below injects this instead
    of the real time.sleep default."""


class FakeClock:
    """Monotonic fake clock: advances only when the test tells it to (mirrors
    test_ratelimit.py's own FakeClock — kept local here since this module
    tests provider-level bucket WIRING, not TokenBucket itself)."""

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def __call__(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


def _kraken_ohlc_fixture(rows: list[list]) -> dict:
    """Realistic /0/public/OHLC success body."""
    return {
        "error": [],
        "result": {
            "XXBTZUSD": rows,
            "last": rows[-1][0] if rows else 0,
        },
    }


def _row(ts_sec: int, o: str, h: str, low: str, c: str, vwap: str, vol: str, count: int) -> list:
    return [ts_sec, o, h, low, c, vwap, vol, count]


@pytest.fixture
def provider() -> KrakenProvider:
    # sleeper=no-op (ASSUMPTIONS 30 / H2): with retry now wired into every
    # call, a persistent 5xx mock triggers real backoff sleeps unless the
    # provider is built with a non-blocking sleeper.
    return KrakenProvider(sleeper=_no_op_sleeper)


def test_symbol_mapping_btcusd_to_xbtusd_request_and_xxbtzusd_response(
    provider, respx_mock
) -> None:
    """BTC/USD -> request param pair=XBTUSD; response result key XXBTZUSD is
    the one read back. Both mappings live inside the provider."""
    t0 = int(datetime(2026, 1, 1, 0, 0, tzinfo=UTC).timestamp())
    rows = [
        _row(t0, "68100.0", "68150.0", "68050.0", "68123.4", "68110.0", "12.5", 50),
        _row(t0 + 3600, "68123.4", "68300.0", "68100.0", "68250.0", "68200.0", "9.1", 40),
    ]
    route = respx_mock.get(KRAKEN_OHLC_URL).mock(
        return_value=httpx.Response(200, json=_kraken_ohlc_fixture(rows))
    )

    start = datetime.fromtimestamp(t0, tz=UTC)
    end = datetime.fromtimestamp(t0 + 7200, tz=UTC)
    series = provider.get_bars(BTC_USD, "1h", start, end)

    assert route.call_count == 1
    sent_params = route.calls.last.request.url.params
    assert sent_params["pair"] == "XBTUSD", (
        f"expected the venue-spelled request param 'XBTUSD' for BTC/USD, got "
        f"{sent_params.get('pair')!r} — symbol mapping must happen inside KrakenProvider"
    )
    assert len(series.bars) == 2, "must read the XXBTZUSD response key, not fail to find data"


def test_prices_parsed_as_decimal_from_kraken_strings_exactly(provider, respx_mock) -> None:
    t0 = int(datetime(2026, 1, 1, 0, 0, tzinfo=UTC).timestamp())
    rows = [_row(t0, "68123.4", "68200.0", "68100.0", "68150.0", "68140.0", "5.0", 10)]
    respx_mock.get(KRAKEN_OHLC_URL).mock(
        return_value=httpx.Response(200, json=_kraken_ohlc_fixture(rows))
    )

    start = datetime.fromtimestamp(t0, tz=UTC)
    end = datetime.fromtimestamp(t0 + 3600, tz=UTC)
    series = provider.get_bars(BTC_USD, "1h", start, end)

    bar = series.bars[0]
    assert bar.open == Decimal("68123.4"), (
        f"got {bar.open!r} — Kraken's OHLC strings must parse via Decimal(str), never via "
        "float(...), or prices silently corrupt (repo-wide rule)"
    )
    assert isinstance(bar.open, Decimal)
    assert bar.high == Decimal("68200.0")
    assert bar.low == Decimal("68100.0")
    assert bar.close == Decimal("68150.0")


def test_ts_seconds_become_aware_utc_ts_open(provider, respx_mock) -> None:
    t0 = int(datetime(2026, 3, 5, 12, 30, 0, tzinfo=UTC).timestamp())
    rows = [_row(t0, "1", "1", "1", "1", "1", "1", 1)]
    respx_mock.get(KRAKEN_OHLC_URL).mock(
        return_value=httpx.Response(200, json=_kraken_ohlc_fixture(rows))
    )
    start = datetime.fromtimestamp(t0, tz=UTC)
    end = datetime.fromtimestamp(t0 + 3600, tz=UTC)
    series = provider.get_bars(BTC_USD, "1h", start, end)

    assert series.bars[0].ts_open == datetime(2026, 3, 5, 12, 30, 0, tzinfo=UTC)
    assert series.bars[0].ts_open.tzinfo is not None, (
        "epoch seconds must become aware-UTC, never naive"
    )


def test_bars_ascending_and_source_is_kraken(provider, respx_mock) -> None:
    t0 = int(datetime(2026, 1, 1, 0, 0, tzinfo=UTC).timestamp())
    rows = [
        _row(t0, "1", "1", "1", "1", "1", "1", 1),
        _row(t0 + 3600, "1", "1", "1", "1", "1", "1", 1),
        _row(t0 + 7200, "1", "1", "1", "1", "1", "1", 1),
    ]
    respx_mock.get(KRAKEN_OHLC_URL).mock(
        return_value=httpx.Response(200, json=_kraken_ohlc_fixture(rows))
    )
    start = datetime.fromtimestamp(t0, tz=UTC)
    end = datetime.fromtimestamp(t0 + 10800, tz=UTC)
    series = provider.get_bars(BTC_USD, "1h", start, end)

    opens = [b.ts_open for b in series.bars]
    assert opens == sorted(opens), "bars must come back strictly ascending by ts_open"
    assert series.source == "kraken", "BarSeries.source must always be the literal 'kraken'"


def test_range_over_720_bars_raises_provider_range_error_no_http_call(provider, respx_mock) -> None:
    """Kraken OHLC returns at most ~720 bars per call; a wider request must
    raise BEFORE hitting the network, not silently truncate or paginate
    (pagination's `since` semantics are a known trap, out of scope)."""
    route = respx_mock.get(KRAKEN_OHLC_URL).mock(
        return_value=httpx.Response(200, json=_kraken_ohlc_fixture([]))
    )
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(minutes=721)  # 721 one-minute bars > 720 cap

    with pytest.raises(ProviderRangeError):
        provider.get_bars(BTC_USD, "1m", start, end)
    assert route.call_count == 0, (
        "an over-range request must be rejected before any HTTP call is made — "
        f"got {route.call_count} calls"
    )


def test_http_failure_raises_provider_unavailable_never_stale(provider, respx_mock) -> None:
    """Primary OHLCV data never degrades silently: an HTTP failure must
    raise ProviderUnavailable, never return a stale=True BarSeries."""
    respx_mock.get(KRAKEN_OHLC_URL).mock(return_value=httpx.Response(500, text="upstream error"))
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)

    with pytest.raises(ProviderUnavailable):
        provider.get_bars(BTC_USD, "1h", start, end)


# ---------------------------------------------------------------------------
# H2/M3/M4 — ratelimit + retry wiring, 4xx typing, malformed-body handling
# ---------------------------------------------------------------------------


def test_retries_5xx_then_succeeds_exactly_three_calls_no_real_sleep(
    provider, respx_mock
) -> None:
    """H2: every provider call now goes through call_with_retry. Two 500s
    then a 200 must succeed with exactly 3 HTTP calls, no real sleep (the
    `provider` fixture already injects a no-op sleeper)."""
    t0 = int(datetime(2026, 1, 1, 0, 0, tzinfo=UTC).timestamp())
    rows = [_row(t0, "1", "1", "1", "1", "1", "1", 1)]
    route = respx_mock.get(KRAKEN_OHLC_URL).mock(
        side_effect=[
            httpx.Response(500, text="upstream error"),
            httpx.Response(500, text="upstream error"),
            httpx.Response(200, json=_kraken_ohlc_fixture(rows)),
        ]
    )
    start = datetime.fromtimestamp(t0, tz=UTC)
    end = start + timedelta(hours=1)

    series = provider.get_bars(BTC_USD, "1h", start, end)

    assert len(series.bars) == 1
    assert route.call_count == 3, (
        f"expected exactly 3 HTTP calls (2 failures + 1 success), got {route.call_count}"
    )


def test_http_4xx_raises_provider_request_error_one_call(provider, respx_mock) -> None:
    """M3: a 4xx must never be retried — it is rejected as ProviderRequestError
    after exactly one HTTP call."""
    route = respx_mock.get(KRAKEN_OHLC_URL).mock(
        return_value=httpx.Response(404, text="not found")
    )
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)

    with pytest.raises(ProviderRequestError):
        provider.get_bars(BTC_USD, "1h", start, end)
    assert route.call_count == 1, (
        f"a 4xx must not be retried — expected exactly 1 HTTP call, got {route.call_count}"
    )


def test_malformed_200_body_raises_provider_unavailable(provider, respx_mock) -> None:
    """M4: a structurally garbage 200 body (missing the "result" key
    entirely — not the same as a legitimate empty pair result) must raise
    ProviderUnavailable naming Kraken, never an untyped KeyError."""
    respx_mock.get(KRAKEN_OHLC_URL).mock(
        return_value=httpx.Response(200, json={"unexpected": True})
    )
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)

    with pytest.raises(ProviderUnavailable, match=r"(?i)kraken"):
        provider.get_bars(BTC_USD, "1h", start, end)


def test_bucket_wiring_second_call_waits_for_token(respx_mock) -> None:
    """H2 bucket-wiring pin: Kraken's bucket is capacity=1, rate=1/s. Two
    sequential get_bars calls with a fake clock that only advances via the
    injected sleeper must show the SECOND call waiting (sleeper invoked with
    a positive wait) — the first call spends the initial burst token for
    free."""
    clock = FakeClock(start=0.0)
    waits: list[float] = []

    def _advancing_sleeper(seconds: float) -> None:
        waits.append(seconds)
        clock.advance(seconds)

    provider = KrakenProvider(clock=clock, sleeper=_advancing_sleeper)

    t0 = int(datetime(2026, 1, 1, 0, 0, tzinfo=UTC).timestamp())
    rows = [_row(t0, "1", "1", "1", "1", "1", "1", 1)]
    respx_mock.get(KRAKEN_OHLC_URL).mock(
        return_value=httpx.Response(200, json=_kraken_ohlc_fixture(rows))
    )
    start = datetime.fromtimestamp(t0, tz=UTC)
    end = start + timedelta(hours=1)

    provider.get_bars(BTC_USD, "1h", start, end)
    assert waits == [], "the first call must spend the free burst token, no waiting"

    provider.get_bars(BTC_USD, "1h", start, end)
    assert waits, (
        "the second call must wait for a token (capacity 1, rate 1/s, no time elapsed "
        "between calls) — sleeper was never invoked"
    )
    assert all(w > 0 for w in waits), f"every wait must be positive, got {waits}"


def test_pair_mapping_tables_are_consistent_and_cover_mikes_universe() -> None:
    """P1C smoke catch: scan_markets against SOL/USD died on a missing pair
    mapping — the P1A tables only covered BTC/ETH. Pins (a) every request
    pair has a response result key, and (b) Mike's crypto universe is
    mapped. Result keys for the five modern pairs were verified against the
    LIVE Kraken OHLC endpoint 2026-07-17 (they echo the request name; only
    legacy BTC/ETH use the X/Z spelling)."""
    from tradekit.mae._data.kraken import _KRAKEN_RESULT_KEY, _SYMBOL_TO_KRAKEN_PAIR

    for symbol, pair in _SYMBOL_TO_KRAKEN_PAIR.items():
        assert pair in _KRAKEN_RESULT_KEY, f"{symbol} maps to {pair} with no result key"

    for symbol in ("ETH/USD", "SOL/USD", "LINK/USD", "NEAR/USD", "TAO/USD", "EIGEN/USD"):
        assert symbol in _SYMBOL_TO_KRAKEN_PAIR, f"universe symbol {symbol} unmapped"

    for modern in ("SOLUSD", "LINKUSD", "NEARUSD", "TAOUSD", "EIGENUSD"):
        assert _KRAKEN_RESULT_KEY[modern] == modern
