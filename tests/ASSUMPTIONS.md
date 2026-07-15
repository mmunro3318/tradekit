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

---

## Round-7 additions — P1B stories 1-3 TDD session (red only), 2026-07-15

39. **TEST-PATH EXCEPTION (extends assumptions 23/29):**
    `tests/unit/mae_indicators/*` import `tradekit.mae._indicators`
    submodules (`volatility`, `momentum`, `trend`, `volume`, `structure`)
    directly — no public verb wires `_indicators` into `scan_markets` yet
    (P1C+), same shape as the `mae._data` exception (assumption 29). When a
    public verb lands: re-point these tests through it AND add
    `tradekit.mae._indicators.volatility` / `.momentum` / `.trend` /
    `.volume` / `.structure` to the `TID251` ban list in `pyproject.toml`,
    same commit — same discipline as assumptions 23/29.
40. **ADX's internal Wilder-smoothing seed window starts at index 1, not
    index 0** (story 3, `trend.adx`): unlike a standalone `atr()` call
    (which seeds its 14-value Wilder average over TR[0:14]), `adx`'s +DM/
    -DM series structurally cannot exist at index 0 (no prior bar), so its
    paired internal TR-for-ADX series is *also* smoothed starting at index
    1 (14 values at indices 1..14) to keep +DI/-DI aligned with +DM/-DM.
    This one-bar shift is what makes the addendum's pinned lookback
    (+DI/-DI first non-None = 14, one bar later than `atr(14)`'s 13) land
    exactly on 2×period-1=27 for the ADX line itself (DX starts at 14, its
    own Wilder seed needs another 14 values). Golden vector
    `tests/golden/indicators/adx.json` covers this seed boundary
    explicitly; hand cross-checks in `test_trend.py::test_adx_golden_vector`
    show the raw +DM/-DM/TR sums.
41. **Supertrend's initial-direction convention is a CTO pin, not a
    derived fact** (story 3, `trend.supertrend`): the addendum explicitly
    defers this to "golden vector + docstring". Pinned here: at the first
    valid index (period-1), direction = +1.0 (uptrend, line=lower band) if
    `close >= basis` (basis = (H+L)/2), else -1.0; a tie resolves to
    uptrend. This has no external canonical source — it is this session's
    choice, documented in `trend.supertrend`'s docstring and exercised by
    `tests/golden/indicators/supertrend.json` (index 9, `direction=-1.0`
    since close9=93.52 < basis9=93.815) and
    `test_trend.py::test_supertrend_initial_direction_pinned_convention`.
    Changing it later is a DESIGN change (breaks the golden vector), not a
    bug fix.
42. **Golden vector provenance (stories 1-3): independent from-spec
    script, not a third-party TA library.** Every value in
    `tests/golden/indicators/*.json` was computed by a standalone
    reference implementation (`gen_golden.py`, run from the session
    scratchpad, never committed to the repo) written directly against the
    formulas pinned in `docs/handoff/SPRINT-P1B-indicators.md` — NOT by
    running `tradekit.mae._indicators` (those are stubs that raise
    `NotImplementedError`) and NOT via `pandas_ta`/`ta` in a throwaway
    venv. This path was chosen over a reference library specifically
    because the addendum's pinned Wilder/EMA seeding convention (SMA of
    the first `period` values) is exactly what `pandas`/`pandas_ta`'s
    `adjust=False` gets wrong (it seeds from the first raw value instead).
    SERIES_A (the shared 45-bar OHLC fixture across `true_range.json`,
    `atr.json`, `bollinger.json`, `keltner.json`, `sma.json`, `ema.json`,
    `rsi.json`, `macd.json`, `stoch_rsi.json`, `roc.json`, `adx.json`,
    `supertrend.json`) is a seeded random walk
    (`random.Random(20260715)`, values rounded to 2 decimals) chosen so
    the hand-arithmetic cross-checks in `test_volatility.py`/
    `test_momentum.py`/`test_trend.py` are exact, pencil-verifiable sums,
    not binary-float noise. Edge vectors (`constant_price.json`,
    `short_series.json`, `single_bar.json`, `true_range_gap.json`) are
    hand-listed or trivially derived (see each JSON's own `"source"`
    field).

    **Cross-checked once, then FROZEN (CTO gate, 2026-07-15):** (a) a
    second from-spec implementation written independently by the CTO
    session reproduced every value in every JSON to rel 1e-9; (b) external
    reference TA-Lib 0.7.0 (throwaway venv, never a project dep) matched
    EXACTLY: sma, ema, rsi, roc, bollinger (all three bands),
    true_range[1:], and the macd line via `EMA(12)-EMA(26)`; (c) known,
    hand-reproduced convention divergences (NOT defects): true_range[0]
    (TA-Lib nan, ours H-L per Wilder), atr (TA-Lib seeds over TR[1..14],
    ours TR[0..13]; verified |diff| decays by exactly 13/14 per bar —
    identical recurrence, seed-only difference), TA-Lib's packaged MACD
    (co-seeds both EMAs at the slow warm-up; converges to ours),
    +DI/-DI/adx (TA-Lib seeds sums over indices 1..13 and applies the
    decay step already at index 14 — its +DI[14]=31.1223 was reproduced
    by hand as 100*(9.70*13/14+0.95)/(32.29*13/14+2.01); ours is Wilder's
    book worksheet: plain average of indices 1..14, recurrence from 15).
    The vectors are frozen; regenerating them requires redoing this gate.

