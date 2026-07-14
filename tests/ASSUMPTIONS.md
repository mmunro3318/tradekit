# Test-suite assumptions pending CTO ratification

Where DESIGN.md leaves a contract detail open, the tests pin the minimal obvious shape below. Ratify or correct each line BEFORE implementation; changing one later means changing the tests in the same commit.

1. `quantize` rounds exact midpoints with **ROUND_HALF_EVEN** (banker's rounding) — pinned in `test_quantize.py::test_midpoint_rounding_pinned_half_even`.
2. `quantize` accepts both `float` and `Decimal` input and returns a `Decimal` carrying the tick's exponent (e.g. scale -2 for tick 0.01).
3. `Predicate` and `InvalidationSpec` validate as discriminated unions on a `kind` field; tests construct them from dicts via `pydantic.TypeAdapter`, so either a union type-alias export or a base-model export satisfies the suite.
4. `InvalidationSpec` kinds are `"measurable"` (field `predicate: Predicate`) and `"structural"` (fields `description: str` nonempty, `requires_attestation: bool` defaulting/forced to `True`).
5. Predicate variants reject undeclared fields (`extra="forbid"` or equivalent) — that is how `time_expiry` rejects `cmp`/`value` being set.
6. `AssetRef` fields: `symbol`, `venue`, `asset_class`, `tick_size` (Decimal).
7. `EntrySpec` fields: `order_type`, `limit_price`, `valid_until` (per §5.1 "order_type, limit/trigger price, valid_until").
8. `EVBlock` fields: `p_win`, `reward_usd`, `risk_usd`, `ev_usd`; the `*_usd` fields are `Decimal` (p_win's exact numeric type is unpinned, but it must be numeric — prose rejects).
9. `Event` envelope field names: `event_id`, `ts_utc`, `type`, `actor`, `run_id` (optional/None allowed), `schema_ver`, `payload`; matches the §6.2 column list.
10. The `Event` envelope accepts a plain JSON-object `dict` as `payload`; per-type typed payload models are a producer-side concern, not enforced at the envelope. (If the envelope DOES validate payloads per type, the fixture payloads in `conftest.py` must be updated to match the typed models.)
11. `Event.type` is validated against the §6.3 v1 taxonomy at the envelope — an unknown type is a `ValidationError`.
12. `EventFilter` minimal shape: `types: list[str] | None`, `since: datetime | None`, `until: datetime | None`, all defaulting to None; `EventFilter()` (empty) matches everything. Boundary inclusivity of since/until is deliberately NOT pinned (test timestamps avoid the boundaries).
13. `ChainReport` minimal shape: `ok: bool`, `first_bad_seq: int | None` (None when ok).
14. `Ledger.append` returns the event_id of the persisted row; tests use the returned value rather than assuming the caller-supplied `event_id` is kept verbatim.
15. TK_RUN_ID stamping happens at append time and only fills a missing `run_id`; an explicit `run_id` on the event always wins.
16. Read-model projections live as SQLite tables inside `ledger.db`; the runs projection is a table named `runs` with one row per `RunStarted` event. Tests observe/corrupt projections via raw `sqlite3` as a harness action (never importing ledger internals).
17. `Ledger.search` returns a list of `Event` models and returns `[]` (never raises) on no match.
18. `ts_utc` on the `Event` model is a timezone-aware UTC `datetime` (serialized ISO-8601 in the DB per §6.2).
19. Two `Ledger` instances open on the same file concurrently is a supported, non-erroring topology (TD-16 WAL + busy_timeout); the suite smoke-tests interleaved appends from two handles.

---

## CTO ratification — 2026-07-12

All 19 assumptions **ratified** as written, with one scope note:

- (10) Ratified for P0: the envelope accepts plain-dict payloads with taxonomy
  validation on `type`. Typed per-event payload models land WITH their producing
  subsystems (P2/P3) — designing ~28 payload shapes before those subsystems
  exist would be designing against vapor. ROADMAP M0.2 updated to match.
- (1) ROUND_HALF_EVEN confirmed — banker's rounding is the financial standard.
- (12) since/until boundary inclusivity: implementation should treat both as
  INCLUSIVE and document it; tests deliberately avoid the boundary so this is
  not load-bearing yet.

Changing any ratified line later requires updating tests + this file in the
same commit (DESIGN maintenance rule applies here too).

---

## Round-2 additions — reviewer FIX-FIRST round, 2026-07-12 (CTO)

20. Every boundary datetime in contracts (`EventFilter.since/until`,
    `Predicate.by`, `EntrySpec.valid_until`, `ThesisContract.horizon_end`) is
    pydantic `AwareDatetime` — naive datetimes are a ValidationError, never
    machine-local guesswork (TD-17, reviewer D2).
21. Event payloads must be JSON-native; `Ledger.append` raises TypeError on
    anything `json.dumps` cannot represent without a fallback (no silent
    str-coercion; reviewer D4). Sharpens assumption 10.
22. `event_id`/`actor`/`run_id` reject control characters (< 0x20) at the
    envelope; the hash preimage additionally length-prefixes every field and
    uses a non-"" NULL marker, so field boundaries are unforgeable even for
    adversarially-authored rows (reviewer D3).

---

## Round-3 additions — Fable final session, 2026-07-12

23. **Internal-test exception (temporary):** tests for `thesis._grading` and
    `mae._sizing` import those internals directly because their public verbs
    (`thesis.grade`, `mae.size_position`) lack wiring until P2/P1C. When the
    verb lands: re-point the tests through the public surface AND add the
    internal to the TID251 ban list, same commit. These are the only two
    permitted internal imports in tests/.
24. One thesis = ONE predicate timeframe (MVP): `evaluate_criteria` raises on
    mixed timeframes. Lifting this is a DESIGN change, not a bug fix.
25. Same-bar grading priority is **failure > invalidation > success**, and
    horizon expiry = FAIL. Every ambiguity resolves AGAINST the agent —
    anti-gaming, pinned by tests in tests/unit/thesis/.
26. `tradekit.costs` tables are PROVISIONAL (seeded from SME §5) until P4
    live fills measure reality; update the table constants + these tests
    together, never scatter cost numbers elsewhere (TD-8).

---

## Round-4 additions — P1A stories 3-5 TDD session, 2026-07-14

27. **Zero-network enforcement** (P1A DoD) lives as an autouse fixture in
    `tests/conftest.py` (`_no_unmocked_network`) that depends on respx's own
    `respx_mock` pytest fixture. respx's default (`assert_all_mocked=True`)
    means any httpx call not matched by a registered route raises
    `AllMockedAssertionError` instead of touching the network. Being autouse,
    it guards the WHOLE suite, not just `tests/unit/mae_data/`; individual
    tests that need HTTP responses request `respx_mock` by name (same cached
    fixture instance) and register routes on it as normal. Pinned by
    `tests/unit/mae_data/test_network_guard.py`.
28. **BarCache design** (story 3, `src/tradekit/mae/_data/cache.py`):
    `get_or_fetch` wraps a provider CALLABLE
    (`provider_fn(asset, timeframe, start, end) -> BarSeries`), not a
    `MarketDataPort` object — cache.py has zero import dependency on any
    specific provider module. A bar is CLOSED (cacheable, immutable) when its
    close time (`ts_open + TIMEFRAME_SECONDS[timeframe]`) is `<=` the query's
    own `end`; `end` doubles as the caller's freshness cutoff, so no separate
    injected clock object is needed for the cache layer (TD-17 "no real
    clock" satisfied by making time an explicit argument). The most recent
    bar whose close time is `>` `end` is the still-open "live" bar: never
    persisted, always refetched.
29. **TEST-PATH EXCEPTION (extends assumption 23):** `tests/unit/mae_data/*`
    import `tradekit.mae._data` internals (`cache`, `kraken`, `ratelimit`,
    `errors`, `port`) directly. No public verb wraps `_data` yet — P1A
    stories 3-5 (cache, Kraken provider, rate limiter) precede the port
    conformance suite (story 8) and any public wiring (P1C+), which are out
    of scope for this handoff. When a public verb lands: re-point these
    tests through it AND add the internals to the TID251 ban list in
    `pyproject.toml`, same commit — same discipline as assumption 23.
30. **Rate limiter clock/sleep injection** (story 5,
    `src/tradekit/mae/_data/ratelimit.py`): `TokenBucket` is non-blocking
    (`try_acquire() -> bool`) and takes an injected
    `clock: Callable[[], float]` (monotonic seconds) rather than sleeping
    itself — callers/tests advance the fake clock explicitly instead of
    waiting. `call_with_retry` takes an injected
    `sleeper: Callable[[float], None]` instead of calling `time.sleep`
    directly. `tests/unit/mae_data/test_ratelimit.py::
    test_retry_never_calls_real_time_sleep` monkeypatches `time.sleep` to
    raise if ever invoked, pinning this as structural, not incidental.
31. **Kraken range-guard ordering** (story 4,
    `src/tradekit/mae/_data/kraken.py`): the `ProviderRangeError` check (>720
    bars implied by the requested range) must happen BEFORE any HTTP call —
    pinned by `test_kraken.py::
    test_range_over_720_bars_raises_provider_range_error_no_http_call`
    asserting the respx route's `call_count == 0`. Pagination itself remains
    out of scope (sprint doc trap: Kraken's `since` semantics differ per
    endpoint).

---

## Round-5 additions — P1A stories 6-8 TDD session (red only), 2026-07-14

32. **Alpaca numeric-price Decimal(str()) caveat** (story 6,
    `src/tradekit/mae/_data/alpaca_data.py`): unlike Kraken, Alpaca's bar
    endpoints return prices as JSON NUMBERS, not strings. The provider must
    still convert every price via `Decimal(str(x))`, never `Decimal(x)` on
    the raw float — `Decimal(189.43)` captures the float's binary
    representation noise (`Decimal('189.4299999999999997157829...')`) while
    `Decimal(str(189.43)) == Decimal("189.43")` is exact. Pinned by
    `test_alpaca.py::test_prices_converted_via_decimal_str_from_json_numbers`,
    which asserts the two forms are unequal as a sanity check on the trap
    itself, then asserts the provider's actual output matches the
    string-routed value.
33. **Pagination-out-of-scope policy extends to Alpaca** (story 6): a
    non-null `next_page_token` in an Alpaca bars response must raise
    `ProviderRangeError`, the same policy as Kraken's >720-bar guard
    (ASSUMPTIONS 31) — provider-side pagination is out of scope for this
    sprint for every provider, not just Kraken. Alpaca's timeframe map
    (`"1m"→"1Min"`, `"1h"→"1Hour"`, `"1d"→"1Day"`) lives in
    `ALPACA_TIMEFRAME_MAP`, the one place that spelling is defined, mirroring
    Kraken's `_SYMBOL_TO_KRAKEN_PAIR` pattern.
34. **CoinGecko is not a MarketDataPort** (story 7,
    `src/tradekit/mae/_data/coingecko.py`): `CoinGeckoProvider` exposes
    `get_global() -> GlobalCrypto` and `get_markets() -> list[CoinMarket]`,
    not `get_bars`, and is therefore excluded from the story-8 conformance
    suite (`tests/contract/test_marketdata_port.py`). Its failure policy is
    also narrower than the sprint doc's general "macro degrades to
    `stale=True`" language: THAT policy belongs to the deferred
    macro/yfinance provider. CoinGecko itself has no `stale` concept (neither
    `GlobalCrypto` nor `CoinMarket` carries a `stale` field) and RAISES
    `ProviderUnavailable` on HTTP failure, same as every primary OHLCV
    provider. Changing this later (e.g. giving CoinGecko a stale/degrade path)
    is a DESIGN change, not a bug fix.
35. **Provider env-var key names are pinned, not configurable**: Alpaca
    reads `ALPACA_API_KEY_ID` / `ALPACA_API_SECRET` (sent as the
    `APCA-API-KEY-ID` / `APCA-API-SECRET-KEY` headers); CoinGecko reads
    `COINGECKO_API_KEY` (sent as the `x_cg_demo_api_key` query param, matching
    CoinGecko's own demo-tier parameter name). Either provider missing its
    required env var(s) raises a typed `ProviderRequestError` naming the
    missing var, with NO network call made — mirrors the Kraken range-guard
    "fail before the request" pattern (ASSUMPTIONS 31).

---

## Round-6 additions — P1A review-round-2 fixes (Opus review, FIX-FIRST), 2026-07-14

36. **Alpaca crypto `bars` is keyed BY SYMBOL** (H1, confirmed against
    Alpaca's OpenAPI spec — MultiBarsResponse): the multi-symbol
    `/v1beta3/crypto/us/bars` endpoint returns
    `{"bars": {"BTC/USD": [...]}, "next_page_token": ...}`, NOT a flat list;
    only the single-symbol equity endpoint (`/v2/stocks/{symbol}/bars`) is
    flat. The provider reads `body["bars"][asset.symbol]`; a MISSING symbol
    key means zero bars in the window (empty series), not an error. Pinned by
    `test_alpaca.py::test_crypto_route_uses_symbols_query_param_btcusd` and
    `::test_crypto_response_missing_requested_symbol_key_yields_empty_series`
    plus the conformance suite's `alpaca-crypto` case. (The original round-5
    fixtures used the flat shape for both endpoints — a CTO-authorized
    fixture correction, review round 2.)
37. **Rate limiting/retry is WIRED into every provider** (H2/M3/M4/L6):
    each provider constructor takes keyword-only
    `clock: Callable[[], float] = time.monotonic` and
    `sleeper: Callable[[float], None] = time.sleep`, owns a per-instance
    `bucket_for(name, clock=clock)`, and routes every HTTP call through
    `acquire_blocking(bucket, sleeper)` (wait computed via
    `TokenBucket.seconds_until_token()`, never spun) then
    `call_with_retry(fn, max_attempts=3, sleeper=sleeper)`. Taxonomy: HTTP
    4xx -> `ProviderRequestError` after exactly ONE call (never retried);
    5xx and `httpx.TimeoutException` (caught INSIDE `call_with_retry`) retry
    with backoff, exhausted -> `ProviderUnavailable`; a structurally
    malformed 200 body -> `ProviderUnavailable` naming the provider. Unit
    tests constructing providers against persistent-5xx mocks MUST inject a
    no-op sleeper or retries real-sleep the suite.
38. **BarCache mixed closed+live ranges serve the cached closed prefix**
    (M5, refines assumption 28): when `end` sits inside a live bar, the
    cached closed prefix is served from cache.db and `provider_fn` is called
    ONLY for the uncovered suffix — from the first uncached expected
    ts_open, or from the live bar's own open if every closed bar is cached;
    results merge ascending and newly-closed bars upsert. Fully-closed
    ranges keep the all-or-nothing read. Pinned by `test_cache.py::
    test_mixed_closed_plus_live_range_serves_cached_prefix_fetches_only_live_suffix`.
