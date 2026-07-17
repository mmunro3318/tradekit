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

    **UPDATE (P1C batch A, 2026-07-16) — the sizing-test split, CTO call
    per the SPRINT-P1C addendum:** `size_position` now has a wired stub
    (`mae/__init__.py`, body still `NotImplementedError` pending the dev
    pass) and a matching verb-level test file,
    `tests/unit/mae/test_size_position_verb.py`, which fakes runtime bars
    (monkeypatching `"tradekit.mae._runtime.get_daily_bars"` by dotted
    string path, not a direct import) and exercises the verb's output
    dict, kelly-both-None/-one-None branches, and the three existing
    golden scenarios RE-EXPRESSED through the verb. `tests/unit/mae/
    test_sizing.py` itself is **unchanged, zero tests moved**: every
    existing test there (`test_kelly_golden_vector`,
    `test_negative_kelly_clamps_to_zero`, `test_kelly_rejects_nonsense_
    inputs`, `test_atr_position_golden_vector`, `test_atr_rejects_zero_
    atr`) asserts pure fraction-exact math on `kelly_fractions`/
    `atr_position` directly — none of them are "verb-shaped" (none touch
    bar fetching, ATR-from-OHLCV, or output-dict assembly), so re-pointing
    them through the verb would need network-shaped bar fakes for **no
    behavioral gain** (the addendum's explicit escape hatch: "keep the
    fraction-exact math golden tests where they are"). Consequently
    `tradekit.mae._sizing` is **NOT yet added to the TID251 ban list** —
    `test_sizing.py` still imports it directly, same as before. This
    exception now covers three modules: `thesis._grading`, `mae._sizing`
    (both unchanged), and, new this batch, `mae._correlation` (see entry
    44) — `mae._runtime` and `mae._data.macro` get their own exception
    below (entry 44) since no public verb wires them either.
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

## Round-5 additions — P1C batch A TDD session, 2026-07-16

44. **TEST-PATH EXCEPTION (extends assumptions 23/29/39):**
    `tests/unit/mae/test_runtime.py` imports `tradekit.mae._runtime`
    directly, `tests/unit/mae_data/test_macro.py` imports
    `tradekit.mae._data.macro` directly, and the `compute_correlation`
    golden-vector tests in `tests/unit/mae/test_correlation_verb.py`
    import `tradekit.mae._correlation` directly — none of the three have
    (or, per the addendum, ever will have) a dedicated public verb of
    their own; `_runtime` is a private ambient seam consumed BY verbs,
    `_data.macro` is non-gating supplementary-data plumbing (may be
    re-deferred without blocking the sprint), and `_correlation` is the
    pure-math core wired only through `get_correlation_matrix`. Verb-level
    tests (`test_size_position_verb.py`, `test_correlation_verb.py`'s
    verb-level half) fake runtime bars by monkeypatching
    `"tradekit.mae._runtime.get_daily_bars"` by dotted STRING path —
    string-path `monkeypatch.setattr` is not a Python `import` statement
    and needs no exception; only files that write `from tradekit.mae
    import _runtime` (or `_data.macro` / `_correlation`) need to be listed
    here. When/if a public verb someday re-exports `_runtime` or
    `_data.macro` wholesale (neither is planned), re-point and ban per the
    entry-23/29/39 pattern.

45. **Live-bar-stripping rule (`mae._runtime.get_daily_bars`, SPRINT-P1C
    addendum "the runtime data seam"):** `get_daily_bars` returns CLOSED
    daily bars only — the still-open "live" bar (the one whose close time,
    `ts_open + 86400s`, is strictly after `clock()`'s "now") is stripped
    inside this ONE function, so no verb downstream can ever see it. This
    is the sprint's pinned lookahead trap. Pinned by
    `test_runtime.py::test_get_daily_bars_strips_live_unclosed_bar`: a
    fake provider returns N closed dailies plus one bar whose close time
    exceeds a monkeypatched fixed `_clock()`, and the returned series must
    end exactly at the last closed bar, never including the live one.

46. **Macro never-raise degradation contract (`mae._data.macro.
    get_macro_bars`, SPRINT-P1C story 0, Mike-approved 2026-07-16):**
    supplementary/macro data (yfinance) NEVER raises out of
    `get_macro_bars`, unlike primary OHLCV providers (assumption 27's
    `errors.py` doc: `ProviderUnavailable` etc. are for Kraken/Alpaca
    only). On any fetch failure: return the cached bars already on disk
    for that ticker with `stale=True`, or `BarSeries(bars=[], stale=True,
    source="yfinance")` when nothing is cached yet. `MacroProvider` itself
    (the `MarketDataPort`-shaped class inside macro.py) DOES raise on
    failure, same contract as Kraken/Alpaca — the never-raise wrapper is
    one layer up, in `get_macro_bars`, and is what distinguishes
    supplementary data's degrade-with-visibility rule from primary OHLCV's
    raise-don't-degrade rule. Pinned by three tests in `test_macro.py`:
    happy path (stale=False), fetch failure with a warm cache (stale=True
    + cached bars, no raise), fetch failure with a cold cache (stale=True
    + empty bars, no raise). yfinance does not go through `httpx`, so the
    suite's autouse `respx_mock` zero-network guard does not see it either
    way; the sanctioned zero-network seam is monkeypatching
    `tradekit.mae._data.macro._fetch_rows` directly (addendum: do NOT
    respx-mock Yahoo's internals).

47. **Schema ambiguities flagged, NOT resolved, this batch (canonical §3
    vs. the SPRINT-P1C addendum) — CTO ratification needed before the dev
    pass implements bodies:**
    (a) canonical §3's `size_position` example output has no `warnings`
    key, but the addendum explicitly requires a `negative_kelly` warning
    and a `kelly_inputs_missing` warning to be surfaced somewhere. This
    batch's tests assert a `"warnings"` list key (same shape as
    `compute_strategy_metrics`'s existing `warnings` field) — NOT
    confirmed against canonical §3, which is silent on it.
    (b) canonical §3's `get_correlation_matrix` example output has no
    `insufficient_overlap`-flavored key at all (only
    `high_correlation_warnings`), but the addendum explicitly requires
    "< 20 overlapping points -> pair entry null +
    `insufficient_overlap` in a warnings list". This batch's tests assert
    an `"insufficient_overlap_warnings"` list key (parallel naming to
    `high_correlation_warnings`, each entry a dict with `"pair"` — a
    2-tuple/list of symbols — and an overlap-count field) — this exact
    key name and shape is this session's invention, not derived from any
    pinned source.
    Both are CTO calls to make explicit (not silently improvised into the
    dev pass) per the batch dispatch instruction: "If a canonical §3
    schema detail conflicts with a pinned signature or an addendum rule,
    do NOT improvise — flag it."

    **CTO ratification (2026-07-16): BOTH RATIFIED as the tests pin them.**
    (a) `size_position` output carries a `warnings: list[str]` key —
    canonical §3's example omitting it is an omission, not a prohibition;
    the sprint doc itself mandates a `negative_kelly` warning, and the
    `warnings` list is the house convention (StrategyMetrics). (b)
    `insufficient_overlap_warnings` (entries `{"pair": [a, b], "overlap":
    n}`) is ratified as the canonical-shape EXTENSION for R-013's
    unmeasured-pair rule, parallel to `high_correlation_warnings`. The
    canonical doc's schemas are a floor, not a ceiling: additive keys that
    carry gate-relevant information are permitted; renaming or removing
    canonical keys is not.

## Round-6 additions — P1C batch B TDD session (get_regime), 2026-07-16

48. **TEST-PATH EXCEPTION (extends assumptions 23/29/39/44):**
    `tests/unit/mae/test_regime.py` AND `tests/unit/mae/
    test_get_regime_verb.py` both import `tradekit.mae._regime` directly.
    `_regime` has no dedicated public verb of its own THIS batch —
    `tradekit.mae.get_regime` stays an unconditional `NotImplementedError`
    stub in batch B (red-only; the dev pass wires it to
    `_regime.compute_regime`), so unlike `size_position`/
    `get_correlation_matrix` (already-wired verbs by the time their
    "_verb" test files were written in batch A), there is no way to
    exercise `compute_regime`'s fit/persist/staleness/override/rules-
    fallback logic through `tradekit.mae.get_regime` yet. Both regime test
    files therefore import `_regime` directly and treat `compute_regime`
    itself as the object under test — `test_get_regime_verb.py`'s
    docstring explains this in full. Runtime bars are still faked via
    `monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", ...)` by
    dotted STRING path (no import, no exception needed) and the clock via
    `"tradekit.mae._runtime._clock"`, matching the batch-A house style.
    `_regime` is NOT added to pyproject's TID251 `banned-api` list this
    batch (only `tradekit.mae._metrics` is banned so far) — same
    unbanned-but-exception-documented state as `_correlation`/`_runtime`.

49. **HMM artifact models-dir path seam (`mae._regime._models_dir`,
    SPRINT-P1C batch B, extends assumption 45's `_cache_path` lesson):**
    any module that writes files needs a path seam, and any test that
    triggers `_regime.compute_regime`'s fit/persist path MUST monkeypatch
    `_regime._models_dir` to `tmp_path` — a test that writes into the real
    `data/models/` is a defect, same rationale as batch A's `_runtime.
    _cache_path` catch. Every persistence/staleness/path-validation/EWMA-
    override/rules-fallback/non-convergence/lookahead test in
    `test_get_regime_verb.py` does this.

50. **Pickle-trap path validation (`_regime._artifact_paths`) — the escape
    vector is a WINDOWS backslash, not a forward slash:** `_symbol_slug`
    only replaces `"/"` with `"-"`; a symbol containing `"\\.."` segments
    (e.g. `"..\\..\\secrets"`) is NOT sanitized by that rule alone and,
    left unvalidated, resolves outside `_models_dir` on Windows (this
    sprint's dev/CTO environment — backslash is a real path separator
    there). `_artifact_paths`/`compute_regime` must independently validate
    the RESOLVED path lands inside `_models_dir` (`Path.resolve()`
    containment check) rather than trusting the slug — pinned by
    `test_regime.py::test_artifact_paths_backslash_escape_symbol_raises_value_error`
    and `test_get_regime_verb.py::test_compute_regime_rejects_path_escaping_symbol`,
    both expecting `ValueError`. A forward-slash-only symbol (e.g.
    `"../evil"`) would NOT actually demonstrate the trap, since the slug
    step neutralizes every `"/"` before any path is built — the tests
    deliberately avoid that non-reproducing case.

51. **State-labeling ambiguity, n_states=3, FLAGGED NOT RESOLVED (CTO
    ratification needed before the dev pass treats this as load-bearing):**
    canonical §3's `get_regime` output lists exactly three
    `current_state` strings (`"low_vol_trend" | "high_vol_chop" |
    "breakdown"`) but never states which is the vol-variance MIDDLE state
    when `n_states=3`. This batch's tests pin lowest-variance ->
    `low_vol_trend`, highest-variance -> `breakdown`, middle-variance ->
    `high_vol_chop` (`_regime._N_STATES_3_MIDDLE_LABEL`) — a SESSION CALL,
    not derived from any pinned source, referenced via the module constant
    in tests (never a hardcoded string) so a later ratification needs no
    test-body edits. n_states=2's mapping (lowest -> low_vol_trend,
    highest -> high_vol_chop) IS unambiguous and directly pinned by the
    addendum + canonical §3, and is the ONLY n_states value this batch's
    enumerated test list actually exercises end-to-end via
    `compute_regime` (the n_states=3 constant is exercised only at the
    `_label_states` unit level in `test_regime.py`).

52. **`get_regime` output schema — `method`/`warnings` keys ADDED to
    canonical §3, same shape as assumption 47's precedent:** canonical
    §3's `get_regime` example output has NO `method` or `warnings`/notes
    key at all, but the addendum explicitly requires `method` (`"hmm" |
    "ewma_override" | "rules"`) to distinguish the override/fallback paths
    the reviewer is specifically gating on, plus warnings entries
    (`refit`, `insufficient_history`, `hmm_non_convergence`). This batch's
    tests assert both keys exist and carry the addendum's values — NOT
    confirmed against canonical §3, which is silent on them; flagged for
    the same CTO ratification pass as assumption 47, not silently
    improvised past that flag.

53. **Rules-fallback neutral-bucket name, FLAGGED NOT RESOLVED:** the
    rules grid's third outcome (neither `vol_pctile > 0.8` nor
    `ADX(14) >= 25`) has no canonical §3 name at all — the addendum says
    only "the middle/neutral state." This batch's tests pin the string
    `"neutral"` via `_regime._RULES_NEUTRAL_STATE` (tests reference the
    constant, never the literal), explicitly NOT one of canonical §3's
    three enumerated `current_state` values. CTO ratification needed:
    either add `"neutral"` as a fourth legitimate `current_state` value,
    or pick one of the three canonical strings (most likely
    `low_vol_trend`, as the least alarming default) for this bucket.

    **CTO ratification (2026-07-16) — entries 51/52/53:**
    (51) RATIFIED as the tests pin it: n_states=3 maps lowest-variance ->
    low_vol_trend, middle -> high_vol_chop, highest -> breakdown.
    Rationale: canonical §3 orders its three states from calmest to most
    violent, and "breakdown" is unambiguously the extreme; chop sits
    between trend and breakdown on the vol axis.
    (52) RATIFIED — `method` and `warnings` are additive keys under the
    assumption-47 floor-not-ceiling rule; `method` is load-bearing for the
    Opus review gate on override/fallback wiring, and downstream policy
    rules (R-012/R-013 context) may key on it.
    (53) RATIFIED as `"neutral"`, a FOURTH legitimate `current_state`
    value emitted ONLY by `method="rules"`. Forcing the bucket into
    `low_vol_trend` would let a thin-history symbol masquerade as a
    trending regime and pass a regime gate it never earned — every
    ambiguity resolves AGAINST permissiveness (assumption 25's spirit).
    Consumers (scan_markets regime gate, P2 policy) MUST treat "neutral"
    as no-recommendation: `recommended_strategies=[]`.

54. **EWMA-override baseline = the CALMEST fitted state's emission params
    (CTO adjudication, 2026-07-16, dev-flagged):** the sprint doc's G3
    line ("state_mean_vol + 3*state_vol_std from the fitted state's
    emission params") is ambiguous about WHICH state. Pinned: the
    lowest-vol-variance fitted state, NOT the currently-decoded state.
    Rationale: with short windows the HMM routinely allocates a vol spike
    its own high-variance state — under a current-state baseline the
    override could then never fire during the exact explosions it exists
    to catch (the threshold inflates with the spike). The calmest-state
    band is the stable definition of "normal"; exceeding it by 3 sigma is
    anomalous regardless of how the HMM chose to file the spike. Costs
    are asymmetric (false positive = missed trades; false negative =
    trading into a vol explosion), and every ambiguity resolves AGAINST
    permissiveness (assumption 25's spirit). Pinned by
    test_get_regime_verb.py::test_ewma_override_planted_spike_triggers;
    documented in _regime.py's module docstring. Flag to the Opus review
    gate: this is the load-bearing override-logic call the sprint doc
    routes to Opus.
    Round-4 review update: the ORIGINAL implementation used the pooled
    feature-matrix mean (`feature_means[1]`, mean over ALL bars) for the
    mean term instead of the calmest state's own emission mean — a defect
    caught by Opus review round 4 (HIGH-1) that the planted-spike test
    above could not detect (it clears either threshold); the fix is pinned
    by the new discriminating test
    `test_get_regime_verb.py::test_ewma_override_marginal_spike_discriminates_calm_state_mean_from_pooled_mean`.

## Round-7 additions — P1C batch C TDD session (scan_markets), 2026-07-16

55. **TEST-PATH EXCEPTION (extends assumptions 23/29/39/44/48):**
    `tests/unit/mae/test_scan_markets_verb.py` imports `tradekit.mae._scanner`
    (and `tradekit.mae._regime`, already covered by entry 48) directly.
    `_scanner` has no dedicated public verb of its own THIS batch —
    `tradekit.mae.scan_markets` stays an unconditional `NotImplementedError`
    stub in `mae/__init__.py` (red-only; the dev pass wires the body to
    `return _scanner.scan(asset_class, timeframes, filters, symbols,
    regime_gate)`), same shape as batch B's `get_regime`/`_regime.
    compute_regime` split. Bars are still faked via
    `monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", ...)` by
    dotted STRING path (no import, no exception needed) and regime via
    `monkeypatch.setattr(_regime, "compute_regime", ...)` (module-attribute
    patch, per the CTO pin that the scanner calls `_regime.compute_regime`
    via module attribute specifically so this is possible).

56. **`get_closed_bars` generalization (`mae._runtime`, SPRINT-P1C batch C
    "`_runtime` extension"):** `get_closed_bars(symbol, timeframe,
    lookback_days) -> BarSeries` generalizes `get_daily_bars`'s cache/
    provider/live-bar-strip contract to any timeframe via
    `TIMEFRAME_SECONDS[timeframe]`; `get_daily_bars(symbol, lookback)` is
    PINNED to behave identically to `get_closed_bars(symbol, "1d",
    lookback)`, but this batch (TDD red phase) deliberately leaves
    `get_daily_bars`'s own body untouched — refactoring it into a one-line
    delegate is the dev pass's job. `get_closed_bars` itself is an
    unconditional-raise stub this batch. Consequently:
    `test_get_closed_bars_strips_live_unclosed_bar_1h` (the genuinely NEW
    "1h" behavior) is RED with `NotImplementedError`;
    `test_get_closed_bars_1d_stub_and_get_daily_bars_still_behaves` is
    GREEN — it reasserts `get_daily_bars`'s own unchanged behavior (still
    passing) AND separately pins, via `pytest.raises(NotImplementedError)`,
    that `get_closed_bars(symbol, "1d", ...)` is currently a raising stub —
    both halves pass, so the test as a whole is green, deliberately
    documenting the current seam state rather than being an accidentally-
    green placeholder.

57. **Scanner filter-semantics, output-schema, and regime-drop ambiguities
    FLAGGED NOT RESOLVED this batch (CTO ratification needed before the dev
    pass treats any of these as load-bearing) — pinned provisionally per
    the batch dispatch's "align names with canonical, flag if it
    contradicts; do NOT improvise" instruction:**

    (a) **`macd_signal` value-string contradiction between the sprint doc
    addendum and canonical §3.** The addendum's filter-semantics list says
    `macd_signal ∈ {"bullish", "bearish"}`; canonical §3's OWN input schema
    says `"bullish_cross" | "bearish_cross" | None`. This batch's tests/
    stub docstring pin canonical's value strings (`"bullish_cross"` /
    `"bearish_cross"`, canonical wins per "align names with canonical, flag
    if it contradicts") but PIN THE SIMPLE SEMANTICS the addendum's
    fallback instructs (histogram sign only: `histogram > 0` /
    `histogram < 0`) rather than an actual crossover-event check — canonical's
    own `"_cross"` naming textually implies a real crossing event (macd
    line crossing signal within some lookback), which NEITHER document ever
    defines algorithmically (no "N bars ago" window pinned anywhere). Not
    improvised past this flag.

    (b) **`bb_position: "inside"`** is an ADDITIVE value beyond canonical
    §3's two enumerated strings (`"below_lower" | "above_upper" | None`) —
    flagged as a minor, semantically-unambiguous extension (close strictly
    between the bands), following the floor-not-ceiling precedent
    (assumption 47), not a contradiction requiring ratification of meaning,
    only of whether it's permitted as a THIRD filter value at all.

    (c) **`scan_ts` vs. `as_of`:** the batch dispatch note suggested
    surfacing the scan timestamp as `as_of` (matching
    `get_correlation_matrix`'s own house-additive field name); canonical §3
    `scan_markets`'s OWN example output names this field `scan_ts`. This
    batch's tests pin `scan_ts` (canonical wins over the dispatch note's
    suggestion — not a contradiction within canonical itself, just a
    correction against an informal naming suggestion made before this
    session reread canonical §3 directly).

    (d) **`regime_context` shape for multi-symbol scans.** Canonical §3's
    example output shows a single flat `regime_context: {"state":...,
    "confidence":...}` — but that example scans a single implied symbol;
    it never actually specifies what a MULTI-symbol scan's `regime_context`
    looks like, and `scan_markets` explicitly supports scanning many
    symbols each with (potentially) a different regime. This batch's tests/
    docstring pin `regime_context` as `dict[symbol, {"state", "confidence"}]`
    — a per-symbol keyed dict. This is flagged as riskier than a pure
    additive-keys extension (assumption 47's precedent only covers ADDING
    new top-level keys, not changing an EXISTING key's value type from a
    flat object to a keyed dict), so it needs explicit CTO ratification,
    not silent improvisation.

    (e) **Regime-gate drop scope: tags vs. whole matches.** The addendum
    says regime-incompatible "strategy tags" get dropped, and (ASSUMPTIONS
    53) that a `"neutral"`/empty-`recommended_strategies` state "drops ALL
    strategy-tagged signals for that symbol." This batch pins tag-level
    pruning only: a match whose `signal_tags` end up empty after the gate
    STAYS in `matches` (with `signal_tags: []`), rather than being removed
    from the list entirely — filter AND-composition alone controls list
    membership; the regime gate only prunes tags. No precedent settles
    this either way; flagged for CTO ratification.

    (f) **Signal-tag <-> strategy-family mapping** (`_scanner._TAG_STRATEGY`):
    canonical §3's example only shows three tags (`"oversold"`,
    `"volume_spike"`, `"at_support"`), none of which are strategy-family
    names (`"momentum"`/`"breakout"`/`"mean_reversion"`, from `get_regime`'s
    `recommended_strategies`) — so implementing the regime gate at all
    requires SOME mapping between filter-derived tags and strategy
    families, which neither document supplies. This session's mapping
    (module docstring, `_scanner._TAG_STRATEGY`) is a session choice,
    explicitly NOT CTO-ratified, same disclaimer precedent as
    `_regime._STRATEGY_TAGS`.

    None of (a)-(f) are silently baked into the dev pass without this flag;
    ratify or correct each line before treating it as load-bearing, same
    discipline as assumptions 47/51-54.

    **CTO ratification (2026-07-16) — entry 57's six flags:**
    (a) RATIFIED with canonical value strings "bullish_cross"/
    "bearish_cross" and SIMPLE histogram-sign semantics (bullish: last
    closed histogram > 0; bearish: < 0). True crossing-window semantics is
    a flagged TODO-P5 refinement — the value-string/semantics tension is
    documented in _scanner's docstring, not hidden.
    (b) RATIFIED — "inside" is an additive enum value (floor-not-ceiling,
    assumption 47).
    (c) RATIFIED — canonical's `scan_ts` key name wins over the dispatch
    note's `as_of` suggestion; canonical key names always win where they
    exist.
    (d) RATIFIED — `regime_context` keyed per-symbol for multi-symbol
    scans; canonical's flat example is read as the single-symbol special
    case. Divergence documented (this changes an existing key's value
    type — the reviewer should confirm no canonical consumer assumes the
    flat shape; none exists yet inside tradekit).
    (e) RATIFIED as pinned — a regime-pruned match STAYS in `matches` with
    `signal_tags: []` and per-symbol regime context visible. The scanner
    is ADVISORY; enforcement is P2's policy engine (R-012/R-013), which
    must never treat a scan match as permission. An explicit empty-tags
    match is more honest than a silent absence and carries the "why".
    (f) RATIFIED PROVISIONALLY — `_scanner._TAG_STRATEGY` (and
    `_regime._STRATEGY_TAGS`) are session-invented mappings; they get
    re-derived from the real strategy-tag registry when P2 introduces it
    (revisit marker: SPRINT-P2 thesis strategy_tag work).

## Round-8 additions — P2 batch A TDD session (thesis lifecycle + typed
event payloads + projections), 2026-07-17

58. **Suite-wide `TK_DATA_DIR` isolation (CTO pin, extends the P1C
    cache-poisoning lesson to the ledger):** `tests/conftest.py` gains an
    AUTOUSE fixture (`_tk_data_dir_isolation`) that `monkeypatch.setenv
    ("TK_DATA_DIR", str(tmp_path))` for EVERY test in the suite, not just
    thesis/ledger tests — same rationale and same shape as the existing
    `_no_unmocked_network` autouse fixture. `tradekit.ledger.default_ledger()`
    reads `TK_DATA_DIR` (default `"./data"`, relative to process CWD) at
    call time; without this fixture, any test reaching state through a
    public verb (rather than the `ledger`/`ledger_path` fixtures, which
    take an explicit tmp_path) would silently touch the REAL
    `data/ledger.db` checked into the repo. Pinned by
    `tests/unit/ledger/test_tk_data_dir_isolation.py`: one pure
    `os.environ` probe test (no filesystem I/O, cannot flake — explicitly
    allowed by the batch dispatch) plus one test that opens
    `default_ledger()`, performs a verb-shaped append, and asserts the
    REAL `data/ledger.db` (located via `Path(__file__).resolve().parents
    [3] / "data" / "ledger.db"`, robust to whatever CWD pytest is invoked
    from) is byte-for-byte unchanged.

59. **Additive `contracts`/`thesis` public surface widening (§4.2's "the
    shared-leaf exception whose interface IS its models"):** `contracts`
    gains thirteen new frozen, `extra="forbid"` payload models
    (`_event_payloads.py`) — `ThesisDraftedPayload`,
    `ThesisSubmittedPayload`, `MarketSnapshotTakenPayload`,
    `SizingComputedPayload`, `ThesisApprovedPayload`,
    `ThesisRejectedPayload`, `ThesisActivatedPayload`,
    `ReviewCompletedPayload`, `InvalidationAttestedPayload`,
    `ThesisGradedPayload`, `GateViolationDetectedPayload`,
    `HaltSetPayload`, `HaltClearedPayload` — re-exported from
    `tradekit.contracts.__init__`. `tradekit.thesis` gains
    `IllegalTransition` (`__init__(current_state: str, verb: str)`),
    exported alongside the six verbs. Both widenings are ADDITIVE only
    (assumption 47's floor-not-ceiling precedent extended from contract
    schemas to whole-module public surfaces): no existing model or verb
    signature changed. The P0 envelope itself (`Event.payload: dict`)
    is UNCHANGED — these are producer-side models per ASSUMPTIONS 10's
    ratified pattern (validate through the model, `model_dump(mode=
    "json")` into the dict envelope), pinned end-to-end by
    `tests/unit/contracts/test_event_payloads.py::
    test_producer_round_trip_pattern_thesis_submitted`.

60. **`ThesisDraftedPayload.supersedes` is threaded through an EXTRA key
    in the contract dict, not a `draft()` kwarg or a `ThesisContract`
    field (session design call, not derived from any pinned source):**
    `ThesisContract` has no `supersedes` field (§5.1's field list is
    closed), and `draft(contract: dict) -> str`'s pinned signature takes
    no second argument. This batch's tests
    (`test_lifecycle.py::test_draft_with_supersedes_links_payload_to_
    the_old_thesis`) put `"supersedes": <old_id>` as an EXTRA key in the
    contract dict passed to `draft()` — `ThesisContract` is a plain
    `FrozenModel` (pydantic v2 default `extra="ignore"`, NOT
    `extra="forbid"`), so the model itself silently drops the extra key
    on validation, and `draft()` is expected to read
    `contract.get("supersedes")` before/independent of constructing
    `ThesisContract` and thread it into `ThesisDraftedPayload.supersedes`.
    Flagged: this is a reasonable but non-obvious reading of the CTO
    addendum's one-line mention of supersede-linkage; ratify or correct
    before the dev pass treats it as load-bearing.

61. **`submit()`'s `equity` computation uses a HARDCODED module constant
    this batch, not `PolicyDials`:** the CTO addendum pins `equity =
    paper_starting_equity_usd + cumulative realized pnl ... from
    pnl_daily`, with `paper_starting_equity_usd` a `PolicyDials` default
    of 500 — but `tradekit.policy`/`PolicyDials` don't exist until batch
    C. `tests/unit/thesis/test_submit.py` pins a local
    `_PAPER_STARTING_EQUITY_USD = Decimal("500")` constant and expects
    batch A's `submit()` implementation to use an equivalent hardcoded
    value (later replaced by a real `PolicyDials` read in batch C).
    Flagged, not silently assumed permanent.

62. **`pnl_daily` FillRecorded population is deferred whole-cloth to
    batch B/D (CTO addendum's own explicit escape hatch: "if pnl_daily
    consumption is too batch-D-entangled, pin equity=500 base case
    only and note the deferral"):** this batch ships `pnl_daily`'s DDL
    only (`_projections.py`'s `_TABLES["pnl_daily"]`); `_apply()` has NO
    handling for `FillRecorded` yet, so the table stays permanently
    empty until a later batch wires it. Consequently
    `test_submit.py::test_submit_equity_base_case_uses_paper_starting_
    equity_with_no_fills` is the ONLY equity test this batch — the
    "equity accumulates realized pnl from a harness-appended fill
    history" case named in the batch dispatch is explicitly NOT
    attempted here.

63. **`theses` projection's event-driven state-TRANSITION derivation is
    a `NotImplementedError` stub this batch, same discipline as every
    thesis VERB (batch dispatch: "Failing tests + stubs only") — with
    ONE deliberate carve-out for `ThesisDrafted` itself:**
    `_projections.py`'s DDL for `theses`/`pnl_daily`/`series`/
    `promotion_state` is real (idempotence/empty-rebuild/tables-exist
    tests are GREEN infrastructure). `_apply()` gives `ThesisDrafted` a
    minimal REAL handler (inserts a `state="draft"` row) rather than
    raising, because the pre-existing P0 done-gate replay test
    (`tests/replay/test_p0_replay.py::test_p0_done_gate_replay`) already
    appends a bare `ThesisDrafted` event and calls `ledger.rebuild()` —
    that baseline test must stay green, so a blanket raise on
    `ThesisDrafted` would be a regression, not a red test. Every
    state-transition PAST `draft` (`ThesisSubmitted`, `ReviewCompleted`,
    `ThesisApproved`, `ThesisRejected`, `ThesisActivated`,
    `ThesisGraded`) still raises `NotImplementedError`, so
    `test_rebuild.py::test_theses_projection_materializes_state_from_
    event_sequence` (whose fixture walks draft -> submitted -> reviewed
    -> approved) is deliberately RED at the `ThesisSubmitted` step,
    matching every thesis-verb test's red state this batch.
    `series`/`promotion_state` get no `_apply` handling at all (batch
    D); unhandled event types are silently skipped by `_apply`'s
    existing if/elif chain (same as `LessonRecorded` today), so those
    two tables stay empty and inert with no red test attached.

64. **§10.1 diagram reading, PINNED not flagged — `reject` branches ONLY
    from `reviewed`:** the state-machine diagram
    (`reviewed ─┬─approve→ approved ... └─reject→ rejected`) has no
    `approved ─reject→` edge at all; `reject` on an `approved` thesis is
    therefore an `IllegalTransition`, same as any other out-of-band verb
    call. This reading is unambiguous from the diagram itself (unlike
    assumptions 51-57's genuinely open questions), so it is PINNED
    directly rather than flagged for ratification — pinned by
    `test_lifecycle.py::test_reject_on_approved_raises_illegal_
    transition`.

65. **Submit's event-ordering + validate-before-append pin (CTO
    addendum, restated as a test-suite contract):** `thesis.submit`
    must (a) run EV validation (and any other pre-append validation)
    BEFORE appending anything — a rejected submit leaves the event
    count unchanged, no orphan `MarketSnapshotTaken`/`SizingComputed`
    rows (pinned by `test_submit.py::
    test_submit_ev_validation_rejects_over_tolerance_and_appends_
    nothing`); (b) on success, append in the EXACT order
    `MarketSnapshotTaken` -> `SizingComputed` -> `ThesisSubmitted`, the
    transition marker LAST (pinned by `test_submit.py::
    test_submit_appends_snapshot_sizing_submitted_in_pinned_order`).
    State is defined as "does a `ThesisSubmitted` marker event exist",
    so a crash between steps (a) and the final append leaves the thesis
    correctly in `draft` with harmless orphan prep events — documented
    behavior, not a bug (CTO addendum).

66. **`mypy` strict override extended to `tradekit.thesis.*`
    (`pyproject.toml`):** the existing `[[tool.mypy.overrides]]` block's
    comment already claimed "Strict where money and state live:
    contracts, ledger, policy, thesis" but its `module` list only named
    `tradekit.contracts.*`/`tradekit.ledger.*`. This batch adds
    `tradekit.thesis.*` to that list (matching the batch dispatch's "note:
    thesis/policy are strict-mypy per pyproject" — `tradekit.policy.*`
    does not exist yet, added when the module lands in batch C).

    **CTO ratification (2026-07-17) — batch-A flags:** the `supersedes`
    dict-key threading through draft() is RATIFIED (keeps the pinned
    signature; draft pops the key before ThesisContract validation and
    records it in the ThesisDrafted payload — a kwarg would widen the pin,
    a contract field would misplace lineage into the immutable contract).
    The hardcoded Decimal("500") equity constant is RATIFIED AS TEMPORARY
    — batch C's PolicyDials.paper_starting_equity_usd replaces it, same
    commit as the dials land, and the constant must not survive the
    sprint. Reject-from-approved being illegal is confirmed per §10.1's
    diagram (reject branches from reviewed only). pnl_daily population
    deferral to batch B/D confirmed.

---

## Round-9 additions — P2 batch B TDD session (thesis.grade wiring + the
VOID path), 2026-07-17

**Entry 23 UPDATE — grading-core re-point assessment (sprint doc's own
instruction: "assess which of the 12 test_grading_engine.py tests are
verb-shaped vs fraction-exact-core; the P1C escape hatch applies — likely
ALL stay"):** assessed all twelve tests in
`tests/unit/thesis/test_grading_engine.py`
(`test_target_touch_passes_at_first_trigger_bar` ...
`test_unsorted_bars_rejected`). Every one calls `evaluate_criteria` directly
with hand-built `Bar`/predicate-dict arguments and asserts on the returned
`CriteriaOutcome` alone — none of them touch bar FETCHING, thesis STATE, the
ledger, or the runtime clock/bar seam (`get_closed_bars`/`_clock`). Re-
pointing any of them through `thesis.grade(thesis_id)` would require
building a full draft->submit->...->active lifecycle plus a fake bar seam for
EVERY ONE, for zero additional behavioral coverage — exactly the P1C
escape hatch's condition ("keep the fraction-exact math golden tests where
they are", precedent: entry 23's own `mae._sizing` carve-out). Verdict:
**ALL TWELVE stay as direct `_grading.evaluate_criteria` imports, unchanged,
zero tests moved.** Consequently `tradekit.thesis._grading` is **NOT added
to the TID251 ban list** this batch (`pyproject.toml` untouched) — same
disposition as `mae._sizing`, for the same reason. The NEW verb-shaped
coverage (state gate, event-payload wiring, pnl, the bar seam, quantize-at-
the-verb-boundary) lives entirely in `tests/unit/thesis/test_grade_verb.py`
(13 tests) and `tests/unit/thesis/test_void_verb.py` (9 tests), added this
batch — these do NOT replace or duplicate the core's own fraction-exact
tests; they test the WIRING around it (bar seam calls, pnl, event shape,
state machine).

67. **`grade()`'s return-value convention (FLAGGED, not derivable from the
    CTO addendum, which only pins the return TYPE `dict[str, Any]`):**
    pinned by this batch's tests as "the `ThesisGradedPayload` it just
    appended, `model_dump`'d" — i.e. `thesis.grade(thesis_id)["outcome"]`
    equals the ledgered `ThesisGraded` event's `payload["outcome"]`. Same
    convention as `draft()` returning the id it just minted (the ledgered
    event is always the source of truth; the return value is a convenience
    mirror of it, never a second computation). Pinned by every happy-path
    test in `test_grade_verb.py` (e.g.
    `test_happy_pass_emits_thesis_graded_with_measured_values_and_bar_refs`).

68. **`grade()`'s lookback-window derivation (FLAGGED — CTO addendum says
    "activation->now window" but `mae._runtime.get_closed_bars(symbol,
    timeframe, lookback_days)` has no explicit `start` parameter):** pinned
    as `lookback_days` derived such that `now - timedelta(days=
    lookback_days) == activation_ts` exactly, using DAY-ALIGNED fixture
    timestamps so the derivation is checkable precisely rather than
    approximately (`test_grade_verb.py::
    test_grade_passes_predicate_timeframe_and_activation_window_to_the_seam`).
    The dev pass may need `math.ceil` for non-day-aligned real activation
    timestamps (this batch's tests don't probe that rounding edge — flagged
    as an open gap, not resolved).

69. **pnl fill-ordering convention (FLAGGED — `contracts._execution.Fill`
    carries NO `side`/`direction` field, so "Σ signed fill notionals net of
    fees" needs an entry/exit convention from somewhere else):** pinned as
    "entry = the `FillRecorded` event with the EARLIEST `payload.ts_utc`
    for this `thesis_id`; exit = the LATEST" with the sign taken from the
    thesis contract's OWN `direction` field (`long`: pnl = (exit_price -
    entry_price) * qty - Σfees; `short`: mirrored, UNTESTED this batch —
    only the `long` case has a pinned test,
    `test_pnl_computed_from_fill_events_net_of_fees_long_round_trip`).
    Multi-fill partial-exit scenarios (more than one entry or exit fill)
    are explicitly OUT OF SCOPE this batch. FLAGGED for CTO ratification;
    the clean alternative (adding a `side` field to `Fill`/a typed
    `FillRecordedPayload`) is a `contracts` change, above a test-author's
    remit.

70. **No `FillRecordedPayload` typed contract exists yet — harness fills
    use `contracts._execution.Fill`'s field shape directly as the raw
    `FillRecorded` event payload** (`order_id`, `thesis_id`, `ts_utc`,
    `price`, `qty`, `fees_usd`), since that's the only pinned schema for a
    fill anywhere in the codebase and the P0 envelope's `payload: dict`
    accepts any JSON-native dict (ASSUMPTIONS 10). FLAGGED: a future batch
    may want a dedicated `FillRecordedPayload` in `_event_payloads.py`
    (same additive pattern as ASSUMPTIONS 59) — not attempted here (would
    be a `contracts` src change, out of this test-authoring pass's remit).

71. **pnl-with-no-fills convention — CTO OVERRIDE (2026-07-17): pnl is
    NULLABLE.** This entry's first draft pinned `pnl_usd == Decimal("0")`
    for a zero-fill grade because `ThesisGradedPayload.pnl_usd: Decimal`
    was non-nullable as landed in batch A. The CTO adjudication overrode
    that: a graded thesis with no fills has NO realized pnl, and
    `Decimal("0")` FABRICATES a break-even datapoint that batch D's
    series-expectancy math would silently ingest, diluting expectancy with
    trades that never happened. Resolution (this batch):
    `ThesisGradedPayload.pnl_usd` is now `Decimal | None`
    (`src/tradekit/contracts/_event_payloads.py` — contracts is the one
    fully-implemented module, so the edit is in-scope for a test pass);
    still a REQUIRED field (None must be said explicitly — nullable !=
    optional). Pinned by `tests/unit/contracts/test_event_payloads.py::
    test_thesis_graded_pnl_usd_accepts_none` /
    `test_thesis_graded_pnl_usd_still_required_even_though_nullable` and by
    `tests/unit/thesis/test_grade_verb.py::
    test_pnl_with_no_fills_is_none_never_a_fabricated_zero`.
    **FORWARD-PIN for batch D (binding):** series expectancy must EXCLUDE
    None-pnl theses from the expectancy computation — never coerce None to
    zero. (They still count toward graded/non-void tallies per their
    outcome; only the pnl aggregation skips them.)

72. **`void()`'s typed refusal exception is named `VoidRefused` (additive
    surface — sprint doc's own instruction: "pin a typed exception name,
    e.g. VoidRefused, additive surface noted in ASSUMPTIONS"):** it does
    NOT exist in `tradekit.thesis` yet (void() is still an unconditional
    `NotImplementedError` stub this batch, and adding a new exception class
    is implementation work outside a test-authoring pass's remit — "do not
    modify src" holds for `thesis/__init__.py` too). Tests in
    `test_void_verb.py` therefore do NOT write `pytest.raises(thesis.
    VoidRefused)` directly (that would be an `AttributeError` at collection
    time today, a different failure mode than the sprint's "red via
    NotImplementedError" expectation) — instead a small local helper
    (`_assert_raises_named`) catches broad `Exception` and asserts
    `type(exc.value).__name__ == "VoidRefused"`, which today fails with a
    clean, informative `AssertionError` (`'NotImplementedError' ==
    'VoidRefused'`) and will correctly discriminate once the dev pass adds
    the real class. `IllegalTransition` (already landed, batch A) IS
    referenced directly (`thesis.IllegalTransition`) throughout, no
    indirection needed.

73. **Reviewer-signoff carrier event for `void()`'s second guard — CTO
    OVERRIDE (2026-07-17), and the flag exposed a latent batch-A bug.**
    This entry's first draft swapped the sign-off carrier to
    `LessonRecorded` to dodge a collision: batch A's
    `thesis._machine.derive_state` (`_STATE_BY_EVENT_TYPE`) and the
    `theses` projection (`_projections._THESIS_STATE_BY_EVENT_TYPE`) map
    ANY `ReviewCompleted` event — regardless of payload — to state
    `"reviewed"`, so a void-signoff appended on an ACTIVE thesis would
    clobber its derived state right when `void()` needs to see `active`.
    CTO adjudication: the carrier stays **`ReviewCompleted` with an
    additive `kind` field** (`LessonRecorded` is the memory module's
    event; overloading it muddies the taxonomy) — and the collision the
    first draft dodged is itself **the flagged defect**: the batch-A map
    is UNGUARDED, meaning any out-of-order lifecycle event can corrupt
    derived state. Resolution (this batch):
    (a) `ReviewCompletedPayload` gains `kind: Literal["thesis_review",
    "void_signoff"] = "thesis_review"` — additive + defaulted, so every
    pre-existing payload (no `kind` key) keeps validating; pinned by
    `test_event_payloads.py::test_review_completed_kind_defaults_to_
    thesis_review` / `test_review_completed_kind_accepts_void_signoff_
    and_rejects_junk`.
    (b) `test_void_verb.py`'s sign-off harness (`_append_void_signoff`)
    emits exactly the shape P3's `review.verify_claim` must produce: a
    `ReviewCompleted` event whose payload is
    `ReviewCompletedPayload(kind="void_signoff", thesis_id=...,
    review_artifact_id=..., passed=True)`, validated through the typed
    model; the success-path test asserts that shape explicitly so P3 has
    an exact contract.
    (c) **GUARDED-TRANSITION PIN (binding on the batch-B dev pass):**
    `derive_state` (and the `theses` projection) must apply a
    (state, event) -> state TABLE — a lifecycle event whose FROM-state
    doesn't match the thesis's current state leaves state UNCHANGED
    (projections must be total over any event history, never crash on and
    never be corrupted by out-of-order events); a
    `ReviewCompleted(kind="thesis_review")` only transitions
    `submitted -> reviewed`; a `ReviewCompleted(kind="void_signoff")`
    NEVER causes a state transition from any state (it is a sign-off
    artifact, not a lifecycle edge). Pinned by the deliberately-RED
    `test_lifecycle.py::test_review_completed_events_do_not_clobber_state_
    guarded_transitions`, which exposes the batch-A unguarded map (under
    it, approve() on an active thesis with a stray ReviewCompleted
    wrongly succeeds). `_machine.py` + `_projections.py` are fixed
    together by the batch-B dev pass.
    Consequence: `test_void_verb.py`'s void success-path tests are red
    for two stacked reasons (void() stub + unguarded derive_state); both
    fixes are required to green them.

    **CTO adjudication summary (2026-07-17) — batch-B flags:** entries 67
    (grade() returns the dumped ThesisGradedPayload), 69 and 70 (pnl
    fill-ordering + raw-Fill-shaped FillRecorded payloads — ratified as
    P2-MVP conventions, TODO-P3: typed FillRecordedPayload, short-direction
    and multi-fill handling), and 72 (VoidRefused naming + the
    name-matching test indirection) are RATIFIED as pinned. Entry 68 is
    ratified with one implementation note: the dev pass must round the
    derived lookback UP (ceil) for non-day-aligned activation timestamps so
    the fetched window always COVERS activation, never clips it. Entries 71
    and 73 were OVERRIDDEN — see their rewritten bodies above.