---

## Round-8 additions — P1B stories 4-5 TDD session (red only), 2026-07-15

43. **`vwap` session anchor is the UTC calendar day of `ts_open`, and the
    crack-bar boundary for `qfl_bases` reports `None` on the SAME bar the
    crack happens** (stories 4/5, `volume.vwap` / `structure.qfl_bases`):
    (a) `vwap`'s cumulative sums reset whenever `ts_open.astimezone(UTC).
    date()` changes from the previous bar — this is deliberately a pure
    UTC-calendar-day rule, not an exchange-session-table lookup. It
    happens to also serve US-equity RTH (13:30-21:00 UTC depending on
    DST) because that window never straddles UTC midnight (documented in
    `volume.vwap`'s docstring); a market whose regular session DOES cross
    UTC midnight would need a different anchor, out of scope this sprint.
    Zero cumulative volume so far in the current session (not just a
    single zero-volume bar) is the ONLY case that yields `None` — a
    zero-volume bar with nonzero prior accumulation in the same session
    still produces a value (pinned by
    `test_volume.py::test_vwap_zero_volume_bar_mid_session_does_not_crash`).
    (b) `qfl_bases`'s crack check is evaluated for index i BEFORE
    reporting index i's value: on the bar where `close[i]` first drops
    below the active base's level, `qfl_bases[i]` is ALREADY `None`, not
    the about-to-be-cracked level — there is no one-bar reporting lag on
    the crack side, unlike the k-bar CONFIRMATION lag on the base-
    formation side (a new swing-low pivot at index p cannot be reported
    until index p+k). Pinned by
    `test_structure.py::test_qfl_bases_golden_vector` (hand check 3,
    index 7) and `::test_qfl_bases_later_base_replaces_cracked_one`.
    Golden vectors `tests/golden/indicators/vwap.json` and
    `qfl_bases.json` were computed by an independent, from-spec reference
    implementation (`gen_golden_p1b45.py`, scratchpad, never committed)
    written directly against `docs/handoff/SPRINT-P1B-indicators.md`'s
    addendum — same provenance discipline as assumption 42.

    **Cross-checked once, then FROZEN (CTO gate, 2026-07-15):** a second
    from-spec implementation written independently by the CTO session
    reproduced every value in all five story-4/5 JSONs (vwap, obv,
    volume_ratio, swing_points, qfl_bases) to rel 1e-9; obv additionally
    matched TA-Lib 0.7.0 exactly modulo the documented seed convention
    (ours pins obv[0]=0.0, TA-Lib seeds obv[0]=volume[0] — a constant
    offset of volume[0] thereafter, verified). vwap/swing_points/
    qfl_bases have no third-party reference for these pinned conventions
    (UTC-day anchor, strict-fractal, slate-wipe crack); the dual
    independent implementation is the gate there. Same freeze rule as
    assumption 42.
