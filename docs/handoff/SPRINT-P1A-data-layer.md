# SPRINT P1A — Market data layer + cost model

> Executor: Sonnet. Reviewer: Opus. Prereqs: none (Kraken public needs no key; Alpaca paper keys exist; CoinGecko key = Mike). References: DESIGN §9.1, TD-8/12/16/17/22; canonical MAE doc §2 for endpoint mechanics (URLs/params there are accurate; its example *numbers* are not gospel).

## Mission

Everything MAE needs to fetch, normalize, cache, and price-friction market data — behind ports, with zero network in tests.

## New dependencies (this sprint only)

`uv add httpx tenacity` and dev `uv add --dev respx`. **Do NOT add pandas/numpy yet** — the canonical frame below is deliberately plain-Python; P1B decides the numeric representation.

## Interface pins (build EXACTLY these; internals are yours)

New private package `src/tradekit/mae/_data/` + one shared leaf module:

```python
# contracts additions (new file src/tradekit/contracts/_marketdata.py, re-exported):
class Bar(FrozenModel):
    ts_open: AwareDatetime          # bar OPEN time, UTC — canonical per TD-17
    open: Decimal; high: Decimal; low: Decimal; close: Decimal
    volume: Decimal
class BarSeries(FrozenModel):
    asset: AssetRef
    timeframe: str                  # "1m" | "5m" | "15m" | "1h" | "4h" | "1d"
    bars: list[Bar]                 # ascending ts_open, no gaps implied
    source: str                     # provider name — provenance always visible
    stale: bool = False             # provider degraded; consumer must see it (§13)

# src/tradekit/mae/_data/port.py:
class MarketDataPort(Protocol):
    def get_bars(self, asset: AssetRef, timeframe: str,
                 start: datetime, end: datetime) -> BarSeries: ...

# src/tradekit/costs.py  (shared leaf — imports ONLY contracts + stdlib, TD-8):
class Friction(FrozenModel):        # add to contracts
    fee_usd: Decimal
    half_spread_usd: Decimal
    slippage_usd: Decimal
    total_usd: Decimal
def price_friction(venue: str, asset_class: str, notional_usd: Decimal,
                   side: Literal["buy", "sell"]) -> Friction: ...
```

Providers (each a module in `_data/`): `kraken.py`, `alpaca_data.py`, `coingecko.py`, `macro.py` (yfinance — daily batch ONLY, defer if fragile), plus `cache.py` and `ratelimit.py`.

## Stories (in order, one commit-pair each)

1. ~~**contracts: Bar/BarSeries/Friction**~~ **DONE by Fable 2026-07-12** (`contracts/_marketdata.py` + tests via grading/costs suites). Note the actual Bar model also validates OHLC coherence, and `TIMEFRAME_SECONDS` lives in contracts — use it, don't redefine durations.
2. ~~**`tradekit.costs` v1**~~ **DONE by Fable 2026-07-12** (`src/tradekit/costs.py` + `tests/unit/test_costs.py`). Tables provisional per ASSUMPTIONS 26.
3. **Cache** (`data/cache.db`, SEPARATE file from ledger.db — TD-22): key (source, symbol, timeframe, ts_open); closed bars immutable → never invalidated; only the live (most recent, still-open) bar refetches. Tests: second fetch hits cache (respx call-count 1); live bar refetches; cache file deletable without breaking anything.
4. **Kraken provider** (public REST `/0/public/OHLC`, no key). Normalize: Kraken returns ≤720 bars, ts in seconds, strings for prices → Decimal via `str`, NEVER via float. Tests: respx fixtures with real captured response shapes; symbol mapping BTC/USD→XBTUSD; pagination beyond 720 raises `ProviderRangeError` for now (paginating Kraken OHLC is a known trap — its `since` semantics differ per endpoint; do NOT improvise, flag to Mike if needed).
5. **Rate limiter + retry**: per-provider token bucket (Kraken ~1 req/s polite; CoinGecko 100/min; Alpaca 200/min) + tenacity backoff on 5xx/timeouts. 4xx NEVER retries (it won't get better). Tests: fake clock, no sleeps.
6. **Alpaca data provider** (alpaca-py or raw httpx — implementer's choice, hide it) for equity + crypto bars. Same conformance tests as Kraken (see below).
7. **CoinGecko provider**: `/global` (BTC dominance) + `/coins/markets`. Needs Mike's key in `.env` as `COINGECKO_API_KEY`; tests use fixtures.
8. **Port conformance suite** (`tests/contract/test_marketdata_port.py`): ONE parametrized suite every provider passes — bars ascending, aware-UTC, Decimal types, stale flag on simulated provider failure (degrade, never raise, for macro; raise typed `ProviderUnavailable` for primaries). This is TD-18 ring 2 — the venue-swap safety net.

## Definition of done

- All stories green; `uv run pytest` zero network (respx enforced — add a conftest fixture that fails any unmocked HTTP call).
- One real-world smoke script `scripts/smoke_data.py` (NOT a test): fetches 30 days of BTC/USD 1h from Kraken live, prints head/tail — Mike runs it once to confirm reality matches fixtures.
- ROADMAP M1.1 boxes checked; dev-log entry.

## Traps

- Kraken pair naming is cursed (XBTUSD vs XXBTZUSD in responses). Normalize INSIDE the provider; nothing outside `_data/` ever sees venue symbols.
- Decimal from float is a bug everywhere in this repo. Providers must parse API strings directly.
- Do not put provider fallback logic in this sprint (that's regime/scanner concern) — one provider per asset class, typed errors.
- `stale=True` degradation is for macro/supplementary data only; primary OHLCV fetch failure must raise, or scans will silently run on old prices.
