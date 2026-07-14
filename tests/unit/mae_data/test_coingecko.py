"""tests/unit/mae_data/test_coingecko.py — story 7: CoinGecko provider
(`/api/v3/global` for BTC dominance, `/api/v3/coins/markets` for ranked coin
markets).

`CoinGeckoProvider` has TWO methods (`get_global`, `get_markets`) and is
deliberately NOT a `MarketDataPort` — it supplies supplementary macro data,
not OHLCV bars (ASSUMPTIONS 34). It is excluded from the story-8 conformance
suite in `tests/contract/test_marketdata_port.py` for the same reason.

SUPPLEMENTARY-DATA POLICY (pinned by both `test_*_http_failure_raises_
provider_unavailable` tests below, ASSUMPTIONS 34): the sprint doc's
"degrade to stale=True, never raise" language is reserved for the
macro/yfinance provider, which THIS sprint defers. CoinGecko itself still
RAISES `ProviderUnavailable` on HTTP failure — it does not have a `stale`
concept at all (its return types, `GlobalCrypto`/`CoinMarket`, carry no
`stale` field). Do not conflate the two providers' failure policies.

TDD status: this test file targets `CoinGeckoProvider`, currently a
`NotImplementedError` stub (`src/tradekit/mae/_data/coingecko.py`) — every
test here is expected RED until story 7 is implemented.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from tradekit.mae._data.coingecko import (
    COINGECKO_API_KEY_ENV,
    COINGECKO_GLOBAL_URL,
    COINGECKO_MARKETS_URL,
    CoinGeckoProvider,
)
from tradekit.mae._data.errors import ProviderRequestError, ProviderUnavailable


def _global_fixture(btc_pct: float, total_cap_usd: float, updated_at: int) -> dict:
    """Realistic /api/v3/global success body (trimmed to the fields we use)."""
    return {
        "data": {
            "active_cryptocurrencies": 17400,
            "markets": 1300,
            "total_market_cap": {"usd": total_cap_usd, "eur": total_cap_usd * 0.92},
            "total_volume": {"usd": 98_000_000_000.0},
            "market_cap_percentage": {"btc": btc_pct, "eth": 12.1},
            "market_cap_change_percentage_24h_usd": 1.23,
            "updated_at": updated_at,
        }
    }


def _markets_fixture() -> list[dict]:
    """Realistic /api/v3/coins/markets success body (trimmed to used fields)."""
    return [
        {
            "id": "bitcoin",
            "symbol": "btc",
            "name": "Bitcoin",
            "current_price": 68123.4,
            "market_cap": 1_345_678_901_234,
            "market_cap_rank": 1,
        },
        {
            "id": "ethereum",
            "symbol": "eth",
            "name": "Ethereum",
            "current_price": 3456.78,
            "market_cap": 415_678_901_234,
            "market_cap_rank": 2,
        },
    ]


def _no_op_sleeper(_seconds: float) -> None:
    """No real sleep in unit tests (ASSUMPTIONS 30) — retries/backoff must
    never block the suite."""


@pytest.fixture
def provider() -> CoinGeckoProvider:
    # sleeper=no-op (ASSUMPTIONS 30 / H2): retry is now wired into every
    # call; a persistent 5xx mock must not trigger real backoff sleeps.
    return CoinGeckoProvider(sleeper=_no_op_sleeper)


@pytest.fixture(autouse=True)
def _coingecko_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default happy-path demo key; individual tests delete it."""
    monkeypatch.setenv(COINGECKO_API_KEY_ENV, "CG-fake-demo-key-0000")


def test_get_global_parses_btc_dominance_market_cap_and_ts(provider, respx_mock) -> None:
    updated_at = int(datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC).timestamp())
    fixture = _global_fixture(54.32, 2_500_000_000_000.12, updated_at)
    respx_mock.get(COINGECKO_GLOBAL_URL).mock(return_value=httpx.Response(200, json=fixture))

    result = provider.get_global()

    assert result.btc_dominance_pct == Decimal("54.32")
    assert result.total_market_cap_usd == Decimal("2500000000000.12")
    assert result.ts == datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    assert result.ts.tzinfo is not None, "updated_at (unix seconds) must become aware-UTC"


def test_get_markets_parses_ranked_coin_market_list(provider, respx_mock) -> None:
    respx_mock.get(COINGECKO_MARKETS_URL).mock(
        return_value=httpx.Response(200, json=_markets_fixture())
    )

    result = provider.get_markets(vs="usd", per_page=100)

    assert len(result) == 2
    btc, eth = result
    assert btc.coingecko_id == "bitcoin"
    assert btc.symbol == "btc"
    assert btc.price_usd == Decimal("68123.4")
    assert btc.market_cap_usd == Decimal("1345678901234")
    assert btc.rank == 1
    assert eth.rank == 2, "market_cap_rank ordering must pass through, rank 1 = largest cap"


