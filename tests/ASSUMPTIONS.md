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

74. **SPRINT P2 batch C red/green split — `_dials.py`/`_rules.py` land
    REAL, the six `policy` verbs + `_context.assemble` + `_evaluate.
    evaluate_pure` + RULES.md generation + the `tk policy`/`tk promote` CLI
    verbs stay unconditional `NotImplementedError` stubs (CTO's own call in
    the batch-C dispatch message, transcribed verbatim: "_dials.py and
    _rules.py may land REAL this phase ... the six VERBS + _context +
    _evaluate + RULES.md generation + CLI stay stubs -> red"). Consequence
    for `tests/unit/policy/test_rules.py`: because `Rule.check` is pure and
    real, every R-001..R-016 allow/deny pair is GREEN even though nothing
    downstream (`_evaluate`, `policy.evaluate`) can run them together yet —
    same "declarative data the tests read" status batch A gave `contracts`'
    typed payload models. `test_evaluate.py`/`test_halt.py` follow the
    P2-batch-A/B red-phase convention exactly: assertions describe the REAL
    behavior the next dev pass implements, not `pytest.raises(
    NotImplementedError)` wrappers — 13 tests fail today, all with
    `NotImplementedError` as the sole failure mode (verified: `uv run
    pytest` — 522 collected, 13 failed, 0 errors, the 13 named exactly
    `test_evaluate.py`'s 9 + `test_halt.py`'s 4).

75. **`PolicyContext` is NOT built on `contracts.FrozenModel` (FLAGGED, a
    deliberate deviation from `contracts` payload-model house style).**
    `FrozenModel`/`StrictFrozenModel` live in `tradekit.contracts._base`,
    which is TID251-banned outside `contracts` itself (DESIGN §1, the same
    deep-module enforcement that bans `thesis._machine` from being imported
    by `policy`). `PolicyContext` is `policy`'s OWN leaf type — never a
    ledgered payload, never cross-boundary in the `contracts` sense (it is
    assembled fresh per `evaluate()` call and never persisted) — so it is
    built directly on `pydantic.BaseModel` with `ConfigDict(frozen=True,
    arbitrary_types_allowed=True)` (the latter only to let `PolicyDials`, a
    `BaseSettings` rather than a plain `BaseModel`, sit as a field).
    `contracts.ProposedAction`/`Verdict`/`RuleHit` (the actual cross-
    boundary contracts `policy` produces/consumes) ARE imported from the
    public `tradekit.contracts` surface everywhere in `policy/*` and
    `tests/unit/policy/*` — only the private `_base` re-export was avoided.

76. **Insufficient-context vs vacuous-pass split, enumerated per rule (CTO
    addendum's required deliverable for this batch).** "Insufficient
    context" = the rule genuinely NEEDS this field to render an honest
    verdict and P2 has no producer for it yet -> `RuleHit(outcome="fail",
    measured="insufficient_context:<field>")`, NEVER a silent pass.
    "Vacuous pass" = the field's empty/zero value is a TRUE, legitimate
    fact about P2 (no open positions, no fills yet), not a data gap.
    - R-001 (halted): defaults `False` — a fresh, un-halted system genuinely
      has no halt; this is state, not data absence, so no insufficient-
      context path exists for this rule at all.
    - R-002 (account_tier): **insufficient_context** when `None` — a tier
      is never "vacuously T0", it must be assigned.
    - R-003 (settled_balance_usd): **insufficient_context** when `None`.
    - R-004 (allowlist): not applicable (vacuous pass) for non-live
      accounts — the allowlist is a live-only gate by DESIGN §7.2 itself,
      not a P2 data gap.
    - R-005/R-006 (equity/live_exposure_usd): `account_equity_usd`
      **insufficient_context** when `None` (paper path only, must be
      supplied); `live_exposure_usd` defaults to `Decimal("0")` — VACUOUS,
      because P2 ships no broker fill pipeline, so "no live exposure yet"
      is simply true, not missing.
    - R-007 (trades_today_count): **insufficient_context** when `None`.
    - R-008 (min notional): no context field at all — pure arithmetic on
      the action's own order, no split applies.
    - R-009 (drawdown): **insufficient_context** when `None` — CTO
      addendum's own text: "None => insufficient_context (never assumed
      0)"; a drawdown of exactly 0% must be said explicitly.
    - R-010 (thesis prerequisites): **insufficient_context** on any of the
      three `None` fields (review_artifact_id / market_snapshot_id /
      ev_ok) — a thesis missing its review artifact is not "vacuously
      reviewed."
    - R-011 (live sequence budget): **insufficient_context** when `None`
      for a LIVE action (vacuous pass — not applicable — for paper/
      advisory, since the budget only gates T2 live trades); FLAGGED
      consequence: because P2 has no `promotion_state` projection yet
      (batch D), every real live action will see `None` here and be
      denied — this is the anti-permissive default working as intended,
      not a bug, but it means R-011 cannot pass for real live traffic
      until batch D wires `promotion_state`.
    - R-012 (sizing purity): **insufficient_context** when
      `recorded_sizing_usd` is `None` OR `Decimal("0")` (zero-recorded
      would divide-by-zero the deviation ratio — treated as insufficient
      context, not a crash, not a silent pass).
    - R-013 (correlation cap): **vacuous pass** on `{}` — P2 ships no
      broker fill pipeline, so "no open positions" is a true fact, per the
      CTO addendum's own example.
    - R-014 (cooling-off): not applicable (vacuous pass) for non-advisory
      accounts and for notional at/under the dial; **insufficient_context**
      when `thesis_age_hours` is `None` AND the notional/account_ref gate
      says the age check is actually needed.
    - R-015 (VOID-rate audit): **vacuous pass** on an empty
      `trailing_graded_outcomes` tuple — nothing graded yet is a true P2-
      MVP fact (no grading has occurred), same status as R-013.
    - R-016 (promotion metrics): **insufficient_context** when
      `strategy_metrics` is `None` — see entry 77's seam flag below.

77. **R-016's `strategy_metrics` context field is a FLAGGED SEAM, not the
    real `mae.compute_strategy_metrics` wiring (CTO addendum, story-3
    pins, explicit).** `PolicyContext.strategy_metrics` is an untyped
    `dict[str, Any] | None` this batch, read by `_check_r016` for exactly
    one key (`"passes_gates": bool`) — a synthetic stand-in shaped loosely
    like `contracts.StrategyMetrics`'s promotion-relevant subset, chosen so
    R-016 is unit-testable NOW without `policy` importing `mae` at all
    (CTO addendum, story-3 pins: "policy touches NONE" of mae internals).
    **FORWARD-PIN for batch D (binding):** the real wiring calls
    `mae.compute_strategy_metrics(trade_log, n_trials=dials.
    n_trials_default, base_equity_usd=...)` inside `_context.assemble`
    (never inside `_check_r016` itself — `_evaluate`'s pure core must stay
    I/O-free) and must render its `StrategyMetrics` output down to
    whatever shape `_check_r016` ends up needing against the real §9.4
    acceptance table, at which point this entry's `passes_gates`
    boolean-flag stand-in is retired.

78. **`tk grade sweep`'s auto-discovery of every `active` thesis is NOT
    implemented this batch (FLAGGED, a scope-reduction from the sprint
    doc's one-line CLI spec).** The mission doc lists `tk grade sweep|show`
    without further detail; the natural reading ("grade every thesis
    currently in `active` state") needs a way to enumerate theses by
    derived state, which today only exists as `thesis._machine.
    derive_state` — a `thesis`-internal, TID251-banned from `cli` the same
    way it's banned from `policy` (DESIGN §1 deep-module enforcement; the
    `theses` projection that WOULD make this a legitimate public query
    doesn't have a queryable-by-state CLI/verb surface yet either).
    Resolution (this batch): `tk grade sweep` takes a repeatable
    `--thesis <id>` option and grades exactly the ids given — thin dispatch
    over `thesis.grade`, zero new business logic, correct but not
    auto-discovering. **FORWARD-PIN:** a real `sweep` needs either a public
    `thesis` verb/query that lists active thesis_ids, or a CLI-level
    `theses` projection reader — Mike's call which, deferred to whichever
    batch first needs it for real (not blocking for P2's Definition of
    Done, which doesn't require sweep automation).

79. **CLI `_guard_not_implemented` (thin-shell hygiene, `cli/main.py`) is
    REAL code this batch even though everything it wraps (`policy.*`) is a
    stub — FLAGGED because it is the one piece of new `cli/main.py` logic
    beyond pure 1:1 verb dispatch.** Scope: it catches ONLY
    `NotImplementedError` and converts it to `typer.echo(...)` +
    `typer.Exit(code=1)` — no business-logic branching, no silent
    swallowing of any OTHER exception type (a real bug in a future
    `policy.evaluate` still crashes loudly through `CliRunner`, as it
    should). This is why `tests/unit/cli/test_cli_policy.py`'s `policy
    status`/`halt`/`resume`/`promote status` tests are GREEN this batch —
    they pin the CLEAN-failure behavior, not the (still-stubbed) business
    behavior underneath it.

80. **`thesis._submit`'s `PAPER_STARTING_EQUITY_USD` hardcode is RETIRED
    this batch, per the CTO addendum's own instruction ("the ratified-
    temporary constant must not survive the sprint — this batch retires
    it").** `build_submit_payloads` now calls `PolicyDials.load().
    paper_starting_equity_usd` at call time (no caching — same discipline
    as `TK_CONFIG_PATH`/`TK_DATA_DIR`). This makes `thesis` depend on
    `tradekit.policy._dials` (dials only, nothing else from `policy`) —
    FLAGGED as a cross-module dependency the sprint doc's "Traps" section
    doesn't explicitly pre-authorize ("Do not let policy import broker or
    mae internals" says nothing about `thesis` importing FROM `policy`).
    No cycle results (`policy` imports nothing from `thesis`), and the
    direction matches DESIGN §7.3's own precedent ("promotion state...
    is an input to gates" — `policy` is the dial-owning module, `thesis`
    is a dial CONSUMER, same relationship submit's EV/sizing math already
    has to `mae`). Pinned by `tests/unit/thesis/test_submit.py::
    test_submit_equity_follows_a_config_toml_paper_starting_equity_
    override` (the batch's own binding pin: "a tmp config with
    paper_starting_equity_usd=1000 -> equity 1000") and by
    `tests/unit/policy/test_dials.py::
    test_paper_starting_equity_usd_override_via_tk_config_path`.

    **CTO-facing summary for this batch's flags (74-80):** none of these
    are self-adjudicated — 75 (BaseModel instead of FrozenModel), 77 (R-016
    metrics seam), 78 (sweep scope reduction), and 80 (thesis->policy
    dependency direction) are the four that most need an explicit CTO
    ratify/override pass before batch D begins; 74, 76, and 79 are
    descriptive (recording what was built and why), not decisions awaiting
    a call.

    **CTO ratification (2026-07-17) — batch-C flags:** (74/PolicyContext on
    plain pydantic.BaseModel) RATIFIED — TID251's contracts._base ban is
    working as designed; the frozen-model property is what matters, not the
    base class. (R-016 synthetic passes_gates stand-in) RATIFIED, batch D
    wires real compute_strategy_metrics — the stand-in must not survive the
    sprint. (tk grade sweep --thesis explicit ids) RATIFIED AS MVP —
    auto-discovery of active theses lands when a ledger read-accessor
    surface exists (batch E or P3; ledger.models is pinned in §4.2 but
    unimplemented). (thesis._submit -> policy._dials import) RATIFIED as a
    documented cross-module internal exception, same class as
    thesis -> mae._runtime; if policy ever grows a thesis dependency the
    dials extract to a shared leaf (TD-register change, Mike sign-off).

---

## Round-10 additions — P2 batch C dev pass (evaluate/halt to green),
2026-07-17

81. **Fabricated-thesis-id fallback REJECTED; the allow path must be
    EARNED (CTO adjudication, batch-C dev pass).** The dev pass's first
    draft of `_context._thesis_prereqs`/`_recorded_sizing` carried a
    permissive fallback for a `thesis_id` with zero ledger history
    (never drafted/submitted at all): R-010's prerequisite fields got an
    `unverified:<id>` placeholder + `ev_ok=True`, and R-012 fell back to
    the action's OWN order notional (deviation 0, a no-op). Flagged by
    the dev pass; CTO REJECTED it — an action citing a NEVER-DRAFTED
    thesis_id passing thesis-prerequisites and sizing-purity means a
    fabricated thesis_id defeats both gates, exactly the gaming vector
    the policy engine exists to block (ASSUMPTIONS 25's spirit; same
    philosophy as the EWMA-override adjudication, entry 54). The defect
    was the TEST FIXTURE (`test_evaluate.py`'s bare `TH-1` with no
    events), not the anti-permissive semantics. Resolution, all in the
    same dev pass:
    (a) src: fallbacks removed — unknown/never-submitted thesis_id ->
    R-010's fields are `None` -> deny with `insufficient_context`; no
    recorded `SizingComputed` -> `recorded_sizing_usd=None` -> R-012
    denies with `insufficient_context`. Anti-permissive, no exceptions.
    (b) `test_evaluate.py` gained `_seed_thesis_events()`: every
    ledgered evaluate() test now harness-appends the minimal REAL events
    that earn the allow (MarketSnapshotTaken, SizingComputed with
    `recommended_size_usd` matching the order notional within R-012's 1%
    tolerance, ThesisSubmitted carrying `market_snapshot_id` + the EV
    numbers, ReviewCompleted kind="thesis_review") — each event's
    docstring maps it to the R-010/R-012 input it feeds, using the typed
    payload models per the house pattern.
    (c) TWO new deny tests pin the closed hole:
    `test_evaluate_denies_a_fabricated_never_drafted_thesis_id_via_r010`
    (deny + insufficient_context + GateViolationDetected ledgered) and
    `test_evaluate_denies_a_submitted_thesis_with_no_sizing_computed_via_
    r012`.
    Related batch-C dev-pass notes, CTO-accepted in the same
    adjudication: `tests/unit/cli/test_cli_policy.py`'s two `policy
    status`/`halt`/`resume` tests were batch-C-authored stub-era pins of
    `_guard_not_implemented`'s clean-nonzero-exit; now that those verbs
    are real, they assert the real exit-0 success shape instead (their
    obsolescence was planned — the guard itself remains for
    `promote status|confirm`, still stubs until batch D).

---

## Round-11 additions — P2 batch D TDD session (series accounting +
promotion machine), 2026-07-17

Story 4: `policy._series` (new module), `policy.promotion_status()`/
`confirm_promotion()`, and the `series`/`promotion_state`/`pnl_daily`
projections' real semantics. `tests/unit/policy/test_series.py`,
`tests/unit/policy/test_promotion.py` (new), `tests/unit/ledger/
test_rebuild.py` (extended), `tests/unit/contracts/test_event_payloads.py`
(extended), `tests/unit/policy/test_dials.py` (extended). Verified: `uv run
pytest` — 577 collected (524 baseline + 20 new green + 33 new red), all 33
failures are `NotImplementedError` (`policy._series.*` stubs or
`policy.promotion_status`/`confirm_promotion`, unchanged from batch C);
`uv run ruff check .` and `uv run mypy` both clean.

82. **`policy._series.py` is a BRAND-NEW module, entirely unconditional
    `NotImplementedError` stubs this batch — no CTO call landed it "real"
    (unlike `_dials.py`/`_rules.py` in batch C's own red/green split).**
    `series_index`/`window_for`/`series_stats` all raise; every design pin
    (the CTO addendum's story-4 arithmetic: `series_index = floor((grade_ts
    - epoch)/30d)`, expectancy = mean of non-None pnl over graded non-void,
    None-pnl exclusion, intra-series MDD walk convention, complete/clean
    boundary) is encoded VERBATIM in the module's docstrings per the batch
    dispatch's own instruction ("encode in stub docstrings"), so the dev
    pass has a single source of truth to implement against. This mirrors
    `thesis.grade()`/`void()`'s own red-phase treatment (batch B): the
    arithmetic these wrap can be "obviously pure" and still stay stubbed,
    because the dispatch's blanket instruction for the WHOLE batch is
    "Failing tests + minimal stubs," not a per-function judgment call left
    to the test author.

83. **A `SeriesStats` return-shape `dataclass` IS defined in `_series.py`
    (FLAGGED — a test-authoring pass narrowly touching "shape, not logic"),
    even though every function that would populate it is a stub.** Same
    class of exception as `PolicyContext` (batch C, ASSUMPTIONS 75): a
    frozen shape declaration is not "implementation work" in the sense the
    red-phase discipline guards against — it exists so `test_series.py`'s
    assertions (`stats.graded_count`, `stats.expectancy`, ...) have a named
    target to describe, the same way `_context.PolicyContext`'s fields let
    `test_rules.py` construct synthetic contexts against a real shape while
    `assemble()` itself stayed a stub through its own red phase. Never
    ledgered, never cross-boundary — not a `contracts` model (same
    rationale as `PolicyContext`'s own deviation).

84. **`policy._dials.PolicyDials.default_account_ref = "paper:alpha"` is a
    NEW dial, added this batch (FLAGGED, per the batch dispatch's own
    explicit instruction: "if argless, pin default account from dials...
    and FLAG").** `policy.promotion_status()`'s pinned §4.2 signature takes
    NO `account_ref` argument — confirmed by reading `policy/__init__.py`
    directly (not inferred) — so a P2 MVP single-account promotion ladder
    needs a default from somewhere. Added as an ordinary additive dial field
    (same declarative-data character as every other `PolicyDials` field,
    same class of in-scope-for-a-test-pass edit as ASSUMPTIONS 71's
    `contracts` nullable-field change) plus the matching `config.toml` key.
    Multi-account promotion ladders (a real `account_ref` argument, or
    per-account iteration) are explicitly out of scope — P3, Mike's call.

85. **`PromotionGrantedPayload`/`PromotionConfirmedPayload`/`DemotedPayload`
    land as REAL, additive `contracts` payload models this batch (same
    precedent as ASSUMPTIONS 71's `ThesisGradedPayload.pnl_usd` nullability
    fix — "contracts is the one fully-implemented module, so the edit is
    in-scope for a test pass").** `EventType`'s taxonomy already reserved
    `PromotionGranted`/`PromotionConfirmed`/`Demoted`/`SeriesClosed` (§6.3,
    landed at P0) but none had a typed payload model until now; `SeriesClosed`
    is deliberately NOT given one — see entry 86. `DemotedPayload.trigger`
    is a closed `Literal["drawdown_breach", "gate_violation",
    "failed_live_grade"]` mirroring §7.3's three named triggers exactly (R-009
    trip / gate violation / failed live grading) — a new trigger kind is a
    contracts change, not a silent string.

86. **`SeriesClosed` gets NO payload model and NO producer in P2 — flagged
    as a P3-deferred taxonomy row (CTO addendum, story-4 pins, explicit:**
    "series stats are DERIVED at read time... a SeriesClosed event is NOT
    emitted in P2"). Both `policy._series.series_stats` (read-time
    derivation) and the `series` projection's eventual `_apply` population
    must independently re-derive the SAME stats from `ThesisGraded`/
    `GateViolationDetected` history — there is no producer event to key off
    of. `test_rebuild.py::test_series_projection_materializes_a_complete_
    clean_series_row`'s own docstring states this explicitly so the dev pass
    doesn't go looking for a `SeriesClosed` handler that was never meant to
    exist this sprint.

87. **`promotion_status()` is a READ VERB THAT MAY WRITE — FLAGGED for CTO
    ratification, per the addendum's own proposal (not self-adjudicated
    here).** When T1->T2's full conjunction passes AND no unconsumed
    `PromotionGranted` already exists for the account, `promotion_status()`
    appends exactly one `PromotionGranted`; when the account is T2 and a
    demotion trigger has fired since the last `PromotionConfirmed`, it
    ALSO appends `Demoted` — the SAME read verb evaluates both directions.
    The CTO addendum offers this as the intentional alternative to widening
    the six-verb policy surface with a dedicated `evaluate_promotion`/
    `evaluate_demotion` verb; `tests/unit/policy/test_promotion.py`'s
    idempotency test (`test_promotion_granted_is_idempotent_on_repeated_
    eligible_calls`) and the demotion test
    (`test_promotion_status_demotes_a_t2_account_on_gate_violation_since_
    confirmation`) pin this shape but do NOT constitute ratification —
    flagged exactly as instructed, not improvised beyond the given proposal.

88. **`PromotionRefused` does NOT exist in `tradekit.policy` yet (same
    discipline as ASSUMPTIONS 72's `VoidRefused` precedent) — adding a new
    exception class is dev-pass implementation work, not a test-authoring
    concern.** `test_promotion.py`'s two `confirm_promotion` refusal tests
    use the identical `_assert_raises_named` indirection `test_void_verb.py`
    used before `thesis.void`/`VoidRefused` existed for real: catch broad
    `Exception`, assert `type(exc).__name__ == "PromotionRefused"`. Today
    that assertion fails cleanly against `NotImplementedError` (since
    `confirm_promotion()` is unconditionally stubbed), the same red-phase
    shape as every other test in this file. Additive export, name pinned
    verbatim from the CTO addendum's own suggestion ("a typed exception,
    e.g. PromotionRefused").

89. **§9.4 gate mapping for R-016 — FLAGGED, the "simplest honest mapping"
    named in the CTO addendum, not independently derived.** The addendum
    says "use the metrics' own edge_verdict/G1 regime output — pin the
    simplest honest mapping (edge_verdict acceptable set) and FLAG it."
    This batch's tests (`test_t2_ineligible_when_r016_metrics_gate_fails`/
    the ALLOW test) pin `edge_verdict == "positive"` as the ONLY passing
    value — `"marginal"`, `"negative"`, and `"insufficient"` all deny. This
    is a stricter reading than §9.4's own per-metric table (Sharpe/Sortino/
    PF/expectancy/MDD/DSR thresholds individually) — `edge_verdict` already
    folds all of those into one four-way verdict (`_metrics._verdict`), so
    gating on `"positive"` alone is equivalent to requiring EVERY §9.4
    threshold simultaneously, never a partial pass. Flagged for CTO
    ratification: an alternative (accept `"marginal"` too, e.g. for the
    provisional 10<=n<30 regime) is defensible but not what these tests pin.

90. **R-016's real trade-log derivation from ledger `FillRecorded` history
    is NOT attempted this batch (FLAGGED, same class of gap as ASSUMPTIONS
    69/70's fill-ordering/typed-payload deferrals).** The sprint doc's own
    TESTS section offers an escape hatch: "use a REAL tiny trade log for one
    allow case if feasible, else flag." `test_promotion.py`'s ALLOW case
    (`test_t2_eligible_when_three_of_four_clean_and_most_recent_clean`)
    takes a middle path: it monkeypatches the `mae.compute_strategy_metrics`
    SEAM (dotted path `"tradekit.mae.compute_strategy_metrics"`) to return a
    `StrategyMetrics` instance whose numbers are the REAL, independently
    verified output of calling the actual function against a real (tiny,
    40-trade, hand-derivable) `TradeRecord` log — so the arithmetic is real,
    but `promotion_status()` itself is never asked to DERIVE that trade log
    from the ledger's `FillRecorded`/`ThesisGraded` history (there is no
    pinned convention yet for turning graded theses into `TradeRecord`s —
    entry/exit price and size live on `Fill` events, which this batch's
    series histories never construct). Flagged: the dev pass needs its own
    derivation (entry Fill -> exit Fill -> TradeRecord, per thesis) before
    R-016 can run on REAL account history rather than a monkeypatched seam.

91. **The T1->T2 ">=30 non-void graded theses across those 4 series"
    conjunct is ARITHMETICALLY SUBSUMED by "3 of last 4 COMPLETE series
    clean," given completeness's own >=10-per-series floor (FLAGGED,
    discovered during test authoring, not previously noted anywhere in the
    sprint doc or CTO addendum).** Three genuinely complete series each
    need >=10 graded non-void by definition, so their sum is >=30 by
    construction — it is mathematically IMPOSSIBLE to satisfy "3 of 4
    complete clean" while the aggregate falls below 30. `test_promotion.py::
    test_t2_ineligible_when_non_void_total_below_30`'s own docstring
    documents this finding in place of an isolated pass/fail pair (which
    cannot exist) and instead demonstrates the counting arithmetic via a
    construction where the third "supposed to be complete" series is
    deliberately short (9, not 10) — a compound/degenerate case, not a pure
    isolation. Flagged for CTO review: either the two thresholds should be
    decoupled (e.g., a rolling non-void count over a longer window
    independent of series completeness) or the redundancy is accepted as
    intentional defense-in-depth (a redundant conjunct is still correct,
    simply not independently testable) — no unilateral fix applied here.

92. **Demotion-trigger mechanics — CTO adjudication already proposed in the
    batch dispatch, restated here as the binding test pin (not
    self-adjudicated further).** `promotion_status()` machine-evaluates
    demotion the same way it evaluates promotion: if the account is
    currently T2 (its latest `PromotionConfirmed` has no LATER `Demoted`)
    AND a trigger event (R-009 drawdown breach / any `GateViolationDetected`
    / a failed live grading) has occurred SINCE that confirmation, it
    appends `Demoted`. This batch's one policy-side trigger test
    (`test_promotion_status_demotes_a_t2_account_on_gate_violation_since_
    confirmation`, per the batch dispatch's explicit "one policy-side
    trigger test" instruction) exercises the `GateViolationDetected` trigger
    only — R-009 drawdown-breach and failed-live-grading triggers are named
    in `DemotedPayload.trigger`'s `Literal` but have no dedicated test this
    batch (flagged as a coverage gap, not a design gap: the mechanics are
    identical, only the SOURCE event differs).

    **CTO ratification (2026-07-17) — batch-D flags (82-92):** ALL RATIFIED
    as pinned. Specifics: (read-verb-that-writes) promotion_status is the
    machine-evaluation point per §7.3's "All machine-evaluated ->
    PromotionGranted"; a separate verb would widen the six-verb surface —
    the appends are limited to PromotionGranted/Demoted, idempotent
    (unconsumed-grant guard), and fully event-sourced. (R-016 mapping)
    edge_verdict == "positive" ONLY passes — verified against
    mae._metrics._verdict's actual vocabulary {positive, marginal,
    negative, insufficient}; marginal edge does not earn live money, and
    at the >=30-trade promotion floor "positive" is DSR-gated (G1), which
    is precisely §9.4's intent. (>=30-non-void redundancy) confirmed
    arithmetically subsumed by 4x-complete-series; the conjunct stays
    explicitly evaluated anyway — spec fidelity + defense in depth if
    completeness definitions ever change. (grade-time pnl attribution,
    SeriesClosed P3 deferral, default_account_ref dial, PromotionRefused,
    demotion-trigger mechanics via promotion_status) all as proposed.

    **CTO ratification (2026-07-17) — batch-D dev flags (round 12):**
    (last-4 window anchored to the account's most-recent graded series
    index) RATIFIED — converges with wall-clock anchoring because
    completeness requires >=10 grades either way, and T2 always passes
    through Mike's manual confirm_promotion as the staleness backstop;
    batch E's adversarial suite may add an explicit stale-history scenario.
    (TradeRecord numeraire-100 reconstruction) RATIFIED — preserves every
    REAL quantity (pnl_usd, size_usd, side, timestamps) and solves
    exit_price so _metrics._pnl reproduces the ledgered pnl exactly;
    fabricates no market claims; TODO-P3: real fill prices replace the
    reconstruction when the broker pipeline lands. (projection-constant
    duplication) RATIFIED WITH TRIPWIRE — ledger stays stdlib-only by
    design, so test_rebuild.py now pins _projections' constants ==
    PolicyDials defaults (drift fails the suite). (promote-status CLI test
    update) accepted per the ASSUMPTIONS-81 precedent.

---

## Round-13 additions — P2 batch E (adversarial replay done-gate), 2026-07-17

93. **Adversarial replay suite = the sprint done-gate
    (`tests/replay/test_p2_adversarial.py`, Opus-authored, ring 3).** One
    scenario per §15 gaming vector, driven through REAL verbs (draft/submit/
    approve/grade/void/policy.evaluate/halt/resume) with harness appends
    reserved for the P3-owned emissions only (ReviewCompleted /
    ThesisActivated / FillRecorded) and the sanctioned clock/bars seams
    (`tradekit.mae._runtime._clock`/`get_closed_bars`,
    `tradekit.policy._context._clock`). Every scenario PASSES against the
    current implementation — **no gate hole was found; all §15 mitigations
    that P2 owns hold.** Coverage map (§15 row -> test):

    | §15 vector | Gate | Test |
    |---|---|---|
    | VOID abuse | R-015 (>20% trailing void-rate) | `test_void_farm_25pct_voids_blocks_new_submission_via_r015` + boundary control `test_void_farm_boundary_20pct_voids_passes_r015` |
    | Micro-trade series gaming | R-008 ($10 min notional) | `test_micro_series_ten_two_dollar_orders_each_denied_by_r008` |
    | Window cherry-picking | fixed calendar series (arith + no mutating verb) | `test_window_cherry_picking_series_assignment_is_pure_timestamp_arithmetic` |
    | Revenge-sizing after losses | R-012 (sizing purity, 1% tol) | `test_revenge_sizing_2x_denied_by_r012_control_within_tolerance_passes` |
    | Drawdown lockout (F7 advisory) | R-009 (10% 30d peak) | `test_drawdown_breach_locks_out_new_paper_position_via_r009` + `..._advisory_account_too_f7` |
    | Agent bypasses gates in-process | R-001 (kill switch) | `test_kill_switch_halt_denies_every_mutating_action_resume_restores` |
    | Thesis prerequisites (ASSUMPTIONS 81 closed hole) | R-010 | `test_fabricated_never_drafted_thesis_id_denied_by_r010` |
    | VOID sign-off leg (§10.4 leg 2) | void() refusal + audit trail | `test_void_without_reviewer_signoff_refused_attestation_kept_grade_still_works` |
    | Tampered history | hash chain / verify_chain() | `test_tampered_event_row_is_detected_by_verify_chain` |

    **Freeze-gate arithmetic** is inline at every threshold (void-rate 5/20 =
    0.25 > 0.20; drawdown 60/500 = 0.12 >= 0.10; sizing deviation 50/25 = 1.0
    > 0.01; series floor((grade_ts - epoch)/30d) boundary cases). The honest
    control in each scenario asserts the SOLE failing rule id
    (`_failing_rule_ids == {"R-0xx"}`) so a scenario proves the named gate is
    both necessary and sufficient, not merely one denial among many.

    **§15 rows NOT covered in P2 (coverage honesty, not padding) — each is a
    P3 concern with no P2 producer to attack:**
    - **Out-of-band trades (stolen keys / manual UI) -> reconcile + auto-halt
      (§8.2):** `tk account reconcile`, broker fills, and the
      ReconciliationRun(mismatch)->HaltSet path are all `tradekit.broker`
      (P3). P2 ships no fill pipeline, so there is nothing to reconcile
      against — deferred to the P3 broker sprint's own replay scenario.
    - **Prompt injection via fetched market/news text:** structurally
      mitigated (MAE returns numbers/enums, not scraped prose; gates are
      deterministic regardless of wiki content) — nothing executable to
      assert at ring 3 in P2; the guarantee is the absence of a text->policy
      path, which the module boundaries (TID251: policy imports no mae
      internals) already pin.
    - **Rules drift -> policy version hash / generated RULES.md:** covered by
      batch-C unit + RULES.md drift tests, not re-pinned here (not a runtime
      gaming vector an agent exercises through the verb surface).
    - **Key hygiene (.env gitignored, live keys at promotion):** operational/
      deployment posture, no code surface to replay.
    - **Failed-live-grading and R-009-drawdown DEMOTION triggers
      (ASSUMPTIONS 92):** the batch-D `promotion_status()` demotion path only
      has an end-to-end producer for the `GateViolationDetected` trigger in
      P2; the other two triggers share identical mechanics but need the P3
      broker/live-grading producers to exercise — the batch-D coverage gap
      (not a design gap) is unchanged by batch E.

---

## Round-14 additions — P2 post-sprint review fixes, 2026-07-17

94. **HIGH — `equity_entering` was pooled across accounts, not scoped to the
    account whose MDD it bases.** `policy._series.series_stats` and its
    byte-for-byte twin `ledger._projections._materialize_series` both
    computed the MDD walk's starting equity as
    `paper_starting_equity_usd + sum(pnl_usd for every ThesisGraded of ANY
    account_ref strictly before window_start)`, while the in-window MDD walk
    itself is explicitly per-account (§7.3). Dangerous direction: a WINNING
    sibling account's pre-window pnl inflates the pooled base, which shrinks
    `mdd_pct` (same numerator, bigger denominator) and can launder a
    genuinely dirty series into a falsely clean one — clean series feed
    `promotion_status()`'s "3-of-last-4-clean" gate (§7.3/§9.4), so this was
    a real T1->T2 promotion-integrity hole, not a cosmetic drift.

    **Discriminating fixture** (`tests/unit/policy/test_series.py`'s
    `_seed_two_account_pooling_bug_fixture`, equivalent in spirit to the
    reviewer's own probe numbers): account `paper:alpha`'s own in-window
    graded pnls are the pre-existing dirty-MDD freeze fixture (+250, -130,
    +40, then seven 0.00 — graded_count=10, expectancy = 160/10 = 16 > 0).
    Walked against A's OWN entering equity (500, the `paper_starting_
    equity_usd` dial default, no prior A history): 500 -> 750 (peak) -> 620
    -> 660 -> flat; mdd_usd = 750 - 620 = 130; **mdd_pct = 130 / 750 =
    0.17333333333333334 (>= 0.15, DIRTY)**. Sibling account `paper:beta` has
    one graded thesis, pnl +900, timestamped one day BEFORE the window
    starts. Under the bug this pnl pools into A's `equity_entering` (500 +
    900 = 1400); walked against THAT base: 1400 -> 1650 (peak) -> 1520 ->
    1560 -> flat; mdd_usd is still 130 (A's own walk is unchanged), but
    **mdd_pct = 130 / 1650 = 0.0787878787878788 (< 0.15, falsely CLEAN)**.
    expectancy (16) and gate_violations (0) are identical either way, so the
    fixture isolates the pooling bug alone — the ONLY thing that can flip
    `clean` between the two computations is which base the MDD walk starts
    from.

    **Fix (both files, identically):** scope the pre-window pnl sum to the
    account's own graded theses — `policy._series.series_stats` iterates
    `all_graded` (already filtered by `_account_thesis_ids(ledger,
    account_ref)`) instead of an unfiltered `ledger.query(...)`;
    `ledger._projections._materialize_series` iterates
    `per_account[account_ref]` (the same list `in_window` is filtered from)
    instead of the module-wide `graded_events`. New tests:
    `test_series_stats_mdd_base_is_per_account_not_pooled_across_siblings`
    (RED before the fix: asserted `mdd_pct` ~0.17333... and `clean=False`,
    the current buggy code produced `mdd_pct` ~0.07879 and `clean=True`) and
    `test_series_projection_and_series_stats_agree_on_two_account_pooling_fixture`
    (both derivations must independently reach `clean=False` on the same
    fixture — before the fix they "agreed" only by sharing the bug).

95. **MEDIUM — `series.complete` was wall-clock-derived, breaking rebuild
    purity.** `ledger._projections._materialize_series` used
    `datetime.now(UTC)` for the `complete` flag, contradicting `rebuild()`'s
    own interface promise ("output depends on the event log alone") — two
    rebuilds of the identical log, run on two different wall-clock days,
    could disagree. **CTO-pinned fix:** `now_for_completeness` is the MAX
    `ts_utc` across the whole event log (a cached read model can only know
    what the log knows); `complete = window_end <= now_for_completeness`,
    a pure function of the events, so repeat rebuilds of the same log agree
    forever. `policy._series` (seam-clocked via `policy._context.clock()`,
    injectable in tests) remains the actual DECISION authority for
    anti-permissive policy checks — this projection is a read-only CLI/
    report cache, and its log-relative `complete` can legitimately read
    `False` for a window a wall-clock-aware caller would call closed, if the
    log itself has no event past that window's end. Documented in the
    module docstring and pinned by
    `test_series_complete_is_derived_from_the_event_logs_own_max_ts_not_wall_clock`
    (`tests/unit/ledger/test_rebuild.py`): ten `paper:alpha` graded theses
    spanning Jan 1-10 2026 (series 0's `window_end` = Jan 31 2026) with no
    later event anywhere in the log — real wall-clock `now` when the suite
    runs (2026-07-17) is already far past Jan 31 2026, so this test only
    passes under the log-derived rule; a wall-clock-derived `complete` would
    read `True` here and fail it. The pre-existing
    `ledger_with_one_clean_series` fixture (whose own complete/clean
    assertions predate this fix) gets one inert marker event — a bare,
    never-graded `ThesisDrafted` timestamped exactly at series 0's
    `window_end` — so the log itself now has evidence the window closed,
    keeping that test's `complete=1`/`clean=1` assertions meaningful under
    the new rule without weakening them.

96. **LOW-1 — stale "promotion_state unwired — batch D" comments in
    `policy._context.py`.** The comments (on `_account_tier`'s `"live:"`
    branch and `assemble()`'s `live_trades_remaining=None`) read as if
    wiring the live tier were merely undone-yet, when the fail-closed
    behavior is INTENTIONAL: P2 never grants the live tier at all (no P2
    producer ever appends an account into `"live:"`), a P3-deferred-by-
    design scope cut already ratified in ASSUMPTIONS 92 ("the batch-D
    `promotion_status()` demotion path only has an end-to-end producer for
    the `GateViolationDetected` trigger in P2 ... the batch-D coverage gap
    ... is unchanged by batch E"). Comments updated to say so explicitly and
    cite ASSUMPTIONS 92 — no behavior change, no test (per the review
    dispatch's own instruction).

97. **LOW-2 — `ConfigChanged` shape collision in `ledger._projections._apply`.**
    Two producers share the `ConfigChanged` event type with DIFFERENT
    payload shapes (ASSUMPTIONS 10's ratified split): the P0 shape carries a
    `config_version` int; `policy`'s own `ConfigChangedPayload`
    (`previous_hash`/`new_hash`/`dials`) never has that key at all. `_apply`
    unconditionally inserted `payload.get("config_version")` into
    `config_versions`, producing a NULL-junk row for every policy-shaped
    `ConfigChanged` event. **Fix:** guard the insert on `"config_version" in
    payload` — skip the table entirely when the key is absent, insert
    exactly as before when it is present. Pinned by
    `test_config_changed_policy_shaped_payload_inserts_no_config_versions_row`
    (a policy-shaped payload -> zero `config_versions` rows) and its control,
    `test_config_changed_p0_shaped_payload_still_inserts_config_versions_row`
    (a P0-shaped payload -> still inserts), both in
    `tests/unit/ledger/test_rebuild.py`.

---

## Round-15 — Mike's P2 rules sign-off, 2026-07-17

98. **Rules catalog + dials SIGNED OFF by Mike (2026-07-17) with directional
    amendments, recorded as TD-24:** general acceptance of R-001..R-016 and
    the committed config.toml defaults (incl. the 20% void cap he took on
    trust). Amendments: (a) position/exposure dials move to FRACTIONS of
    account principal (R-005 live 5%, R-006 20%, R-014 scaling) — R-008's
    $10 min notional deliberately STAYS absolute (fee-noise floor; CTO
    exception, explained to Mike); (b) accounts get an AccountConfig
    contract (principal_usd Decimal @ 2dp; prop-style slots
    max_lifetime_drawdown / max_daily_drawdown / max_daily_profit /
    consistency_rule, None = disabled — NOT +/-Infinity) with config.toml
    as the defaults layer; (c) create_new_account lands with P3's
    multi-account PaperBroker; (d) Mike expects dial values to change once
    simulations run — the ConfigChanged event trail is the mechanism.
    P2's DoD is now fully closed; the P2-era dollar dials remain the
    default-account values until TD-24's migration lands in P3.

---

## Round-16 — P3 batch A TDD session (BrokerPort + AccountConfig/TD-24
migration), 2026-07-17

99. **`not_configured` RuleHit convention (TD-24):** a rule whose backing
    dial resolves to `None` (disabled — AccountConfig field unset AND
    config.toml default unset) is still CONSULTED, not silently skipped —
    it emits `RuleHit(outcome="not_configured")` so the audit trail proves
    the rule ran. `RuleHit.outcome`'s `Literal` widened from `["pass",
    "fail"]` to `["pass", "fail", "not_configured"]` (additive contract
    change). `_evaluate.evaluate_pure`'s allow/deny roll-up changed from
    `all(hit.outcome == "pass")` to `all(hit.outcome != "fail")` — the old
    predicate would have made every `not_configured` hit deny the whole
    verdict, defeating the point of the convention; this was a genuine bug
    fix, not new production logic, needed for R-017/R-018 to be usable at
    all. R-017 (`max_daily_drawdown`) and R-018 (`max_lifetime_drawdown`)
    are the first two rules to use it; `_rules._not_configured()` is the
    shared constructor.

100. **Conformance-suite skeleton convention (TD-18 ring 2,
    `tests/contract/test_broker_port.py`):** when a Protocol has zero real
    adapters yet, `CASE_BUILDERS` holds exactly one `"placeholder"` entry
    whose factory is never invoked — the `case` fixture `pytest.skip()`s it
    with a reason naming the batch that adds the first real adapter (batch
    B, PaperBroker). Every assertion body in the file is written against the
    Protocol's real return shapes so the later batch's dev pass is a
    ONE-LINE `CASE_BUILDERS` addition, mirroring `test_marketdata_port.py`'s
    "one factory entry" property (TD-18) even before any adapter exists.
    `BrokerTokenRequired` is PINNED here as the exception name batch B's
    `PaperBroker.submit` (and every later adapter) must raise for a missing/
    invalid `VerdictToken` — defined in the test file itself since no
    adapter module exists yet to own it; batch B should re-home it under
    `tradekit.broker` once `_paper.py` lands, at which point the test file
    imports it rather than defining it.

101. **Dial-migration equivalence table (TD-24, R-005 live/R-006/R-014):**
    every renamed dial reproduces the OLD flat-dollar figure exactly at the
    $500 default-account principal — `max_position_usd_live=$25` ->
    `max_position_pct_live=0.05` (0.05 × 500 = 25.00);
    `max_total_live_exposure_usd=$100` -> `max_total_live_exposure_pct=0.20`
    (0.20 × 500 = 100.00); `cooling_off_notional_usd=$200` ->
    `cooling_off_pct=0.40` (0.40 × 500 = 200.00). R-008's `min_notional_usd`
    ($10) is UNCHANGED (stays absolute, CTO exception per Mike's sign-off,
    entry 98). R-005's PAPER leg (`max_position_pct_paper=0.10` ×
    `account_equity_usd`) is untouched by this migration — it was already
    percent-of-equity before TD-24.

    **Test-shape movers (values UNCHANGED, context SHAPE changed — flagged
    per the task's "if any test_rules.py boundary test must change, STOP
    and report" instruction):** R-006's and R-014's pre-existing
    `test_rules.py` allow/deny fixtures now require an explicit
    `account_principal_usd=Decimal("500")` in their synthetic `_ctx(...)`
    call, because the rule itself now needs a principal to compute a
    fraction-based limit where it previously read a flat dial requiring no
    per-account context at all. The boundary VALUES asserted (100.00/100.01
    for R-006; the 200/250 notional vs 200 threshold for R-014) are
    IDENTICAL before and after — only the context construction gained one
    required kwarg. R-005's LIVE leg had NO pre-existing `test_rules.py`
    coverage (only the PAPER leg did), so its new 25.00/25.01 boundary
    tests are pure additions, not migrations.
    `tests/unit/policy/test_evaluate.py`'s `_allow_ctx()` fixture similarly
    gained `account_principal_usd=Decimal("500")` (R-006 applies to EVERY
    `submit_order`, not just live ones — a pre-existing, unchanged property
    of `_check_r006` predating this batch — so the paper-account allow path
    needed it too); its "no failing rule hits" assertion loosened from
    `hit.outcome == "pass"` to `hit.outcome != "fail"` for the same
    `not_configured`-is-not-a-failure reason as entry 99.

102. **`AccountConfig.principal_usd` 2dp rejection is validator-based, not
    quantization:** unlike `contracts.quantize` (which snaps a price onto a
    tick grid), a principal with 3+ fractional digits is a caller ERROR
    (typo'd config file), not a value to silently round — `AccountConfig`'s
    `field_validator` inspects `Decimal.as_tuple().exponent < -2` and raises
    `ValueError` (surfaces as pydantic `ValidationError`).

103. **Lifetime-drawdown-fraction basis flagged ambiguity:** R-018's
    `lifetime_drawdown_fraction` is computed as `(peak_equity -
    current_equity) / principal` — a fraction OF PRINCIPAL, deliberately
    NOT of peak equity (unlike R-009's pre-existing
    `trailing_30d_drawdown_pct`, which divides by peak). The addendum's own
    wording ("lifetime drawdown fraction ... vs principal") reads as
    principal-relative; proposed interpretation, not confirmed by Mike —
    flagged in `policy._context._lifetime_drawdown_fraction`'s docstring
    for review before batch D+ depends on it.

104. **R-017 "daily" == UTC calendar day of realized pnl, no rolling
    window (proposed):** `_daily_pnl_fraction` sums `ThesisGraded.pnl_usd`
    for events whose `graded_ts` (fallback `ts_utc`) falls on `now`'s UTC
    calendar date — the same "UTC calendar day" convention
    `_trades_today_count` (R-007) already uses. A rolling 24h window was
    considered and deferred (per Mike's own P3 addendum note that rolling
    windows are out of scope) — flagged as a proposal, not a sign-off.

105. **`create_paper_account` lives in `tradekit.broker`, not a new
    `tradekit.accounts` module:** TD-24 doesn't name a home for the verb;
    DESIGN §8.3 already frames named paper accounts as "rows in our ledger"
    owned by the broker subsystem, and `tk account create-paper` sits next
    to the existing (already-pinned) `tk account list|balance|positions|
    reconcile` verb family — adding a sixth `tradekit.broker` public
    function stays under the §4.2 depth-test guidance (still far short of
    "~6 verbs" as a hard smell threshold) so a new deep module wasn't
    warranted for one additive verb. Flagged for Mike/CTO ratification —
    the alternative (a dedicated `tradekit.accounts` leaf) is a legitimate
    counter-design if account management grows past this one verb.

    **CTO ratification (2026-07-17) — batch-A/P3 flags (99-105):** the
    evaluate_pure fix is RATIFIED and HARDENED — CTO changed the shape from
    a fail-blocklist to an explicit ALLOWLIST (pass|not_configured) so any
    future outcome value fails closed; insufficient_context verified to
    ride on outcome="fail" (RuleHit Literal is exactly the three values).
    Context-shape movers with unchanged boundary values: accepted.
    Lifetime-drawdown ÷principal basis and R-017 daily = UTC calendar day:
    RATIFIED as proposed (rolling windows deferred per Mike's own note).
    create_paper_account living in tradekit.broker: RATIFIED — accounts
    are broker-domain, the verb is Mike-specified (TD-24 sketch), and
    broker's surface stays at 5 verbs (within the ~6 depth rule). This
    batch deliberately collapsed the TDD/dev split for declarative
    machinery (batch-C precedent); the conformance-suite skips are the
    honest red carried to batch B.

---

## Round-17 additions — P3 batch B TDD session (PaperBroker fill model,
DESIGN §8.3, Opus review focus), 2026-07-17

106. **`FillRecordedPayload` (`tradekit.contracts`, additive, real this
     batch) is a superset of `contracts.Fill`'s field shape PLUS `side`:**
     `order_id`, `thesis_id`, `ts_utc`, `price`, `qty`, `fees_usd`,
     `quote_snapshot` (unchanged from `Fill`) + `side: Literal["buy",
     "sell"]` (the field `Fill` never carried — ASSUMPTIONS 69's own
     flagged gap). Compatibility with P2's harness convention (ASSUMPTIONS
     69/70 — raw dicts shaped like `Fill`, no `side`): CHECKED, not
     silently assumed. `thesis._grade_wiring.compute_pnl` reads
     `FillRecorded` payloads as **plain dicts** via `event.payload.get(...)`
     / `event.payload["..."]` — it never imports or validates through a
     payload model (the ASSUMPTIONS-10 consumer-reads-the-dict split) and
     never touches `side` or `quote_snapshot`. Every field `compute_pnl`
     actually reads (`ts_utc`, `price`, `qty`, `fees_usd`, `thesis_id`) is
     present on every P2-harness-built fixture fill. **Conclusion: no P2
     test changes, no `compute_pnl` migration needed this batch** — `side`
     stays unconsumed by the existing earliest/latest-`ts_utc` entry/exit
     convention. Wiring `side` into pnl attribution (replacing the
     ordering-based convention, closing ASSUMPTIONS 69's flagged gap for
     real) is explicitly deferred to a later batch, not attempted here.

107. **`account_ref` is a FIRST-CLASS required field on
     `FillRecordedPayload` — CTO OVERRIDE (2026-07-17) of this entry's
     first draft.** The first draft flagged that the CTO addendum's
     enumerated field list ("fill price, qty, fees, side, thesis_id,
     order_id, AND the quote snapshot") omits `account_ref`, and pinned an
     extra-dict-key convention (option (a)) as the read path. Adjudication:
     REJECTED — multi-account attribution is TD-7's entire reason to exist,
     and an untyped side-channel key on a typed payload defeats the model.
     Resolution (this batch): `FillRecordedPayload.account_ref: str` is a
     required model field; `tests/unit/broker/test_paper_account_state.py`'s
     `_append_fill` constructs it first-class and persists a pure
     `payload.model_dump(mode="json")` with no merged extras.
     Compatibility re-check after the change (per the adjudication's own
     instruction): `thesis._grade_wiring.compute_pnl` reads raw dicts and
     touches only `thesis_id`/`ts_utc`/`price`/`qty`/`fees_usd` — it never
     reads `account_ref` — and P2's `test_grade_verb.py` harness fills are
     raw dicts that never validate through the model, so an ADDED required
     model field cannot fail them (only producers construct the model).
     Confirmed: nothing else moves; entry 106's no-migration finding is
     unchanged.

108. **`buying_power_usd == settled_cash_usd` (no margin modeled in MVP)** —
     `AccountState`'s three money fields collapse to one value for a cash-
     settled paper account with no open positions carrying unrealized P&L
     into buying power. Pinned by every `test_paper_account_state.py`
     assertion; genuinely unpinned by any DESIGN prose read for this batch
     (§8.1 only says "equity, settled cash, buying power" without a
     formula) — flagged, not derived from a cited source.

109. **A fully round-tripped (net qty == 0) symbol is OMITTED from
     `positions()`, never returned as a zero-qty row** — `BrokerPort.
     positions()`'s own docstring ("Every open position on this account")
     reads qty-0 as "not open." Flagged convention, not literally pinned
     by §8.1/§8.3 prose.

110. **Limit-fill evaluation trigger — FLAGGED, inferred, not literally
     pinned by §8.3's prose:** a resting limit order can only trade through
     on a bar that closes AFTER the order was placed, so `PaperBroker`
     cannot evaluate (and therefore cannot fill) a limit order at `submit()`
     time alone — something must re-check later bars as they close.
     `tests/unit/broker/test_paper_fills.py` pins `order_status(order_id)`
     as that re-check point (mirrors §8.2 step 6: "`tk order status`
     polling -> `FillRecorded`" — the pipeline's own polling verb), which
     means `order_status` has a WRITE side effect (appends `FillRecorded`)
     on a fill-triggering call, unusual for a "status getter" but consistent
     with "no mutable broker state — the ledger is the only state." An
     equally defensible alternative is a dedicated internal poll method
     `execute_order` (batch C) calls directly instead of going through
     `order_status`. The test suite's CONTRACT (submit a resting limit at
     T0 -> later bars appear -> `order_status` reflects `"filled"` with a
     matching `FillRecorded`) is what the dev pass must preserve; the
     MECHANISM (`order_status` itself doing the evaluation vs. a private
     helper `order_status` merely reads the result of) is not pinned,
     flagged for CTO ratification.

     **CTO ratification (2026-07-17): RATIFIED as pinned** — batch C's
     pipeline is the poller (§8.2 step 6); a dedicated sweep verb can come
     later if scheduling needs it.

111. **No-cached-bars behavior — PINNED by CTO adjudication (2026-07-17),
     no longer an open question:** typed exception `NoQuoteAvailable`,
     canonical home `tradekit.broker._port` (alongside
     `BrokerTokenRequired`, same identity-match rationale as entry 112),
     raised by a market `submit()` when `mae._runtime.get_closed_bars`
     returns ZERO bars for the order's symbol, with ZERO events appended
     (no `OrderSubmitted`, no `OrderAck`, no `FillRecorded`) — never a
     guess-fill; a broker that invents prices is the exact fabrication
     class ASSUMPTIONS 71 exists to kill. Pinned by the (red this batch)
     `tests/unit/broker/test_paper_fills.py::
     test_market_submit_with_no_cached_bars_raises_no_quote_available_and_
     appends_nothing`. The limit-order-with-no-bars variant is not
     separately tested this batch (the adjudication specified the market
     case; the same no-fabrication principle applies, coverage gap noted,
     not a design gap).

112. **`BrokerTokenRequired` moved from a test-local class
     (`tests/contract/test_broker_port.py`, batch A skeleton) to its
     canonical home, `tradekit.broker._port.BrokerTokenRequired`** — this
     is a mechanical fix, not a design call: `pytest.raises(SomeClass)`
     matches by class IDENTITY, so a same-named class defined only inside
     the test module could never have caught a real adapter's raised
     exception (the batch-A skeleton predates any real adapter to import
     from, so the gap was latent, not deliberate). The conformance test's
     own assertion body is UNCHANGED — only the import site moved, per the
     batch-A pin's "nothing else in this file changes" intent for the
     CASE_BUILDERS mechanics (the exception-location fix is orthogonal to
     that pin, not a violation of it).

113. **Conformance suite's `CASE_BUILDERS["paper"]` seeds a FRESH
     `account_ref` per call (`f"paper:conformance-suite-{ULID()}"`), not
     the fixed `"paper:conformance-suite"` string the batch-A skeleton's
     placeholder comment suggested** — `pytest.fixture(params=...)` builds
     one `Case` per parametrized TEST FUNCTION (five call sites this file),
     and `broker.create_paper_account` refuses a duplicate `account_ref`
     (`AccountAlreadyExists`, batch A, real) — a fixed string would 409 on
     the second test function's factory call. ULID-suffixing keeps every
     call collision-free without changing `Case`'s "fresh instance per
     test" contract.

    **Batch-B token-gate scope note (not a numbered flag, restating the
    CTO addendum directly):** `PaperBroker.submit`/`.account`/`.positions`/
    `.order_status`/`.fills` and the documented `_verify_token` seam are
    ALL unconditional `NotImplementedError` stubs this batch (TDD red
    phase, "Failing tests + stubs" per the batch dispatch) — including the
    None-token shape check itself. This means `tests/contract/
    test_broker_port.py::test_submit_refuses_without_a_valid_verdict_token
    [paper]` and every other "paper" conformance case fail with
    `NotImplementedError`, not the assertion they encode — the suite is
    UNSKIPPED and running for real (675 collected vs. the prior 5-skip
    baseline; batch A's placeholder marker and skip reason are gone), which
    satisfies "conformance now failing-red for paper, not skipped." No
    fill-model code was written in this session beyond `contracts`
    additions (additive, real per house convention: "contracts are cheap")
    and the `BrokerTokenRequired`/`NoQuoteAvailable` exception classes in
    `_port.py` (mechanical fix, entry 112 / CTO-pinned typed error, entry
    111).

    **CTO adjudication summary (2026-07-17) — batch-B flags (106-113):**
    entries 106 (FillRecordedPayload superset + no-migration finding), 108
    (buying_power == settled_cash — no margin in paper, EVER), 109
    (zero-qty positions omitted), 110 (order_status polling — batch C's
    pipeline is the poller), 112 (BrokerTokenRequired relocation), 113
    (ULID-suffixed conformance seeding) RATIFIED as pinned. Entries 107
    and 111 were ADJUSTED — see their rewritten bodies above (account_ref
    first-class on the typed payload; NoQuoteAvailable pinned in _port.py
    with a red no-fabrication test).

114. **Token verification pulled forward to batch B — REAL ledger lookup,
     not shape-only (CTO adjudication, 2026-07-17, dev pass).** The
     batch-B "shape-only" `_verify_token` plan was the CTO's own
     sequencing call and the conformance suite (deliberately written
     first) proved it wrong: no honest string-shape property separates a
     registered token (`verdict_id="v-1"`, must succeed in
     `test_paper_fills.py`) from an unregistered one
     (`"not-a-real-verdict"`, must fail in `test_broker_port.py`) — both
     are short, hyphenated, non-empty, with identical
     `policy_version_hash`. Resolution: `PaperBroker._verify_token`
     verifies against the LEDGER now — a token is valid iff a
     `VerdictIssued` event exists whose payload `verdict_id` matches,
     `allow` is true, and `policy_version_hash` matches. Missing/None,
     unregistered, hash-mismatched, and registered-but-deny all raise the
     one refusal type (`BrokerTokenRequired`) with the reason in the
     message. **Earned-allow fixture rule** (same class as P2 batch C's
     R-010 "the allow path must be earned" adjudication, commit 7f4c241):
     `test_paper_fills.py` fixtures seed a typed
     `VerdictIssuedPayload(allow=True, verdict_id="v-1", matching hash)`
     onto the tmp ledger before submitting — pre-authorized fixture edit,
     not a frozen-test violation. **Check ordering pinned:** token
     verification FIRST, `NoQuoteAvailable` second — the conformance
     suite's unregistered-token case supplies no bar fixture at all, so
     an invalid token must refuse before any bar fetch (and the
     no-cached-bars test seeds its verdict precisely so it measures the
     quote refusal, not the token one). Batch C may harden further
     (consumption, no-later-deny, thesis linkage) at the same seam.

115. **`FillRecordedPayload.symbol` is REQUIRED, no default (CTO
     adjudication, 2026-07-17, dev pass).** `PaperBroker.positions()`
     derives Position rows per symbol from `FillRecorded` history alone
     (no mutable broker state), so the payload must carry the symbol; the
     dev pass's first draft defaulted it to `"BTC/USD"` to avoid touching
     the frozen `test_paper_account_state.py` harness — REJECTED: a
     defaulted symbol on a money payload is silent fabrication (a producer
     that forgets it would write BTC/USD fills). `_append_fill` now passes
     `symbol` explicitly (pre-authorized fixture edit, same rationale as
     entry 114's). P2 harness fills (raw dicts, no model validation, no
     `account_ref`) are unaffected — `PaperBroker._fill_events` filters on
     `account_ref` before ever reading `symbol`.

## Round-18 — P3 batch C TDD session (execute_order two-phase pipeline,
reconcile->auto-halt, live-tier context wiring), 2026-07-17

RED this session — `broker._pipeline.execute_order`/`reconcile`/
`cancel_order` are unconditional `NotImplementedError` stubs; `policy.
_context`'s live-tier account_tier/live_trades_remaining derivation for
`"live:"` refs still returns the P2 fail-closed carve-out unconditionally
(ASSUMPTIONS 92, now superseded — see entry 119 below). Every test written
this session describes REAL target behavior and fails today for one of
those two reasons, never wrapped in `pytest.raises(NotImplementedError)`
(same discipline as P2 batch C's own red pass, entries 76+).

116. **Token-minting rule (DESIGN §8.2/§15, CTO pin, no improvisation
     needed — the sprint doc already resolved this): `VerdictToken(
     verdict_id=verdict.verdict_id, policy_version_hash=
     verdict.policy_version_hash)`, minted directly off the `Verdict`
     `policy.evaluate()` returns.** No new ULID, no separate token
     registry — `PaperBroker._verify_token` (batch B, real, entry 114)
     already validates exactly this pair against the ledgered
     `VerdictIssued` event. Pinned in `_pipeline.py`'s module docstring,
     step 4; `test_pipeline.py::
     test_execute_order_mints_a_token_that_passes_the_real_verify_token_check`
     exercises it end-to-end with NO monkeypatch of `_verify_token`.

117. **Single-poll MVP (ASSUMPTIONS, this session, per the sprint doc's own
     phrasing): `execute_order` calls `adapter.order_status(order_id)`
     EXACTLY ONCE after `submit()`, never loops/blocks waiting for a later
     fill.** A market order's poll always observes `"filled"` immediately
     (§8.3 synchronous fill); a limit order's poll may observe `"open"` —
     `execute_order` returns that `OrderAck` as-is with no thesis
     activation and no R-011 touch, and `tk order status`/a later
     `broker.get(...).order_status(...)` call is the user-facing re-poll
     surface for a still-resting limit, not a second `execute_order` call.
     Pinned in `_pipeline.py`'s module docstring, step 6.

118. **Thesis activation is a PRIVATE `thesis._machine` seam
     (`_activate_on_fill`), never a public `thesis` verb (DESIGN §4.2's
     own wording: "activation-on-fill (internal, invoked by the broker
     pipeline)").** Added as a stub in `src/tradekit/thesis/_machine.py`
     this session (not exported from `tradekit.thesis.__all__`) —
     `broker._pipeline.execute_order` is the pipeline's own pinned single
     caller. Legal only from `approved` (mirrors every other transition's
     `require_state` guard); appends `ThesisActivated(thesis_id, order_id,
     ts_utc)`, the SAME event type `_machine._SIMPLE_TRANSITIONS` already
     wires `("approved", "ThesisActivated") -> "active"` for.

119. **Live-sequence budget (R-011) is a PURE READ-TIME DERIVATION, never a
     ledgered decrement event (ASSUMPTIONS, this session, per the sprint
     doc's explicit "no new event type" instruction).**
     `live_trades_remaining` = the account's own `PromotionConfirmed.
     live_sequence_remaining` (always 3 at confirmation) MINUS the count of
     `FillRecorded` events for that `account_ref` at/after that
     `PromotionConfirmed`'s own `ts_utc`. Lives in `policy._context.
     assemble()` (SPRINT P3 batch C dev pass), read by R-011 on every
     subsequent `policy.evaluate()` call — `broker._pipeline.execute_order`
     itself does nothing extra on the live path beyond appending the
     `FillRecorded` its adapter already produces (documented at length in
     `_pipeline.py`'s module docstring, step 7, to head off a dev-pass
     temptation to add a decrement event/verb that doesn't exist in the
     taxonomy). A `Demoted` event strictly after the most recent
     `PromotionConfirmed` reverts `account_tier` to (at most) `"T1"` and
     `live_trades_remaining` to `None` (mirrors `policy.__init__.
     _current_tier`'s existing T2-iff-no-later-Demoted logic — the context
     wiring must not reimplement that independently; it should call/mirror
     the SAME derivation `policy._current_tier` already uses, not invent a
     second one that could drift).

120. **ASSUMPTIONS 92 SUPERSEDED — the P2 fail-closed carve-out for
     `"live:"` `account_tier` ends THIS batch, not P4 (DESIGN §7.1's
     addendum, CTO pin, "the P2 fail-closed carve-out ends here").** An
     UNCONFIRMED `"live:"` account_ref keeps the fail-closed `None` (that
     branch is NOT changing — `tests/unit/policy/test_live_tier.py::
     test_account_tier_stays_none_for_an_unconfirmed_live_account_fail_closed`
     pins it as a still-passing regression guard, not a red case, alongside
     the already-real `Demoted`-reverts-tier case). Only a CONFIRMED (and
     not-since-demoted) `"live:"` account_ref newly resolves `"T2"`.

121. **Reconcile match key: exact `(order_id, ts_utc, qty)` triple, no
     fuzzy/tolerance matching (ASSUMPTIONS, this session, sprint doc's own
     phrasing "match on order_id+ts+qty").** A ledger `FillRecorded` with a
     DIFFERENT `order_id` than the broker's own report, even with
     identical `ts_utc`/`qty`, still counts as a mismatch — pinned by
     `test_reconcile.py::
     test_reconcile_does_not_match_fills_across_different_order_ids`.
     `reconcile`'s automatic `HaltSet` is appended DIRECTLY by
     `broker._pipeline.reconcile` (not via a `policy.halt()` call) to avoid
     a `broker` -> `policy` verb-level dependency for a broker-observed
     fact — mirrors the existing rule that `policy.evaluate` never calls
     into `broker`.

122. **`cancel_order` is an ADDITIVE fifth broker verb (MVP), not one of
     §4.2's original four pinned verbs — same "declarative addition, not a
     surface widen" class of call as TD-24's `create_paper_account`
     (ASSUMPTIONS, this session — FLAGGED for CTO ratification, since the
     sprint doc's own broker verb list only names
     get/execute_order/reconcile/record_manual_fill).** Only a RESTING
     order (`order_status(...).status == "open"`) may be canceled; any
     other status raises `broker._pipeline.OrderNotCancelable` (typed,
     zero events appended on refusal) rather than a silent no-op. No new
     `BrokerPort` method — cancellation reads the adapter's existing
     `order_status` and appends `OrderCancelled` itself (pipeline-level
     bookkeeping, not a sixth Protocol method, so §8.1's "five methods"
     depth test in `test_broker_stubs.py` stays unchanged).

123. **`ReconciliationRunPayload`/`OrderCancelledPayload` land as additive
     typed contracts this session** (same "contracts are cheap" status as
     every other declarative addition this sprint) — `contracts.
     ReconciliationRunPayload` carries `account_ref`/`result`
     (`"ok"`/`"mismatch"`)/`broker_fill_count`/`ledger_fill_count`/
     `mismatches` (a list of plain-dict unmatched-fill records, same
     ASSUMPTIONS-10 heterogeneous-payload convention as `quote_snapshot`)/
     `ts_utc`; `contracts.OrderCancelledPayload` carries `order_id`/
     `account_ref`/`ts_utc`/`reason`.

124. **Pipeline entry-price rule for qty derivation (ASSUMPTIONS, this
     session, CTO pin encoded verbatim in `_pipeline.py`'s module
     docstring, step 1): `qty = recommended_size_usd / entry_price`, where
     `entry_price` is the thesis contract's own `entry.limit_price` for a
     LIMIT entry, or the `MarketSnapshotTaken.last_close` recorded at
     `thesis.submit()` time for a MARKET entry — never a fresh quote at
     execute_order time.** This makes the submitted order a mechanical
     transcription of what was already `approved`, not a fresh sizing
     decision at submit time. `test_pipeline.py`'s happy-path tests use a
     MARKET entry (simpler to pin deterministically than the limit-entry
     rule) — the limit-entry qty rule is documented but not exercised by a
     dedicated test this session; FLAGGED as a coverage gap for the dev
     pass or a follow-up batch to close.

    **CTO ratification (2026-07-17) — batch-C/P3 flags (116-124):**
    cancel_order as broker's sixth verb RATIFIED — `tk order cancel` is
    pinned by the sprint doc's own CLI list, and six sits exactly at the
    §4.2 ~6-verb depth line (any seventh verb is a design smell — noted).
    Limit-entry qty derivation coverage gap: NOT accepted as debt — the
    dev pass MUST add one limit-entry pipeline test (additive coverage is
    a permitted dev-side test addition; weakening is not). Live-tier
    Demoted handling reuses policy._current_tier rather than duplicating:
    RATIFIED (the projection-vs-derivation duplication in _projections is
    already tripwired; no third copy). All other round-18 entries ratified
    as pinned.

    **CTO audit + ratification (2026-07-17) — batch-C dev pass edits
    (round 19):** the dev edited tests beyond its authorization; every
    edit was audited individually before this commit. Verdicts: stub/CLI
    planned-obsolescence flips = the documented pattern, assert MORE not
    less — accepted. Fixture-data corrections (ATR=10 so sizing lands at
    5% of equity, clear of the 10%/20% caps: risk 5.00 / stop 20 → 0.25
    units → $25 notional; per-iteration fresh thesis_ids) = data bugs, not
    assertion changes — accepted. OrderAckPayload.thesis_id + the
    thesis_review-kind default fix + implicit live-account config =
    consistent with landed conventions — accepted. **live: →PaperBroker
    routing is EXPLICITLY TEMPORARY**: no venue adapter exists before the
    Alpaca work (P4 story 1); a "live" fill in P3 is a SIMULATED fill and
    must never be reported as venue-executed; P4 MUST replace the routing
    and add a test pinning that live: no longer resolves to PaperBroker
    (duty recorded here + in the P4 seed). PROCESS NOTE: the correct
    sequence was stop-and-flag BEFORE editing; accepted this once because
    every edit survived audit and was prominently self-reported — the
    10-for-10 tests-were-right streak is now 9-for-10 with one
    fixture-data asterisk.

## Round-20 -- P3 batch D TDD session (review module + ManualBroker/
advisory + `tk fill record`), 2026-07-17

RED this session -- `review.run_review`/`review.verify_claim`,
`review._adapters.SubprocessReviewerAdapter.review`, `review._rubric.
score_exchanges`, `review._artifacts.assemble`, and every `ManualBroker`
method (`account`/`positions`/`submit`/`order_status`/`fills`) plus
`broker._manual.record_manual_fill` are unconditional `NotImplementedError`
stubs; every test describes REAL target behavior (same discipline as every
prior red-phase session this sprint, never `pytest.raises(NotImplementedError)`).
`broker.get()` (routing) and `SubprocessReviewerAdapter.__init__`/
`from_dials()` ARE real this batch (declarative construction/routing, same
"cheap" status as `PaperBroker`'s own resolution) -- three tests are
therefore green out of this red-phase file set:
`test_manual.py::test_broker_get_advisory_account_ref_resolves_to_a_real_manual_broker`,
`test_adapters.py::test_from_dials_resolves_binary_args_and_caps_from_policydials`,
`test_cli_fill.py::test_fill_record_on_a_stubbed_verb_exits_cleanly_not_a_traceback`.

125. **"Missing/non-numeric EV block" auto-fail (DESIGN §12.1/F5) is
     UNREACHABLE as literally worded through any real `ThesisContract` --
     `EVBlock`'s four fields are already mandatory `Decimal`s at the
     contracts layer (F5 enforced at construction, not at review time).**
     FLAGGED for CTO ratification, not improvised: this batch's tests
     (`test_run_review.py::
     test_auto_fail_nonpositive_ev_short_circuits_with_zero_adapter_calls`)
     interpret the check as **`ev_block.ev_usd <= 0`** -- a mathematically
     non-positive expectancy is the one EV defect still reachable on a
     valid contract, and it is the substantive thing `run_review` can
     usefully auto-fail on (a `p_win`/`reward_usd`/`risk_usd` combination
     that doesn't justify the trade at all). If Mike intends something
     else (e.g. `ev_usd` disagreeing with the recomputed value already
     checked at `thesis.submit()` time, DESIGN §5.1's `ThesisSubmittedPayload.
     ev_recomputed_usd`), this test's fixture and `run_review`'s docstring
     both need updating together.

126. **Auto-fail short-circuit tests read thesis state via a HARNESS that
     bypasses `thesis.draft`/`submit` (`tests/unit/review/conftest.py::
     _seed_submitted_thesis`), appending `ThesisDrafted`/`ThesisSubmitted`/
     `SizingComputed` directly through their typed payload models.** The
     real `thesis.submit` verb validates EV/sizing tolerance itself and
     would refuse to produce the deliberately-mismatched fixtures these
     tests need (an empty `success_criteria` list, a `size_usd` that
     disagrees with `SizingComputed`) -- same "producer pattern" technique
     `test_void_verb.py::_append_void_signoff` already uses one lifecycle
     stage later. `run_review`'s own real implementation is NOT pinned to
     read the ledger this same way (it may use whatever internal seam the
     dev pass prefers) -- only the OBSERVABLE contract (`ReviewArtifact`
     fields, `ReviewCompleted` event, zero adapter calls) is pinned by
     these tests.

127. **`ReviewArtifact`/`Verification` (SPRINT P3 batch D, additive
     contracts, `contracts/_review.py`) are the dict-shaped return values
     `run_review`/`verify_claim` produce -- distinct from the narrower,
     ledger-facing `ReviewCompletedPayload` (existing since P2).** An
     artifact carries the FULL transcript+scores; the ledgered event is a
     pointer (`review_artifact_id`) + verdict, per DESIGN §12.1's own
     "artifact vs pointer-event" wording. `ReviewCompletedPayload` gained
     an additive+defaulted `failure_mode` field this batch (the
     "ReviewFailed-as-ReviewCompleted" pin, entry 128 below) -- every P2/P3
     pre-existing payload construction keeps validating unchanged.

128. **Pin: a reviewer-subprocess boundary failure (malformed JSON,
     timeout, oversized output) is NEVER a distinct event type and NEVER an
     uncaught crash -- it is `ReviewCompleted(passed=False,
     failure_mode="malformed_output" | "timeout" | "output_too_large")`.**
     An auto-fail short-circuit and a rubric-driven fail (unresolved attack
     >= threshold) are ALSO `passed=False`, but with `failure_mode=None` --
     `failure_mode` answers "did the reviewer PIPELINE itself fail to
     produce a scored verdict", not "did the thesis pass review". Pinned by
     every `test_run_review.py` test's explicit `failure_mode` assertion.

129. **Rubric-threshold arithmetic: `unresolved_attack_count` is a FLAT
     count across ALL rubric categories, compared against
     `PolicyDials.unresolved_attack_threshold` (default 1) by
     `review.run_review`/`verify_claim` -- NOT inside `_rubric.
     score_exchanges` itself, which stays threshold-agnostic (reports the
     raw count only).** A single unresolved severity-5 attack in ANY
     category blocks approval at the default threshold -- there is no
     per-category threshold in P3 (flagged as an open question in
     `prompts/rubric-thesis-v1.md`'s own "Open questions for Mike" section,
     not decided here).

130. **Kraken read-only balance tracking for advisory accounts (DESIGN
     §8.4, sprint doc story 3.5) is EXPLICITLY DEFERRED past P3 -- CTO
     pin, not a dev-pass improvisation.** `ManualBroker`'s `reconcile`
     support (not exercised by any test this batch -- `broker.reconcile`
     itself isn't extended to advisory accounts yet) is stubbed to compare
     RECORDED FILLS ONLY when it lands; wiring the read-only Kraken key is
     P4-adjacent (needs the key rotated, Mike's own precondition per the
     sprint doc). No test in this batch exercises a Kraken balance fetch of
     any kind.

131. **`record_manual_fill`'s R-009/R-014 re-enforcement question is
     FLAGGED, not resolved (`_manual.py`'s own docstring).** DESIGN §8.4
     says advisory accounts get "the SAME R-009 drawdown breaker and R-014
     cooling-off ... the pipeline exists to catch that, so it applies to
     Mike too" -- this batch reads that as enforcement happening at
     thesis submit/approve time via `policy.evaluate`'s existing context
     assembly (same as any other account_ref), with `record_manual_fill`
     itself staying a POST-HOC recording verb with no gate of its own (Mike
     already executed off-platform by the time it's called). No test pins
     a re-check inside `record_manual_fill`; if Mike intends one, that's a
     new red test for the dev pass, not an assumption this batch resolves
     silently.

132. **`prompts/rubric-thesis-v1.md` is a DRAFT, explicitly unratified
     (sprint doc's own deferred-flag).** Five categories
     (`catalyst_falsifiability`/`ev_arithmetic`/`invalidation_distinctness`/
     `sizing_discipline`/`correlation_awareness`), 1-5 severity scale, one
     open exchange JSON schema `review._rubric.score_exchanges` pins in
     code (attack/category/severity/defense/resolved). Mike's edit may
     change category names/count/severity scale -- `RUBRIC_CATEGORIES` in
     `_rubric.py` and this file must move together when he does.

    **CTO ratification (2026-07-17) — batch-D/P3 flags (125-132) + the
    delayed-fuse discovery:** (macro clock fuse) test_macro.py carried
    fixed-date fixtures against the REAL clock — green at authorship, red
    when UTC rolled past the window; fixed with an autouse pinned clock;
    swept the suite — the other dated-fixture files fake the bar seam and
    never touch the real clock. STANDING RULE SHARPENED: fixed-date
    fixtures always pin the clock, and the gate check is "what happens to
    this test in a month," not "is it green now". (ev auto-fail) RATIFIED
    as ev_usd <= 0 — the contract makes missing-EV unconstructible, and a
    non-positive stated EV is the honest auto-fail. (rubric threshold
    placement, kraken-balance deferral, rubric DRAFT status) RATIFIED as
    pinned — rubric prompt goes to Mike at close-out. (record_manual_fill
    gates) RESOLVED: the verb NEVER refuses — the ledger must reflect
    reality, a fill that happened cannot be denied retroactively; instead,
    recording while an R-009 lockout or R-014 cooling-off breach is in
    force appends GateViolationDetected alongside the fill (visibility ->
    series cleanliness -> promotion consequences, F7's actual teeth). The
    dev pass MUST add one additive test pinning exactly that.

## Round-21 -- P3 batch E TDD session (memory + report, 3.7 done-gate,
SeriesClosed emission, ledger.models, strategies registry), 2026-07-17

RED this session -- `memory._brief.render`, `memory._search.search`,
`ledger._models.LedgerModels.{active_theses,account_refs,latest_grades}`,
`policy._series.maybe_close_series`, and all three `report.*` verbs are
unconditional `NotImplementedError` stubs; every test describes REAL target
behavior (never `pytest.raises(NotImplementedError)`). GREEN out of this
red-phase file set (cheap/declarative, same precedent class as
`broker.create_paper_account`/`SubprocessReviewerAdapter.__init__`):
`memory.record_lesson` (contract-validate + one ledger append),
`memory._wiki.add_note` (`tk wiki add`'s file writer), `memory._brief.
estimate_tokens` (pure arithmetic), `Ledger.models` property construction,
`tk grade sweep`'s CLI wiring change itself (the guard around the new
stub), and `tests/replay/test_p3_end_to_end.py`'s entire scan -> thesis ->
review -> approve -> execute_order -> fill -> grade -> REPLAY chain (every
verb it drives landed in earlier P3 batches) -- that file only turns red at
its FINAL two lines (`memory.brief()`/`report.daily_memo()`).

133. **`policy._series.maybe_close_series` is NOT wired into
     `policy.promotion_status()`'s call graph this batch, by deliberate
     choice, not an oversight.** `promotion_status()` is already real and
     green (SPRINT P2 batch D); wiring a brand-new unconditional
     `NotImplementedError` stub into an already-green, heavily-tested
     verb's call graph would turn every pre-existing `test_promotion.py`/
     `test_series.py` scenario that reaches a completed series red too --
     directly violating this batch's own "726 baseline green, new red
     NotImplementedError only" verification bar. `tests/unit/policy/
     test_series_closed.py` calls `maybe_close_series` DIRECTLY instead.
     FLAGGED for the dev pass: wiring the call site into
     `promotion_status()` (and updating whichever pre-existing promotion
     tests that wiring legitimately touches) is real integration work this
     batch does not attempt, per the sprint-doc addendum's own "emitted by
     promotion_status" pin -- not silently deferred, named here.

134. **`tests/unit/test_strategies_registry.py`'s two propagation tests
     (`test_scanner_tag_strategy_is_not_yet_the_shared_registry_object`,
     `test_registry_edit_propagates_to_the_regime_gate`) are RED via
     `AssertionError`, not `NotImplementedError` -- the one deliberate
     deviation from this batch's "new red is NotImplementedError only"
     default, named in both the module docstring and each test's own
     docstring.** `tradekit.strategies` (`TAGS`/`FAMILIES`) is real,
     declarative data seeded verbatim from `mae._scanner._TAG_STRATEGY`'s
     existing (ASSUMPTIONS 57f) mapping -- there is no stub to call. The
     re-derivation itself (`_scanner._TAG_STRATEGY`/`_regime.
     _STRATEGY_TAGS` importing FROM `tradekit.strategies` instead of
     carrying independent copies) is real integration work against two
     already-complete, golden-frozen SPRINT P1C modules, left to the dev
     pass rather than improvised here (rewiring a frozen module's
     module-level constant is not "adding a stub"). Golden-compatibility
     (scanner/regime OUTPUT VALUES unchanged once rewired) is the job of
     the PRE-EXISTING frozen tests in `tests/unit/mae/`, which stayed
     green throughout this session untouched.

135. **`report.daily_memo(thesis_id: str)` takes a single `thesis_id`, not
     a date/account.** DESIGN §12.3 only says `daily_memo` renders "the SME
     §3 practitioner memo" to `docs/reports/`; `docs/research/
     perplexity-SME.md` §3's own canonical template is headed
     `DAILY TRADE MEMO — [Date] — [Asset]` and lists exactly one thesis's
     hypothesis/context/strategy/size/risk/EV/criteria/gate-status fields
     -- read as a PER-THESIS submission-time memo (the "daily" in the name
     names WHEN it's produced, not an aggregation key), not a digest across
     every thesis traded that day. FLAGGED for CTO ratification -- if Mike
     intends a true daily digest (all theses touched on a given UTC date),
     the signature and every `tests/unit/report/test_report.py` fixture
     built against it need to move together.

136. **`ledger.models`/`memory`/`report` all reuse `policy._dials.
     PolicyDials` for their own dials (`brief_max_tokens`, `wiki_dir`)
     rather than inventing a second `BaseSettings` loader.** `PolicyDials`
     is `config.toml`'s one existing loader (`TomlConfigSettingsSource`);
     the alternative -- a dedicated `memory._dials.MemoryDials` -- would
     duplicate the `TK_CONFIG_PATH` resolution logic for two fields. This
     is a cross-module dependency in the OPPOSITE direction from the one
     the CTO addendum forbids ("policy imports NOTHING from broker or
     mae") -- `memory`/`ledger` importing FROM `policy._dials` is a
     read-only data dependency, not `policy` reaching INTO another
     module's internals. FLAGGED as a session choice, not silently assumed
     load-bearing.

137. **`memory`'s own clock seam is `tradekit.memory._clock` (module-
     local, house convention), NEVER `mae._runtime._clock`.** The sprint
     doc's "sanctioned-consumer" note (`mae._runtime.get_closed_bars`) name
     ONLY `thesis` and `broker` as permitted cross-module internal
     consumers of `mae._runtime` -- `memory` reaching into `mae._runtime`
     for a clock would be an undocumented third consumer, so `memory`
     grows its own private `_clock()` function instead (same pattern as
     `policy._context._clock`), monkeypatched by dotted string path
     exactly like every other module's clock seam.

    **CTO ratification pending** -- entries 133-137 flagged this session,
    not yet reviewed.

    **CTO ratification (2026-07-18 UTC) — batch-E flags (133-137):** ALL
    RATIFIED. maybe_close_series: the dev pass WIRES it into
    promotion_status (the machine-evaluation point, consistent with the
    read-verb-that-writes ratification); if any frozen promotion test
    objects on event counts, stop-and-flag — do not leave it unwired.
    Registry rewire assertion-reds: correct shape for a rewire of frozen
    modules. daily_memo per-thesis, PolicyDials reuse, memory's private
    clock seam (mae._runtime stays sanctioned for thesis/broker only):
    as pinned.

## Round-22 -- P3 review fixes (Opus FIX-FIRST verdict: 3 MEDIUM + 1
LOW-deferral), 2026-07-17

Baseline: 774 green at 9c9c12e. Every finding below fixed TDD (red test
proven red against the pre-fix code, then green).

138. **MED-1, halt bypass via resting-limit fill (reviewer probe:
     `PaperBroker.order_status` appended `FillRecorded` with NO halt check
     — a limit resting BEFORE a `HaltSet` could still fill AFTER the halt
     via a later `tk order status` poll).** Fix: `_paper.py` grows a
     private `_is_halted(ledger)` that folds every `HaltSet`/`HaltCleared`
     event in append order into the current halt state (last one wins) —
     the SAME derivation `policy._context._halt_state` uses, DUPLICATED
     here (not imported) so `broker` gains no dependency on `policy`
     (comment in `_is_halted`'s own docstring names the twin explicitly,
     per the CTO pin: "duplication acceptable here"). `order_status` now
     checks `_is_halted` immediately after determining an order is a
     still-open limit and BEFORE evaluating trade-through bars — while
     halted, the order stays `"open"`, zero `FillRecorded`, regardless of
     whether a bar has traded through; a LATER poll after `HaltCleared`
     evaluates normally (ledger determinism is event-based, so replay at
     any later point reproduces the same fill-or-not outcome — noted in
     the method's own docstring). RED proof: two new tests in
     `tests/unit/broker/test_paper_fills.py`
     (`test_order_status_does_not_fill_a_resting_limit_while_halted`,
     `test_order_status_fills_a_resting_limit_after_halt_cleared`) both
     failed against pre-fix code (`AssertionError: assert 'filled' ==
     'open'` and `assert [Fill(...)] == []`), confirming the bypass was
     real; both green after the fix.

139. **MED-2, token gate narrower than the written pin (reviewer probe:
     `_verify_token` only checked existence + allow + hash; the addendum
     pins "existence + thesis match + no newer deny" — a token minted for
     one thesis could authorize an order for a DIFFERENT thesis, and an
     allow superseded by a later deny for the same thesis was still
     accepted).** Fix, both halves, in `_paper.py._verify_token`:
     (a) thesis binding — `_verify_token`'s signature grows a `thesis_id`
     parameter (the submitting order's own `thesis_id`, threaded from
     `submit`'s call site); the matched `VerdictIssued` event's own
     `thesis_id` field (already present on `VerdictIssuedPayload`, no new
     field needed) must equal it, or `BrokerTokenRequired`, fail-closed
     (a `None`-vs-real mismatch refuses same as any other mismatch);
     (b) no-newer-deny — after the thesis-binding check passes, a second
     ledger scan looks for ANY OTHER `VerdictIssued` for the SAME
     `thesis_id` at a STRICTLY LATER `ts_utc` than the matched allow with
     `allow is False` -> `BrokerTokenRequired`; a later ALLOW does not
     invalidate the presented token, only a later DENY does. RED proof:
     three new tests
     (`test_submit_refuses_a_token_minted_for_a_different_thesis`,
     `test_submit_refuses_an_allow_token_superseded_by_a_later_deny_for_the_same_thesis`,
     plus the positive control
     `test_submit_accepts_an_allow_token_when_a_later_verdict_is_also_an_allow`)
     — the two refusal tests failed with `Failed: DID NOT RAISE
     BrokerTokenRequired` against pre-fix code; the positive control
     passed both before and after (by design, as the control). SIDE
     EFFECT: `_verify_token`'s new signature (`verdict, thesis_id`)
     required every existing test fixture seeding a `VerdictIssued` with
     `thesis_id=None` to instead seed the REAL thesis_id the order under
     test carries — `tests/unit/broker/test_paper_fills.py`'s
     `_seed_allow_verdict` and `tests/unit/broker/test_pipeline.py`'s
     `_seed_allow_verdict` both grow an explicit `thesis_id` kwarg, and
     every call site now passes the order's own `thesis_id` (previously
     `None` worked only because the old check never looked at it — no
     assertion was weakened, the fixtures became honest about what they
     were already implicitly claiming).

140. **MED-3, reconcile one-directional (reviewer probe:
     `_pipeline.reconcile` only checked "every broker fill has a matching
     ledger row" — a `FillRecorded` sitting on the ledger with NO matching
     broker fill, a "phantom ledger fill", was invisible to reconcile).**
     Fix: `reconcile` now also builds the ledger's own fill keys
     (`(order_id, ts_utc, qty)`, same exact-triple match, no new key
     scheme) and, for each ledger `FillRecorded` with a key absent from
     the broker's reported set, appends a mismatch entry tagged
     `"kind": "phantom_ledger_fill"` and folds its `order_id` into the
     `HaltSet` reason string (which now names `phantom_ledger_fill`
     explicitly when that branch fires, alongside the pre-existing
     "unmatched broker fill(s)" wording when both directions disagree
     simultaneously). A real `PaperBroker` structurally cannot exercise
     this branch (`PaperBroker.fills()` derives FROM the same ledger
     `reconcile` reads, so it can never disagree with itself) — RED proof
     uses the SAME `_FakeBrokerPort` pattern `test_reconcile.py` already
     established (mocks mirror real shapes — `contracts.Fill` instances),
     reporting a SUBSET of what the ledger has. New test
     `test_reconcile_detects_a_phantom_ledger_fill_the_broker_never_reported`
     failed with `AssertionError: assert 'ok' == 'mismatch'` against
     pre-fix code (the phantom fill was silently invisible); green after
     the fix. Positive control
     `test_reconcile_ok_when_ledger_and_broker_fill_sets_are_identical`
     (two fills each side, identical triples) passed both before and
     after, confirming the new reverse check does not false-positive on a
     clean two-sided match.

141. **LOW-1, subprocess cap is post-buffering — NO code change, deferred
     to P4.** Reviewer probe: wherever this sprint shells out to a
     subprocess with an output cap, the cap is enforced by reading the
     FULL stdout/stderr into memory and truncating afterward (post hoc),
     not by bounding the read as it streams — a misbehaving or malicious
     subprocess that emits gigabytes before the process exits (or never
     exits) is bounded only by the SAME timeout that already governs the
     call, not by the output cap itself, and peak memory during the read
     is unbounded by that cap. Assessed and INTENTIONALLY DEFERRED, not
     silently ignored: at MVP scope every subprocess call site invokes a
     TRUSTED, house-controlled CLI (no third-party/user-supplied
     executables reachable through this path this sprint) and every call
     is already timeout-bounded, so the failure mode this would guard
     against (an adversarial or runaway subprocess exhausting memory
     before the cap can apply) is not currently reachable. Streaming caps
     (bound the read itself, not just the post hoc truncation) are real
     work — a chunked-read loop with an early-abort once the cap is
     exceeded, plus a test harness that can actually produce a
     multi-gigabyte or hanging subprocess — properly scoped to P4 when/if
     a less-trusted subprocess consumer is added, not squeezed into this
     review-fix pass.

    **CTO ratification pending** -- entries 138-141 flagged this session
    (P3 review fix pass), not yet reviewed.

    **CTO ratification (2026-07-18 UTC) — round-22 (138-141): ALL
    RATIFIED as implemented.** The halt-gate on resting fills preserves
    ledger determinism (fills are recorded events; replay reproduces the
    log, not the poll timing). Token thesis-binding fails closed on
    legacy None. Phantom-ledger-fill reconcile direction closes the §15
    asymmetry ahead of P4. Streaming subprocess caps deferred to P4.

142. **Round-23 (SPRINT P4-PAPER batch A, addendum 2) — routing table,
     fail-closed conjunction, fees-from-costs provisional convention,
     shared-verifier extraction + halt addition, fixture provenance.**
     TDD red-phase session; every item below is either declarative/real
     this batch (routing, dials, the shared verifier + its halt addition)
     or a PIN for the batch-B dev pass (AlpacaBroker's method bodies).

     - **Routing table** (`broker/__init__.py.get()`, real this batch):
       `"paper:*"` -> `PaperBroker`; `"alpaca-paper:*"` -> `AlpacaBroker`
       bound to `ALPACA_PAPER_BASE_URL` + `ALPACA_API_KEY_ID`/
       `ALPACA_API_SECRET` (the SAME env names `mae._data.alpaca_data`
       already uses — one Alpaca paper credential pair for both
       market-data and trading this sprint); `"live:*"` -> the fail-closed
       gate (below); `"advisory:*"` -> `ManualBroker` (unchanged).
     - **Fail-closed conjunction** (`LiveTradingDisabled`, `broker._port`):
       `"live:"` resolves to a real `AlpacaBroker` (live base URL +
       `ALPACA_LIVE_KEY_ID`/`ALPACA_LIVE_SECRET`) iff BOTH
       `PolicyDials.live_trading_enabled` is `True` (new dial, default
       `False` in `config.toml` and the `PolicyDials` code default) AND
       both live env keys are present — EITHER alone is insufficient,
       matching the addendum's own "requires dial `live_trading_enabled`
       ... AND env ALPACA_LIVE_KEY_ID/SECRET" wording literally as an AND,
       not an OR of independent guards. This REPLACES SPRINT P3 batch C's
       temporary `"live:"` -> `PaperBroker` routing (round-18) — the
       round-19 pin (`"live:"` never resolves to `PaperBroker` again) is
       re-pointed onto this batch's real gate in
       `tests/unit/broker/test_broker_stubs.py::
       test_get_never_resolves_a_live_prefixed_account_ref_to_a_paper_broker`,
       replacing that file's own SPRINT P3 batch C test of the same
       family (`test_get_resolves_a_live_prefixed_account_ref_to_a_paper_
       broker`, now deleted — its own docstring said as much would happen).
     - **Fees-from-costs provisional convention** (worked arithmetic,
       `_alpaca.py`'s module docstring + `test_alpaca_broker.py::
       test_fees_from_costs_arithmetic_for_the_captured_10_dollar_order`):
       the CTO's captured `activities` fixture
       (`docs/research/alpaca-paper-shapes-2026-07-18.json`) confirms
       Alpaca's paper crypto FILL activity carries NO fee/commission field
       at all — not an omission in our fixture, the REAL response has none.
       `FillRecordedPayload.fees_usd` at fill-recording time (batch B pin)
       therefore comes from `tradekit.costs.price_friction("alpaca",
       "crypto", notional_usd, side).fee_usd` — `_TABLE[("alpaca",
       "crypto")]` = (fee_rate=Decimal("0.0025"),
       half_spread_rate=Decimal("0.0010")), so at the captured $10
       notional: `fee_usd = Decimal("0.0025") * Decimal("10") =
       Decimal("0.025")`. PROVISIONAL (ASSUMPTIONS-26 spirit — a modeled
       estimate standing in for a real per-fill number Alpaca's paper API
       simply does not report), not to be treated as ground truth once
       live fills exist to measure against.
     - **Shared-verifier extraction + halt addition**
       (`src/tradekit/broker/_tokens.py`, new module): `PaperBroker.
       _verify_token`'s existence/allow/hash + thesis-binding (MED-2a) +
       no-newer-deny (MED-2b) algorithm moved VERBATIM into
       `_tokens.verify_token(ledger, verdict, thesis_id, caller_repr=...)`
       — `_paper.py` now delegates to it (mechanical extraction, zero
       PaperBroker test changes needed), and `AlpacaBroker`'s batch-B
       `submit()` will run through the SAME function object, never a
       second copy. PLUS the deliberate new behavior this batch adds:
       `verify_token` refuses (`BrokerTokenRequired`, message contains
       "halted") when `_tokens.is_halted(ledger)` finds an unresolved
       `HaltSet` — checked FIRST, before even the missing-token check.
       This is a genuine BEHAVIOR CHANGE for `PaperBroker` (before this
       batch, `submit()` never checked halt state at all; only
       `order_status`'s resting-limit poll did, MED-1) — the ONE
       deliberately red-then-green case this batch:
       `tests/unit/broker/test_alpaca_broker.py::
       test_submit_refuses_with_reason_halted_when_an_unresolved_halt_set_exists[paper]`
       is GREEN this batch (real code, not a stub) precisely because the
       extraction ships working code; the `[alpaca-paper]` parametrize
       case stays RED (stub). No existing `test_paper_fills.py` test seeds
       a `HaltSet` before calling `submit()`, so this addition changes
       ZERO existing green tests (audited by grep before writing the
       extraction).
     - **Fixture provenance**: every JSON shape embedded in
       `tests/unit/broker/test_alpaca_broker.py` (`ORDER_SUBMIT_FIXTURE`,
       `ORDER_GET_FILLED_FIXTURE`, `ACTIVITIES_FIXTURE`) is copied verbatim
       (field names/types unchanged, a few obviously-null optional keys
       trimmed for length — `legs`/`hwm`/`subtag`/`source`/`trail_*`/
       `replaced_*`/`replaces`/`position_intent`/`extended_hours` etc. —
       never a value that participates in any test assertion) from
       `docs/research/alpaca-paper-shapes-2026-07-18.json`, the CTO's own
       2026-07-18 UTC probe (a real $10 BTC/USD Alpaca PAPER order's full
       lifecycle). The P1A lesson stands as law (a fixture diverging from
       captured reality is a HIGH defect) — no field was invented or
       reshaped to make a test easier to write.

     **Flagged ambiguities (NOT improvised, left for the batch-B dev pass
     or CTO adjudication):**
     - `AlpacaBroker.positions()`'s real source is genuinely undecided —
       `GET {base}/positions` (Alpaca's own venue truth) vs. deriving from
       this account's own `FillRecorded` ledger history (the
       `PaperBroker`/`ManualBroker` convention). `_alpaca.py`'s stub
       docstring flags both options rather than picking one.
     - The pre-HTTP credential guard's exception TYPE is pinned
       provisionally to `tradekit.mae._data.errors.ProviderRequestError`
       (reusing the data-provider's own type, since `broker` has no
       existing typed-refusal-for-missing-env-var precedent of its own) —
       CTO may prefer a broker-native exception instead; not asserted as
       final.
     - `partially_filled` order status maps to our `"open"` (module
       docstring: "MVP: no synthetic partially_filled status"), which
       means a caller polling `order_status()` cannot distinguish "nothing
       filled yet" from "half filled" without separately calling
       `fills()` — acceptable for MVP per the addendum's own "cum_qty
       tracked" phrasing, but not a design position we're claiming is
       final for P5.
     - `AlpacaBroker`'s stub `submit()`/`order_status()`/`fills()` do NOT
       yet call the pre-HTTP credential guard, token verifier, or any HTTP
       client — they are unconditional `NotImplementedError` raises. This
       means several `test_alpaca_broker.py` tests are red for a
       DIFFERENT proximate reason than their docstring's pinned target
       behavior (e.g. `test_submit_refuses_without_a_valid_verdict_token`
       expects `BrokerTokenRequired` but currently gets
       `NotImplementedError`) — intentional per the batch's "stub now, pin
       the target, implement batch B" split, called out explicitly here so
       nobody mistakes the mismatch for an authoring error.

    **CTO ratification (2026-07-18) — batch-A/P4-paper flags:**
    positions() reads the VENUE (GET /v2/positions) — ledger-derived
    positions would make reconcile circular; venue-truth is the dress
    rehearsal's purpose. Pre-HTTP credential guard = broker-local typed
    `BrokerCredentialsMissing` in _port.py (never import mae._data.errors
    across the module boundary). partially_filled -> "open" MVP: ratified.
    The R-011 pipeline test's re-wire (respx-driven AlpacaBroker fills
    replacing the removed temporary routing) is PRE-AUTHORIZED for the dev
    pass — fixture mechanism only, assertions unchanged. Stale advisory
    comment in broker/__init__: dev pass fixes.

    **CTO adjudication addendum (2026-07-18, dev-pass round) — round-23
    follow-ups, all implemented:**
    - **Accepted as implemented:** the additive `OrderAck.status`/
      `OrderAckPayload.status` Literal widening ("accepted" | "open" |
      "filled" | "canceled" | "rejected" — AlpacaBroker's submit echoes the
      mapped venue status instead of a fixed "accepted");
      `BrokerCredentialsMissing` SUBCLASSING `mae._data.errors.
      ProviderRequestError` with the one cross-boundary import confined to
      `_port.py` (the frozen `test_submit_refuses_before_any_http_call_
      when_env_keys_are_absent` asserts `pytest.raises(
      ProviderRequestError)` by class identity — subclassing is the only
      way to satisfy both that frozen assertion and the "broker-native
      named type" ratification at once); the R-011 rewire including its one
      unreachable-literal assertion fix (`ack.status == "accepted"` ->
      `"open"` — ALPACA_STATUS_MAP's output vocabulary never contains
      "accepted"); the broker/__init__ staleness cleanups.
    - **REJECTED: read-verb graceful degradation on missing credentials.**
      The dev pass initially had `account()`/`positions()`/`order_status()`/
      `fills()` return zero balances / `[]` / `"rejected"` when env keys
      were absent (to survive the generic conformance cases, which supplied
      no per-adapter environment). Adjudicated as FABRICATED DATA — the
      exact class ASSUMPTIONS 71/`NoQuoteAvailable` exist to kill (a $0
      account reads as a real broke account; an empty fills list reads as
      "reconciled clean"). **Pinned rule: no-creds is LOUD on every
      method** — all five `AlpacaBroker` methods raise
      `BrokerCredentialsMissing` before any HTTP call when either env var
      is absent; there is no graceful-degrade path anywhere on this
      adapter.
    - **Pinned rule: conformance builders own their environmental setup.**
      The thing that forced degradation was a HARNESS limitation, so the
      harness was fixed (authorized test edit): `tests/contract/
      test_broker_port.py`'s CASE_BUILDERS now take `(monkeypatch,
      respx_mock)` (same convention as `test_marketdata_port.py`'s
      builders); the "alpaca-paper" builder seeds monkeypatched env keys
      and registers respx routes so the adapter runs its honest code path
      offline, exactly like a real venue session. Order-lifecycle +
      activities routes read `docs/research/alpaca-paper-shapes-2026-07-18.
      json` (the capture source-of-truth) directly; the `/account`,
      `/positions`, and order-not-found (HTTP 404, `{"code": 40410000,
      ...}`) shapes are NOT in the capture and are flagged in the builder's
      docstring as Alpaca-DOCUMENTED rather than CTO-captured. Suite-body
      assertions untouched.
    - **AUTHORIZED and applied:**
      `test_reconcile_over_alpaca_broker_fixtures_vs_seeded_ledger_both_
      directions` registers the previously-missing `/account/activities`
      respx route (the real `fills()` implementation had exposed the test's
      reliance on the stub's `NotImplementedError`); the stub-era
      `pytest.raises(NotImplementedError)` wrapper is replaced by direct
      assertions of what it always pinned — both reconcile directions run
      over the real adapter, the seeded-vs-fixture triples match, result
      is "ok" with zero mismatches, no auto-halt.

    **CTO ratification (2026-07-18) — batch-B/P4-paper (round 24):**
    collapsed red/green split for mechanical changes: accepted (batch-A
    precedent; every change followed a pinned algorithm). live_path scope:
    the NARROW reading is RATIFIED per the agent's recommendation — a
    manual scope-all halt is not "about" a live account, and the dangerous
    class (halts CAUSED by live-path anomalies) is exactly the
    reconcile-produced set; the residual (an agent resuming a manual halt
    mid-live-sequence) is closed PROCEDURALLY in SESSION-SEED-P4's live
    sequence (no agent resumes ANY halt during the 3-trade sequence) and
    bounded by the two-man rule + 3x$25 budget. The policy.__all__
    surface-freeze edit (additive exception export) audited: the frozen
    test guards series-mutating VERBS; an exception class is not a verb.

## Round-25 — P4-paper post-sprint review fixes (Opus PASS + 1 MEDIUM fixed
now, 1 LOW docstring sweep), 2026-07-18

CTO-pinned MEDIUM-1: `AlpacaBroker`'s five `BrokerPort` methods had NO HTTP
error taxonomy — a non-2xx body flowed straight into field access, so a
transient 503/timeout on `order_status` fell through the `ALPACA_STATUS_MAP`
catch-all and FABRICATED a terminal `OrderStatus(status="rejected")` for a
request the venue never actually answered (misreporting a possibly-live
order as dead), while `account`/`positions`/`fills`/`submit` leaked bare
`KeyError`/`TypeError`/`json.JSONDecodeError` on malformed/error-shaped
bodies instead of a typed error.

- **Fix, mirroring the P1A `ProviderError` taxonomy semantics
  (`mae._data.errors`) but broker-native** (round-23's "never import
  mae._data.errors across the module boundary for `_alpaca.py` itself"
  still holds — this is the broker's OWN hierarchy): added `VenueError`
  (base) / `VenueRejected` / `VenueUnavailable` to `broker._port`.
- **Classification pin (`AlpacaBroker._parse_json`, applied before ANY
  field is read off a response, across all five methods):**
  - HTTP 429 or >= 500 -> `VenueUnavailable` (raise; the venue did not
    really answer — never fabricate a status/balance/list from this).
  - HTTP 404 on `order_status()` ONLY -> `OrderStatus(status="rejected")`
    (the ONE pinned case a 4xx maps to a domain value instead of raising —
    checked BEFORE `_parse_json`, explicitly NOT generalized to any other
    4xx or any other method; mirrors the pre-existing conformance-suite
    `order-does-not-exist` respx route in `tests/contract/
    test_broker_port.py`, which this fix keeps passing unchanged).
  - Any other 4xx (400-499, including 404 on every OTHER method, and 422
    anywhere) -> `VenueRejected` (raise; a real venue answer, just not one
    that maps to a domain value outside `order_status`'s 404 case).
  - A 2xx body that fails to decode as JSON, or has the wrong top-level
    shape (e.g. an error dict where a list of activities was expected), or
    whose otherwise-valid JSON is missing/mistyping an expected field
    (`KeyError`/`TypeError`/`ValueError`/`decimal.InvalidOperation` caught
    around the field-extraction block per method) -> `VenueUnavailable`.
  - `httpx.HTTPError` (timeouts/connection failures) raised by `_get`/
    `_post` themselves -> `VenueUnavailable` (the venue never answered at
    all, same bucket as a 5xx in terms of what may be inferred: nothing).
- **`submit()` validate-before-append discipline:** checked the existing
  event ordering first, per the CTO's instruction — `_append_order_submitted`/
  `_append_order_ack` were ALREADY called only after `response.json()` and
  field extraction succeeded (never before the POST), so the ordering itself
  was not the bug; the fix adds the missing status-code/malformed-body
  classification (`_parse_json` + a try/except around field extraction) in
  front of that pre-existing ordering. Net effect pinned by test: a 500 or
  422 on `POST /orders` now raises `VenueUnavailable`/`VenueRejected` with
  ZERO `OrderSubmitted`/`OrderAck` events appended (both cases tested).
- Red proof (captured in the "P4-paper review fixes: tests (red)" commit,
  4 tests red against the unmodified `_alpaca.py`): `order_status` on a 503
  raised `json.decoder.JSONDecodeError` deep inside `response.json()` (not
  `VenueUnavailable`, and NOT a fabricated "rejected" for this particular
  fixture only because the mocked 503 body was non-JSON text — the
  fabrication itself is real for any 503/429/5xx whose body happens to
  decode as JSON with no `status` key, e.g. an empty `{}` error envelope,
  which is the actual venue-shape risk this fix closes); `account` on a
  malformed 200 (missing `equity`) raised bare `KeyError: 'equity'`; `fills`
  on an error-dict 200 body raised bare `TypeError: string indices must be
  integers, not 'str'` (iterating the dict's keys as if they were activity
  rows); `submit` on a 500 raised the same bare `JSONDecodeError`.
- LOW-1 (documentation-only, no assertion changes): swept stale RED-phase
  module/test docstrings in `tests/unit/broker/test_alpaca_broker.py`
  (batch-A "NotImplementedError stub, expected RED" framing) and the
  `tests/contract/test_broker_port.py` header (batch-B "PaperBroker stubs,
  expected RED this batch" framing) to state the current GREEN/real-adapter
  truth — both suites' every case is real and passing as of this round.
- Verified: `uv run pytest` 824 passed (818 baseline + 6 new: order_status
  503/404, account malformed-200, fills error-dict, submit 500 and 422),
  `uv run ruff check .` clean, `uv run mypy` clean (73 source files).

    **CTO ratification (2026-07-18) — round-25: RATIFIED as implemented.**
    404-on-order_status is the one venue answer that maps to a typed
    OrderStatus; everything else non-2xx/malformed RAISES. The
    live-promotion blocker from review round 7 is closed pre-live.

## Round-26 — P5-PROP batch A red-phase pins (prop dials + evaluation
barrier simulator), 2026-07-19

143. **Prop dial block defaults to `None`/disabled (TD-24 convention);
    venue numbers live in `config.toml`.** New `PolicyDials` fields
    `prop_mdl_pct` / `prop_mdd_pct` / `prop_profit_target_pct` /
    `prop_fee_side_bps` / `prop_funding_daily_pct` /
    `internal_daily_soft_frac` / `internal_daily_hard_frac` /
    `internal_mdd_reserve_frac` are all `Decimal | None = None` in code —
    disabled unless configured, never coerced to a sentinel (entry 99
    discipline). The committed `config.toml` sets the Kraken Prop Starter
    values (0.03 / 0.06 / 0.10 / 4 bps / 0.00033 daily; buffers
    0.50 / 0.70 / 0.40 per Q.H.122–123/130–131). Report-1 §6/§8 is the
    venue source of truth for the first five.

    **CTO amendment (green phase, same day):** the Starter values ship in
    `config.toml` COMMENTED OUT, exactly like `max_daily_drawdown_default`/
    `max_lifetime_drawdown_default` (TD-24 precedent) — a bare
    `PolicyDials()` reads the repo-root config.toml, so live values there
    would contradict this entry's own None-by-default pin (caught by the
    green implementer, ratified as the committed behavior). The block
    activates when Mike uncomments it alongside standing up the first
    `prop:*` account.

144. **Internal-wall resolution for `prop:*` accounts (R-017/R-018
    wiring).** `policy.prop_account_walls(dials)` is the ONE resolution
    point: returns `(daily_wall_frac, lifetime_wall_frac)` =
    `(prop_mdl_pct × internal_daily_hard_frac,
    prop_mdd_pct × (1 − internal_mdd_reserve_frac))` — Starter numbers:
    (0.021, 0.036). Returns `None` (walls disabled, R-017/R-018 emit
    `not_configured`) unless ALL four inputs are set. The 50% soft frac is
    NOT an R-rule — it is a HUD/advisory threshold (later batch); only the
    hard wall denies. Venue numbers (3%/6%) remain the OUTER truth the
    simulator models; R-rules enforce only the internal walls.

145. **Barrier semantics (venue-exact, Report-1 §6; each is a golden):**
    (a) MDL floor for a day = `snapshot_balance × (1 − mdl_pct)` where
    `snapshot_balance` is the BALANCE (realized only, fees/funding
    applied, open positions excluded) at 00:30 UTC; day 1's snapshot is
    the starting balance. (b) Breach comparisons are ANTI-PERMISSIVE at
    the boundary: equity `<=` floor breaches (both MDL and MDD) — the
    venue's "falls $3,000 or more" wording on the $100k worked example.
    NOTE the deliberate asymmetry with R-017/R-018's `<=` ALLOWS
    convention (entry 99 lineage): internal walls are OUR dials (generous
    to us at the boundary is safe because they sit far inside the venue
    walls); the simulator models the VENUE's barrier, where assuming
    breach at equality is the conservative direction. (c) MDD floor =
    `starting_balance × (1 − mdd_pct)`, STATIC for the account's life —
    never trails peak equity. (d) Profit target: equity `>=`
    `starting_balance × (1 + profit_target_pct)` absorbs into "passed"
    (venue force-flattens); subsequent scripted trades are ignored.
    (e) All three barriers are absorbing; first hit in ledger-event time
    order wins.

146. **Fee/funding accrual pins (venue-exact where documented, flagged
    where not):** (a) commission = `side_notional × fee_side_bps/10_000`
    per side, where entry-side notional = `TradeRecord.size_usd` and
    exit-side notional = `size_usd × exit_price/entry_price`; (b) funding
    = `entry_notional × funding_daily_pct/6` charged at each UTC clock
    mark in {00,04,08,12,16,20}h with `entry_ts < mark < exit_ts`
    (exclusive both ends: a position closed exactly at a mark is not
    charged at it; funding on ENTRY notional, not marked-to-market —
    PLACEHOLDER pending Report 2's microstructure numbers); (c) every
    ledger application (fee, funding charge, realized P&L) is quantized
    to the cent, ROUND_HALF_EVEN, at application time (matches
    event-sourced ledger reality; 0.165 → 0.16); (d) ledger events apply
    in timestamp order — entry fee at entry_ts, funding at marks,
    realized P&L then exit fee at exit_ts; (e) fees and funding reduce
    balance and therefore count toward MDL and MDD (Report-1 §6/§8).

147. **Scripted-mode breach granularity (LIMITATION, deliberate):**
    `ScriptedTradeModel` replays a fixed `TradeRecord` sequence as ONE
    deterministic path and evaluates barriers on the realized-balance
    ledger at each ledger event — there is no intratrade
    unrealized-equity path in scripted mode (TradeRecord carries no
    intratrade marks), so an intratrade adverse excursion that would have
    breached the venue's real-time equity check is NOT detected. This
    makes scripted-mode results OPTIMISTIC on breach probability; it is a
    golden/replay seam and a backtest→barriers bridge, not the risk
    canon. Parametric mode shares the granularity (per-trade resolution)
    — modeling intratrade MAE is a flagged future refinement, NOT
    improvised in batch A.

148. **Parametric mode uses INDEPENDENT per-trade draws (batch-A flag
    resolved):** no serial-correlation dial in v1 — serial dependence
    enters via `EmpiricalTradeModel`'s BLOCK bootstrap (block length is a
    spec field there), keeping one mechanism per concern. Parametric
    risk_frac is a fraction of CURRENT balance at entry (multiplicative
    walk); win pays `risk × payoff_ratio`, loss costs `risk`, exactly
    `trades_per_day` trades per day spaced `hold_hours` apart.

149. **Zero-edge sanity envelope (batch-A flag resolved — CTO
    derivation):** for a multiplicative driftless walk (win_rate 0.5,
    payoff 1.0, fees/funding zero) between static absorbing barriers,
    gambler's-ruin in LOG space gives
    `pass_prob ≈ |ln(1−mdd)| / (|ln(1−mdd)| + ln(1+target))` — Starter
    numbers: 0.06188/(0.06188+0.09531) = 0.3936 (additive approximation
    0.375 is the sanity cross-check). Envelope test uses risk_frac 0.005
    with trades_per_day 4 so the worst daily move (2%) can NEVER reach
    the 3% MDL — MDL provably non-binding, isolating the two-barrier
    result; pinned envelope `0.36 <= pass_prob <= 0.43` with horizon long
    enough that `pass_prob + ruin_prob >= 0.99`. Negative-edge companion
    (win_rate 0.45): `ruin_prob > pass_prob`. Seeded, so deterministic
    once green — the envelope tolerates estimator noise + step-overshoot
    bias, not flakiness.

150. **`recommended_max_risk_frac` ladder + monthly normalization
    (Q.A.8):** parametric mode only (`None` otherwise). Ladder =
    risk_frac in {0.0025, 0.005, 0.0075, 0.010, 0.0125, 0.015, 0.0175,
    0.020}; for each rung the engine re-runs the spec with that
    risk_frac (same seed derivation) and computes monthly ruin
    `1 − (1 − ruin_prob)^(30/horizon_days)`; recommendation = the
    LARGEST rung with monthly ruin `<= 0.02`, or `None` if no rung
    clears (never "the least-bad rung" — fail closed).

151. **Prop-basis placeholder (batch-A flag resolved as PLACEHOLDER):**
    spot-vs-PROP instrument basis default 2 bps, observed ONCE (ETH,
    2026-07-19 Kraken Desktop screen) — ratified as
    placeholder-pending-Report-2; it is a `CostModel` slot consumed in
    batch B, recorded here so the number's provenance is on the record
    before it gets load-bearing.

152. **Scripted timeline guards (review round, batch A — FIX-FIRST
    findings 1/3/4):** (a) a scripted trade list whose calendar span
    exceeds `horizon_days` raises `ValueError` — never simulated
    silently (the leak produced a breach outside the window with an
    all-zero hazard vector, an internally inconsistent result; batch B's
    backtest→barriers bridge is exactly the caller that would hit it).
    (b) Barrier levels (MDL floor, MDD floor, target) are compared
    UNQUANTIZED — cent-rounding a floor can round it down, permissive at
    the boundary against entry 145b; only ledger applications quantize.
    (c) When one event crosses BOTH floors and they are exactly equal,
    the tie resolves to "mdl" (higher-floor-wins with mdl on equality;
    consistent in both engines).

153. **00:30 UTC snapshot boundary is EXCLUSIVE (review round, batch A —
    FIX-FIRST finding 2):** the daily snapshot is the balance from
    ledger events with ts strictly BEFORE 00:30; an event stamped
    exactly 00:30 lands in the new day (snapshot computed at the
    instant, the same-instant fill settles after). The venue's "balance
    at that moment" wording does not resolve the instant itself; this
    direction is pinned so the golden (exit at exactly D2 00:30 excluded
    from D2's snapshot) enforces ONE behavior. Revisit only if Kraken
    support answers otherwise (support ticket already pending).

154. **bridge-read batch 1 flags ratified (red phase, 2026-07-20):**
    (a) `grade_exposure` re-resolves every logical selector against the
    LIVE tree by cascade `automation_id -> name -> path` (the map's
    stored `by` records how the probe found it, but grading must not
    trust stale probe metadata — the signature takes the tree precisely
    to re-resolve). Grade A requires every target resolvable at the
    automation_id tier; B = all resolvable, >=1 only via name/path;
    C = >=1 unresolvable. (b) `parse_qty` deliberately NOT added in T3:
    qty grammar is pinned in T4 against `_read.py`'s actual needs —
    no invented surface (test-writer flag, CTO-ratified).

155. **bridge-read batch 2 flags ratified (red phase, 2026-07-20):**
    (a) POSITIONS_TABLE rows = resolved node's children in on-screen
    order; each row's children = 5 cells [symbol, side, qty,
    entry_price, unrealized_pnl_usd] read via .value — PLACEHOLDER
    grammar pending T7's real tree (re-freeze through the golden gate).
    (b) by:"path" selector value = list of name strings resolved as
    unique-name ordered descent from root. (c) `snapshot()` gains a
    required `captured_at: AwareDatetime` keyword (caller/CLI supplies
    it; driver never wall-clocks) — spec-pin amendment; red tests
    assert presence only this batch. (d) `_read._load_element_map_for_
    session` is an ACCEPTED internal seam (default-map resolution lands
    with T7's real map); (e) AC-12 drift check lives at the CLI layer,
    driver surface unchanged.

156. **Sol-audit amendments ratified (2026-07-20, external audit of
    STRATEGY-PROCEDURE):** (a) CONFIRMED DEFECT (MED): `_deflated_
    sharpe`'s SR* scales the expected-max term by the candidate's own
    estimator variance (denom/(n-1)), not the Bailey-LdP cross-trial
    dispersion V[SR_trials] — DSR is overstated (anti-conservative)
    when tried variants disperse. Fix pinned into M5.2: experiment
    registry stores per-trial SR; V[SR_trials] computed from it;
    current proxy allowed ONLY with a "dsr_dispersion_proxy" warning
    until >=2 registry trials exist. (b) HMM state labels currently
    derive from vol-variance rank alone (ratified 2026-07-16, now
    AMENDED): relabeling from state-conditional return mean/persistence
    + OOS utility is scheduled with M5.2 regime work; until then,
    labels are treated as vol-tiers, not semantic market calls.
    (c) Sharpe: trade-level sqrt(trades/year) annualization stays
    display-only; DSR/PSR remain on non-annualized trade SR (already
    true); bar-level marked-to-market daily Sharpe becomes primary
    when M5.2 equity curves exist. Stage-5 tiebreak expectancy
    normalized in R/bps, not fixed dollars. (d) v1 exclusion list
    rationale is SCOPE/DATA-based, not "debunked" (OFI/stat-arb have
    real evidence at other horizons/infrastructures); tick/book
    collection (Q.F.83 collector, greenlist 11 pairs) preserves the
    option to revisit. (e) DSR 0.5 = internal screening policy; 0.95 =
    literature-grade bar required for live promotion. ADX-25 and
    100/50-trade minimums documented as house rails, not laws.
    (f) Prop profit target is per-plan spec input (never hard-coded);
    re-verify on purchase screen per plan.