def test_api_key_sent_as_query_param_on_both_endpoints(provider, respx_mock) -> None:
    global_route = respx_mock.get(COINGECKO_GLOBAL_URL).mock(
        return_value=httpx.Response(
            200,
            json=_global_fixture(
                54.32, 2_500_000_000_000.12, int(datetime(2026, 3, 1, tzinfo=UTC).timestamp())
            ),
        )
    )
    markets_route = respx_mock.get(COINGECKO_MARKETS_URL).mock(
        return_value=httpx.Response(200, json=_markets_fixture())
    )

    provider.get_global()
    provider.get_markets()

    assert global_route.calls.last.request.url.params["x_cg_demo_api_key"] == (
        "CG-fake-demo-key-0000"
    )
    assert markets_route.calls.last.request.url.params["x_cg_demo_api_key"] == (
        "CG-fake-demo-key-0000"
    )


def test_get_markets_sends_vs_currency_and_per_page_query_params(provider, respx_mock) -> None:
    route = respx_mock.get(COINGECKO_MARKETS_URL).mock(
        return_value=httpx.Response(200, json=_markets_fixture())
    )

    provider.get_markets(vs="usd", per_page=50)

    sent = route.calls.last.request.url.params
    assert sent["vs_currency"] == "usd"
    assert sent["per_page"] == "50"


def test_missing_api_key_env_raises_provider_request_error_no_network_call_get_global(
    provider, respx_mock, monkeypatch
) -> None:
    monkeypatch.delenv(COINGECKO_API_KEY_ENV, raising=False)
    route = respx_mock.get(COINGECKO_GLOBAL_URL).mock(
        return_value=httpx.Response(
            200,
            json=_global_fixture(
                54.32, 2_500_000_000_000.12, int(datetime(2026, 3, 1, tzinfo=UTC).timestamp())
            ),
        )
    )

    with pytest.raises(ProviderRequestError, match="COINGECKO_API_KEY"):
        provider.get_global()
    assert route.call_count == 0, (
        f"missing COINGECKO_API_KEY must be rejected before any HTTP call — got "
        f"{route.call_count} calls"
    )


def test_missing_api_key_env_raises_provider_request_error_no_network_call_get_markets(
    provider, respx_mock, monkeypatch
) -> None:
    monkeypatch.delenv(COINGECKO_API_KEY_ENV, raising=False)
    route = respx_mock.get(COINGECKO_MARKETS_URL).mock(
        return_value=httpx.Response(200, json=_markets_fixture())
    )

    with pytest.raises(ProviderRequestError, match="COINGECKO_API_KEY"):
        provider.get_markets()
    assert route.call_count == 0, (
        f"missing COINGECKO_API_KEY must be rejected before any HTTP call — got "
        f"{route.call_count} calls"
    )


def test_get_global_http_failure_raises_provider_unavailable(provider, respx_mock) -> None:
    """See module docstring: CoinGecko's own failure policy is RAISE, not
    degrade-to-stale (that's the deferred macro/yfinance story's policy)."""
    respx_mock.get(COINGECKO_GLOBAL_URL).mock(
        return_value=httpx.Response(500, text="upstream error")
    )

    with pytest.raises(ProviderUnavailable):
        provider.get_global()


def test_get_markets_http_failure_raises_provider_unavailable(provider, respx_mock) -> None:
    """Same supplementary-data policy as get_global (ASSUMPTIONS 34): raise,
    never silently return a stale/partial list."""
    respx_mock.get(COINGECKO_MARKETS_URL).mock(
        return_value=httpx.Response(503, text="service unavailable")
    )

    with pytest.raises(ProviderUnavailable):
        provider.get_markets()


# ---------------------------------------------------------------------------
# M3/M4 — 4xx typing, malformed-body handling (review round 2)
# ---------------------------------------------------------------------------


def test_http_4xx_raises_provider_request_error_one_call(provider, respx_mock) -> None:
    """M3: a 4xx must be typed ProviderRequestError and never retried —
    exactly one HTTP call."""
    route = respx_mock.get(COINGECKO_GLOBAL_URL).mock(
        return_value=httpx.Response(404, text="not found")
    )

    with pytest.raises(ProviderRequestError):
        provider.get_global()
    assert route.call_count == 1, (
        f"a 4xx must not be retried — expected exactly 1 HTTP call, got {route.call_count}"
    )


def test_malformed_200_body_raises_provider_unavailable(provider, respx_mock) -> None:
    """M4: a structurally garbage 200 body (missing the "data" envelope)
    must raise ProviderUnavailable naming CoinGecko, never an untyped
    KeyError."""
    respx_mock.get(COINGECKO_GLOBAL_URL).mock(
        return_value=httpx.Response(200, json={"unexpected": True})
    )

    with pytest.raises(ProviderUnavailable, match=r"(?i)coingecko"):
        provider.get_global()
