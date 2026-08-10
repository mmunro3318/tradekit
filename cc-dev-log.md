## 2026-08-10 (Opus — Kraken book to 1 Hz, history synced; archive halved)

- Mike ratified: one book sampling policy archive-wide, 1 Hz (ASSUMPTIONS 180).
  `collect_ticks` never had a RowThrottle — it predates collector_core and
  never inherited `throttled_streams={"book"}` — so the largest stream was
  recorded at Kraken's update rate while Coinbase and OKX were coalesced.
- COLLECTOR: throttle gates the WRITE only. `apply_update` still runs on every
  message, so book state is unchanged and no update is missed. Trades are
  untouched on every venue and pinned by a counter-test — a coalesced book row
  costs resolution, a dropped print is a hole in the tape.
- HISTORY: new `scripts/downsample_book.py`. 342,389,849 -> 14,658,656 rows,
  **95.7% dropped**. ticks 4.48 -> 0.85 GB, whole archive 6.98 -> 3.36 GB.
- I QUOTED THE WRONG NUMBER FOR APPROVAL. Told Mike ~10x (89.9%); real figure
  95.7%, ~23x. The estimate counted distinct seconds on 2026-08-08 — a
  SATURDAY. ETH/USD averages 18.0 book updates/sec at weekends against 45.7 on
  weekdays. Caught it in the dry run and corrected before executing an
  irreversible delete, but one day is not a sample. Logged in FRICTION.
- BUG THE TESTS CAUGHT: the first downsampler sorted by the ts STRING. ISO-8601
  does not sort lexicographically across mixed fractional precision —
  "12:00:00Z" sorts AFTER "12:00:00.5Z" because "." < "Z", and isoformat()
  omits the fraction when it is exactly zero. It was keeping the LATER row of
  each window and dropping the earlier one. Now sorts by parsed instant.
- Also fixed en route: `repartition_archive` blew up ~145x through
  `to_pylist()` on 41-column book tables (8.5 GB RSS, unfinished after 22 min
  on one symbol-day). Rewritten to slice in Arrow: whole ETH_USD symbol,
  67.5M rows, 40 seconds. And `--dedupe` is now OPT-IN — it had been silently
  dropping ~23% of Kraken book, pre-empting the very decision that was open.
- Both repair tools now share one tree lock. I had launched a second repair
  while the first was running and both were reading the same 698 MB symbol;
  nothing was lost only because all reads precede any write.
- VERIFIED: second downsample pass drops 0 (idempotent); every CLOSED day has
  zero book rows <1s apart; 0 rows in the wrong hour after the rewrite; trades
  1,519,608 unchanged. Live post-deploy gaps all fall in 900-1000 ms — clock
  jitter (gate reads monotonic, ts is captured at message receipt), not
  throttle failure. Remaining sub-1s rows are 2026-08-10 pre-deploy only.
- Gate green at every step. 18 commits on fix/event-time-partitioning.

## 2026-08-09b (Opus — the archive was filing rows by INGEST time; every stream, every day)

- Tree committed first (3 commits: .github assets, the collector sprint,
  the docs/seed). It had been sitting green and uncommitted for a session.
  Fix work then went on `fix/event-time-partitioning`.
- THE BUG: every sink named its target file from FLUSH time, so a row's
  on-disk hour recorded when we ingested it, not when it happened. Hour
  partitioning that lies is worse than none — it invites time-ranged reads
  that silently return the wrong rows.
- Measured before the fix, 2026-08-08 alone. NOT a rounding error:

  | stream | rows | wrong-hour | wrong-day |
  |---|---|---|---|
  | ticks (kraken book) | 24,236,349 | 1.87% | 38,148 |
  | books/coinbase | 1,889,897 | 0.74% | 427 |
  | books/okx | 207,137 | 5.65% | 0 |
  | trades/coinbase | 92,076 | 5.90% | 110 |
  | trades/okx | 35,323 | 4.72% | 0 |
  | perps/hyperliquid (ctx) | 399,050 | 3.12% | 0 |
  | liquidations/okx | 299 | 18.39% | 0 |
  | equities/alpaca | 5,150,262 | 14.7-18.5% | 100% at weekends |

- THE UNCOMFORTABLE PART: the collector_core streams score WORSE than the
  legacy ones. That is a direct cost of last session's MIN_PART_ROWS change —
  making a buffer wait until it earns a file means more buffers straddle an
  hour boundary. Last session's own FRICTION entry claims the hour escape
  handled it; the escape fired correctly and then wrote the rows into the NEW
  hour's file, which is the bug it claimed to prevent. Trading file overhead
  for hour attribution was not a trade anyone chose.
- FIX: `PartitionedParquetSink` buffers (ts, row) pairs and one flush writes
  one part file per (day, hour) the buffer spans. `flush()` lost its `ts`
  parameter entirely — a parameter that looks like it decides the path but
  does not is how this survived review.
- SECOND BUG, Alpaca: `start` was formatted `%H:%M:%SZ`. Alpaca's `start` is
  inclusive, so every pass re-requested and re-wrote the whole final second of
  the tape. Over the closed weekend the cursor could not advance at all: 15
  prints re-stored 176 times each, 2,625 redundant rows. Fixed with a
  microsecond-exact cursor plus identity suppression scoped to the boundary
  instant — no arithmetic cursor is correct here, because `start` is inclusive
  and the venue stamps nanoseconds while a datetime carries microseconds.
- THIRD, cosmetic: no `_CLASS_RULES` rule matches an equity ticker, so all ten
  symbols were filed under `equities/alpaca/crypto/`. Alpaca's sink now runs
  with `partition=False` — the venue tree IS the asset class.
- SCOPE FOUND MID-FLIGHT: `collect_ticks`, `collect_books_coinbase` and
  `collect_books_binance` each carried their OWN private ParquetSink — 74% of
  the archive by volume, and not one test between them. All three had the
  flush-time bug plus read-modify-write: read the whole hourly file back and
  rewrite it, every 60s, quadratic in rows/hour, and a kill mid-write takes
  the hour with it. It already had: `books/coinbase/crypto/CAKE_USD/
  2026-08-08/book-05.parquet` has no footer magic bytes. All three retired
  onto the shared sink; part files are append-only and cannot do that.
- REPAIR: `scripts/repartition_archive.py` re-files what was already written
  (possible only because the ts is in the data — nothing refetched). Deletes
  source files, so it is deliberately timid: dry-run default, never touches or
  writes into days at/after the cutoff, skips a whole (symbol, day, stream)
  unit if any file in it is unreadable, leaves unparseable-ts rows put, and
  does not rewrite an hour that is already correct. All reads happen before
  any write. 15 tests; they passed first run rather than going red, so
  discrimination was verified by mutation (4 mutants, all caught) instead.
- ALPACA TREE REPAIRED AND VERIFIED: 5,148,222 rows read, 851,441 moved
  (16.5%), 585 exact duplicates collapsed, 0 skipped; second pass a clean
  no-op. The stale `2026-08-09` partitions held 2,145 rows of which **zero**
  were unique — proved row-by-row against the rest of the tree before
  deleting. Post-repair audit: 0.00% wrong-hour on every day, 0 duplicate
  keys, 5,147,637 rows = exactly the distinct-observation count from the
  pre-repair audit. Nothing lost.
- ASSUMPTIONS 179 records the four judgment calls (partition key, cursor
  semantics, what counts as a duplicate, and "when unsure, do nothing").
- IT TOOK FOUR FIXES AND ONLY MEASUREMENT FOUND THE LAST THREE. Sink fix ->
  0.1083% (hour 13); run_ws_collector was still passing ARRIVAL time ->
  0.0009% (hour 14); collect_perps_hyperliquid is a custom orchestrator that
  bypasses the shared runner and did the same -> 0.0000% (hour 15). Three
  callers making the same mistake independently means the PARAMETER was the
  bug: `add`'s `ts` is now the arrival time, a fallback, and the row's own
  stamp wins. Do not simplify that back to trusting the caller.
- VERIFIED hour 15 UTC, first full hour on the final build: 442,479 rows
  across all 8 streams, **0 misfiled**. Plus 855,546 rows stamped after the
  restart with 0 misfiled, and 56,053 rows stamped 14:59:xx every one of which
  is in an hour-14 file — the boundary is where this bug always hid. 0
  duplicates on every stream carrying an id.
- TWO OPEN FINDINGS, both pre-existing, neither fixed, both in the seed §5b:
  (a) Coinbase persists 100-row snapshot blocks though parse() provably skips
  snapshots — mechanism unexplained, now redundancy rather than corruption;
  (b) collect_ticks has NO RowThrottle, so Kraken book (the largest stream)
  runs unthrottled at ~2.2 rows/s against 1/s everywhere else, and `now` is
  computed per message so rows share timestamps. That one is Mike's call, not
  a unilateral fix.
- REGRESSION I CAUSED, AND THE AUDIT DID NOT CATCH IT. repartition_archive
  emptied RIOT/2026-08-08 and left the directory; last_stored_cursor read only
  the newest day dir, found nothing, returned None, and the poller fell back
  to its 5-day floor — re-storing five days of tape every five minutes
  (rows=3710400 per pass). 82,087,002 rows written, 76,939,365 of them
  duplicates; collapsing returned the tree to exactly 5,147,637 rows, the
  same distinct count as before. Nothing lost. Fixed at both ends (cursor
  walks days newest-first; the tool removes a directory it empties). Found by
  reading the collector's own LOG — the partition audit was green at 15:12
  while this had been running since 14:55. One green property implies nothing
  about another.
- FINAL VERIFICATION, complete closed hour 15 UTC entirely on the final build:
  1,953,929 rows across all 8 streams, 0 misfiled (0.0000%). 32,308 rows
  stamped 15:59:xx, every one in an hour-15 file. 0 duplicates on every stream
  carrying a unique id. Watchdog LastTaskResult 0, 8/8 up, compaction current,
  archive 7.59 GB / 457 GB free. Alpaca rows=0 per poll (market closed).
- MEASURED finding (b): Kraken book, BTC_USD hour 15 = 40,334 rows against a
  1 Hz ceiling of 3,600. 9,186 are BYTE-IDENTICAL duplicates (23%) and 6,508
  are distinct book states sharing a timestamp. Adding the throttle other
  venues already have would cut the biggest stream ~10x. Mike's call.
- Gate green at every step; ten commits, red committed separately.

## 2026-08-09a (Opus — data-vacuum cutover complete: 8 live streams, watchdog was silently dead)

- Seed: `docs/handoff/HANDOFF-2026-08-09-data-vacuum-expansion.md`. Gate 1314
  green, ruff clean, TREE UNCOMMITTED (26 paths).
- GREENLIST 56 -> 87: full stablecoin sleeve (peg + stable-vs-stable + fiat
  legs incl. OKX-only USDT/TRY, USDT/BRL, USDT/AED). Perplexity cross-check
  surfaced 4 real tokens our own scan missed (AUDF, BRL1, MXNB, EURQ).
- 8 LIVE STREAMS (was 3): +Coinbase trades, +OKX books/trades/liquidations,
  +Hyperliquid perps (all 232), +Alpaca SIP equities. Binance.US RETIRED
  (2,669 BTC prints/day vs Kraken 42,063; its WS trade channel publishes
  nothing — proved with a control stream on the same socket).
- LAYOUT MIGRATED: 124 dirs -> <class>/<SYMBOL>/<date>/, PARTITION_BY_CLASS
  True. Required unifying paths first — the 3 original collectors had private
  path helpers and would have recreated flat dirs alongside the migrated tree.
- NUMBERS CORRECTED: a subagent read OKX `volCcy24h` (QUOTE ccy) as USD.
  USDT/TRY is $9.9M, not "$470M". Kraken figures were ~3x high too. Recomputed
  all of them by hand with explicit fx conversion; true values now in comments.
- THREE MORE COLLECTOR BUGS (docs/FRICTION.md):
  (4) `_PART_RE` was `[a-z_]+` — a stream named `aggTrades`/`book5` matched
      nothing, so compaction became a silent no-op AND `_next_part` always
      returned 0, so every flush overwrote part-0000. Same data-loss bug as
      (1), through a different door. One regex fed two consumers.
  (5) tiny part files: flushing every buffer every 60s wrote 6-row files at
      232 symbols. 6.54 -> 2.55 GB/day via MIN_PART_ROWS + bounded escapes.
  (6) OKX closes idle conns ~30s and ignores protocol pings — the sparse
      liquidation feed reconnected ~10x/240s. Added VenueSpec keepalive; then
      had to tolerate the non-JSON `pong` reply. Now 0 reconnects.
- OPS, THE BIG ONE: the watchdog SCHEDULED TASK had been failing every run
  with 0x80070002 (ERROR_FILE_NOT_FOUND) — it executed `pwsh`, which resolves
  only to a Store app-execution alias that Task Scheduler cannot run.
  Collectors survived by luck; compaction did not run for 9.5h (1048s backlog).
  Repointed at full-path powershell.exe, verified LastTaskResult 0.
- OPS: collectors now launch with `python -u`. The historical "dies silently,
  empty logs" note was stdout BUFFERING — the buffer died with the process.
  Logs populate for the first time.
- Dead code removed: the unreachable try/except in `_next_part` (part_files
  already guarantees `\d{4}`).

## 2026-08-08a (Opus — data-vacuum expansion: greenlist 11->56, collector_core landed, 3 collector bugs fixed)

- GREENLIST 11 -> 56 pairs, grouped in-code by research intent (L1/infra/
  academic/bridge/dex/rwa/stables/fx/cross). Added BTC/USD — the venue's most
  active pair (42k trades/day, 0.02bp) was simply absent. Dropped CRV, kept
  CAKE as a reference series (research: NOT abandoned — $2.69B weekly DEX vol
  Jun-2026, supply cap cut to 400M Jan-2026; the thin tape is a US-venue
  artifact, not a dead protocol). ACX refused: Risk Labs is converting the
  token to C-corp equity, so the series has a scheduled death.
- THREE COLLECTOR BUGS (all in docs/FRICTION.md with repro):
  (1) verify_pairs compared REST `wsname` (XBT/USD) against WS v2 symbols
      (BTC/USD) — every BTC pair would have verified False and been dropped
      with only a warning into a 0-byte log. Fixed via _ws_v2_symbol.
  (2) Coinbase level2 caps at 30 products/session (binary-searched: 30 OK,
      31 rejected) then goes SILENT — indistinguishable from a dead socket,
      so the collector livelocked on reconnect and wrote nothing. Sharded.
  (3) collect_ticks had NO time-based flush; FLUSH_INTERVAL_S was defined,
      documented, and never used. Only 8 of 56 pairs ever wrote. Quiet pairs
      held rows in RAM (lost on crash) and were mis-filed into the flush
      hour's file. Historical thin-pair hour attribution is unrecoverable.
- NEW scripts/collector_core.py — one VenueSpec (url + subscribe + parse)
  per venue, runner owns sink/paths/throttle/backoff/sharding/error-frames.
  Writes are APPEND-ONLY part files compacted after the hour closes: O(rows)
  per flush instead of the old read-concat-rewrite (which cost ~0.1s/file/min
  and grew the process to ~414MB within an hour). Part files beat a
  persistent ParquetWriter here because these collectors DO die and a
  footer-less parquet is unreadable. Verified on 1010 real parts: 5.03M rows
  merged in 13.5s, 13% smaller, idempotent, current hour correctly skipped.
- NEW collectors, ALL OFF (not in watchdog, no scheduled task): Coinbase
  trades (public market_trades, no key — 453 rows/90s over 40 pairs), OKX
  books (NEW venue, reachable unlike Bybit — 37 pairs, 20-level, 1396
  rows/75s), Alpaca delayed-SIP equity puller (COIN/MSTR/IBIT/FBTC/GBTC/
  ETHA/GLD/MARA/RIOT/HOOD; real-time SIP needs a paid plan but historical
  SIP is free at T-15min; measured ~2MB/sym/day trades, ~10-15MB quotes).
- migrate_layout.py: flat <SYMBOL>/ -> <class>/<SYMBOL>/, dry-run default,
  refuses to run while collectors are live. 124 dirs would move.
- BINANCE.US IS NEARLY DEAD and its WS trade channel publishes nothing.
  Control test, one socket, 240s: depth20 -> 103 frames, @trade/@aggTrade ->
  0. REST confirms trades exist (BTCUSD 2,669/day = 1 per 32s, $1.26M/day vs
  Kraken's $90M). Trades must be REST-polled; consider dropping the venue.
- data.binance.vision (Binance GLOBAL history) is reachable although
  api.binance.com is 451. OKX live is 200; Bybit is 403.
- Gate: 1277 passed (+54 new collector_core/trades tests), ruff clean.

## 2026-08-03i (Fable — paper-sprint batch G2: AUTONOMOUS CADENCE GREEN. Sprint machinery COMPLETE.)

- SPEC-cadence T1+T2+T3 all landed (reviews rounds 21+22, ASSUMPTIONS
  177+178, GATE green): strategy-aware confirm chain (def-driven bracket/
  sizing/horizon; unknown-key 400 at the wire), execute_exit (net-qty
  sells mirroring execute_order's gated shape; entry-price reference
  ratified vs side-blind R-rules), exit_trigger (inclusive touches,
  stop-first), and run_once (paper-only refusal, funnel-only entries,
  two-phase policy w/ reject-on-deny at reviewed, crash-visible digest,
  degrade-don't-die marking, grade-recovery for flat+active).
  scripts/run_cadence.py ready; schtasks registration is MIKE'S step
  (documented in the header, two-man pattern).
- Round-22's defining finding: the failure envelope IS the product for an
  unattended runner — happy path held all four guarantees on first
  review; every defect lived in what happens when things break with
  nobody watching. Also: fix agent proved a CTO pin unimplementable
  (R-010/R-012 never pass vacuously) and redesigned correctly — grade A.
- SPRINT COMPLETE: 8 batches, 9 review rounds (14-22), ASSUMPTIONS
  170-178, 3 follow-up chips, ladder untouched throughout. The funnel now
  scans S1/S2/S4, trades only policy-passed tickets on paper, flattens on
  stop/target/horizon, grades itself, and writes the daily digest.

## 2026-08-03h (Fable — sprint checkpoint: MTF-SCAN complete, G2 seeded)

- Live-market smoke of the finished walk: 11 symbols scanned, 0 tickets --
  an HONEST wait with named killers per strategy per symbol (S1/S2 die at
  confluence, S4 at regime prefilter: regime not recommending
  mean_reversion today). Watch-item -> digest: per-strategy prefilter-kill
  counts (an S4 that never arms is a data finding).
- G2 cadence seed written: docs/handoff/HANDOFF-2026-08-03-cadence.md
  (thesis-from-StrategyDef builder w/ horizon validation, THE EXIT VERB
  (net-qty sells, carried pin), scheduler per watchdog pattern, daily
  Mike digest, structural paper-only + funnel-only guards). CLAUDE.md
  focus updated. Day's tally: 7 batches, 7 review rounds (14-20), 3
  follow-up chips, ASSUMPTIONS 170-176, gate green throughout.

## 2026-08-03g (Fable — paper-sprint batch G1: T-MTF-4 registry walk GREEN)

- hud's setup stage is now the REGISTRY WALK: per symbol, STRATEGIES in
  priority order, ANY-intersection regime pre-filter, scan_confluence per
  def, first match with non-empty tags on every leg claims (strategy_key
  on _SetupResult + named in the setup gate). Red babcd49, review round 20
  FIX-FIRST with 2 HIGH both caught by adversarial review: a broad
  except-Exception that would have SILENTLY killed any future
  misconfigured strategy (narrowed to ProviderError; loud escape restored)
  and an attrition-stages regression vs 163b (walk now synthesizes stages
  naming real killers). ASSUMPTIONS 176. GATE green. Chips filed: regime
  pass-through (HMM economy), scan_confluence audit-awareness (T-AUDIT-3).
- MTF-SCAN COMPLETE (T-MTF-1..4 all merged). Funnel = S1 momentum, S2
  pullback, S4 reversion, walked first-match-wins. Remaining: batch G2
  autonomous paper cadence (spec drafted in scratchpad: thesis-from-
  StrategyDef + exit management + scheduler + daily digest; money-path
  review; funnel-only red line structural).

## 2026-08-03f (Fable — paper-sprint batch F: S4 reversion GREEN, verdict ACCEPT)

- S4 restricted reversion registered (STRATEGIES = S1, S2, S4): single 1h
  leg {rsi_max 25, bb_position below_lower} min_tags 2, mean_reversion
  family, HALF SIZE (0.5) + r_multiple_override 1 -- the bear-regime
  strategy, most likely to fire in current market. ThesisContract gains
  horizon_hours: int = 168 (S4 will set 48 when cadence wires
  StrategyDef->thesis). Red 80dc469, review round 19 ACCEPT. Adjudications:
  doc's "at_support" = tag/value conflation (below_lower is the value);
  red's "(1/2 tags)" contradicted 172.1 AND-kill semantics (corrected 0/2);
  S2's exact-registry pins broke on append -> relaxed per round-13
  fragile-pin lesson. ASSUMPTIONS 175. GATE green.
- THE FUNNEL NOW HAS ITS BEAR-REGIME STRATEGY. Remaining: T-MTF-4 hud
  registry walk + autonomous funnel-only paper cadence (batch G) -- the
  last machinery before paper trades accumulate toward 30.

## 2026-08-03e (Fable — paper-sprint batch E: S2 pullback GREEN, verdict ACCEPT)

- S2 pullback-continuation live in the registry: 4h {ema_above 50 +
  macd bullish_cross} min_tags 2 -> 1h {rsi_band [35,50]} min_tags 1.
  New vocab wired into the SHARED evaluation path (both scan verbs);
  trend_up/pullback tags -> momentum. EMA already existed (SMA-seeded,
  golden-covered) -- only wiring needed. Red fd86be4 (22 tests incl.
  hand-derived RSI 35.0/50.0 exact-boundary goldens), review round 18
  ACCEPT (first clean verdict; red-s2 graded A). ASSUMPTIONS 174 pins
  strict-> / inclusive-band semantics + the S2-1 residual + the
  regime_families tension deferred to T-MTF-4. GATE green.
- THE FUNNEL NOW HAS A SECOND WAY TO FIRE. Next: S4 restricted reversion
  (the bear-regime strategy) + horizon_hours thesis field, then T-MTF-4
  walk + funnel-only cadence.

## 2026-08-03d (Fable — paper-sprint batch D: T-MTF-3 registry GREEN)

- Strategy registry landed (mae/_strategies.py: frozen 7-field StrategyDef,
  STRATEGIES priority tuple, build_registry/STRATEGY_BY_KEY, all public via
  mae). S1 migrated. Red 55b8c10, green, review round 17 FIX-FIRST -- the
  catch that mattered: min_tags=0 made S1 unconditional under confluence
  semantics and would have SHADOWED S2 forever under T-MTF-4 first-match-
  wins; re-adjudicated to min_tags=1 (decision-identical to hud's arm gate).
  ASSUMPTIONS 173 (incl. the T-MTF-4 non-empty-tags pin), GLOSSARY now
  disambiguates strategy registry vs tag-family registry. GATE green.
- tests/ gained __init__.py package plumbing (basename-collision fix,
  reviewer-accepted); backlog: pytest --import-mode=importlib for the
  class-wide cure.
- Next: S2 pullback (needs ema_above + rsi_band vocab), then S4 reversion
  (+ horizon_hours thesis field), then T-MTF-4 walk + cadence.

## 2026-08-03c (Fable — paper-sprint batch C: T-MTF-2 scan_confluence GREEN)

- scan_confluence verb landed (mae/_confluence.py behind the __init__ verb;
  ScanLeg TypedDict exported). Red 7ce069b (11 tests), green, review round
  16 FIX-FIRST: 1 HIGH caught (provider error escaped the verb -- at
  autonomous-cadence time one 5xx would have killed whole funnel runs) + 3
  MED, all fixed same-session (13 tests final), GATE green. ASSUMPTIONS 172
  pins the five adjudicated semantics (one warning shape, short-circuit,
  duplicate-tf loud reject, min_tags=0 unconditional, provider containment).
- Notable: scan() itself has NO internal provider containment (hud contains
  at call site) -- confluence is now the more robust verb; wordings to be
  reconciled if scan() ever gains containment. Follow-up chip: extract
  shared filter-vocab validation (logic forked, drift risk).
- Next: T-MTF-3 strategy registry (S1 migrated behavior-identical), then
  S2/S4, then T-MTF-4 + funnel-only cadence.

## 2026-08-03b (Fable — paper-sprint batch B: wound-scale GREEN)

- SPEC-wound-scale: severity int 1..5 -> enum minor/major/fatal (ratified
  07-25). Red d1f50ff, green, GATE green, review round 15 (FIX-FIRST, MED
  cluster fixed same-session: bool-trap pinned True/False, score_exchanges
  rank-validates every exchange, ASSUMPTIONS 171 + GLOSSARY wound-scale).
  Key simplification discovered at spec time: blocking was ALWAYS count-based
  (unresolved_attack_threshold); severity's only live site is the reporting
  tally -- representation migration, zero gate-semantics change. Parse
  boundary (_call_reviewer_and_score) maps legacy ints, rejects everything
  else through the existing malformed_output taxonomy.

## 2026-08-03 (Fable — paper-sprint batch A: in-kind fee fix GREEN)

- SPEC-inkind-fees spec'd, red (004a097+5bcfd53), green, GATE green, money-path
  review round 14 (FIX-FIRST: zero code defects, hygiene only; both agents A−).
  Alpaca in-kind crypto fee physics now modeled end-to-end: FillRecorded gains
  fee_asset_qty (default 0, historical events replay under recorded physics);
  paper+alpaca buys withhold ceil9(0.0025×qty) in-asset, cash delta exact
  notional; positions() nets the withhold; compute_pnl drops the entry-fee
  term iff in-kind (double-count guard); GOLDEN pins the 2026-07-26 live ETH
  round trip to the venue's own $50.00→$49.97 to the cent. ASSUMPTIONS 170
  (ceiling rounding PROVISIONAL — re-measure on the 3 probationary trades),
  GLOSSARY in-kind-fee/net-held-qty entries, agent-metrics round 14.
- Carried-forward pin for the cadence batch: sells sized from positions() net
  qty, NEVER entry filled_qty (live smoke run proved full-qty sells reject).
- Sprint plan tasked (TASKS-inkind-fees + task graph): next wound-scale
  migration (spec drafted, three-layer finding: exchange schema + persisted
  rubric_scores tally + dials blocking predicate), then T-MTF-2→3, S2, S4,
  T-MTF-4+cadence. Recon: STRATEGY-PACK requires MTF-SCAN first (S2/S4 are
  ScanLeg lists over scan_confluence); strategies.py TAGS registry already
  exists; S2/S4 vocab (ema_above, rsi_band) collides with nothing.

# cc-dev-log

Chronological dev log. Newest entry first. One entry per working session; keep entries terse — decisions and deltas, not narration.

## 2026-07-27 (Fable — three-thread fork seeded; dispatch skeleton codified)

- Three handoff seeds written+committed (Mike forking to clean threads):
  paper-sprint (CRITICAL PATH — fee fix, S2/S4, MTF-2, autonomous paper
  cadence w/ funnel-only rule), indicator-lab (experiments/ only, teach+test,
  next-period-entry check mandatory), stratchpad (charting SPA wishlist →
  starts at tk-brainstorm; read-only red line). CLAUDE.md focus points at all
  three.
- Subagent-seeding methodology CODIFIED into spawn-mvm SKILL.md: 9-part
  canonical skeleton (context/study-first/mission/PINNED/probe-before-parse/
  scope-fence/ASSUMPTIONS-hatch/self-verify/report-format) — skeleton fixed,
  content always bespoke.
- Funnel drought diagnosis stands: long-only bullish_cross starved in bear
  leg; fix = strategy breadth, never threshold loosening.

## 2026-07-26b (Fable — LIVE round-trip PASSED; P4 path ratified Option A; backfill complete)

- **LIVE $5 ETH round-trip PASSED** (Mike-run, one-shot scratch script, deleted
  after): buy 0.002602483 @ 1883.57 → hold 30s → sell full position @ 1882.03
  → flat YES, net -$0.0163. Proves live auth/order/fill/close/reconcile path.
  Preflight: account ACTIVE, crypto ACTIVE, $50, no blocks.
- **FINDING (pin for P4 sprint): Alpaca takes crypto fees IN-KIND** — buy
  filled 0.002602483 but position held 0.002595976 (fee deducted in ETH).
  CostModel/ledger assume USD fees (ASSUMPTIONS 144) → live crypto reconcile
  would flag phantom shortfalls. Needs a spec'd fix before probation trades.
- **P4 "done" RATIFIED with Mike = Option A**: 3 live trades are the T2
  probation sequence (live_sequence_remaining=3), NOT an ad-hoc goal; ladder
  stands unweakened (30 graded + positive edge + clean series → grant →
  Mike's `tk promote confirm`). 30-trade dial's intent = vet the autonomous
  bot, which is the actual product ("bot can SURVIVE going live" = done).
  Promotion state read: T1, 1/30 graded, all four T2 criteria false.
- **Tick backfill COMPLETE**: 269 REST requests, ~246k rows, all 11 pairs
  0 missing hours (incl. 4 book-anchored pairs from 07-19 14h). Watchdog
  scheduled task (15min) live. Next: multi-venue order-book harvesters
  (Binance/Coinbase, free public APIs only — Mike's open-data mission).

## 2026-07-26 (Fable — AUDIT-UX-2 vars lines; ticks → D:; repo-map + script-ify skills)

- **AUDIT-UX-2 shipped** (red b70b0d0 → green 3742de4, GATE green): `vars:`
  line under each indicator block — every input/intermediate from the SAME
  computation the gate read (macd_line/signal/hist/close, last_volume, bb
  upper/lower, atr window_n), no recompute. Mike's hand-replication ask.
- **Tick data → D:\tradekit-data\ticks** (1.19 GB robocopy'd off the ~full
  C:): collect_ticks.py `resolve_data_dir()` prefers D:, falls back local if
  drive absent (tested); Startup launcher .cmd updated (log too). Collector
  was found NOT RUNNING (unnoticed since unknown) — restarted, fresh parquet
  verified on D:. Consider a liveness check in tk-bootstrap.
- **New global skills** (Mike's ask): `repo-map` (~/.claude/skills/repo-map —
  stdlib-ast cached map, module→defs+linenos, 0.2s cached, --symbol lookup;
  the null-option code intel) and `script-ify` (meta-skill: mechanics→script
  reflex, token-cut target ≥50%, save-to-skill rules).
- Convergence msg in hud output = hmmlearn EM monitor stderr print (regime
  HMM); anti-permissive fallback to rules regime already handles it
  (_regime.py hmm_non_convergence). Explained to Mike; no code change.
- Next: walk Mike through P4 promotion (3 live trades — Alpaca recommended;
  prop has no API, Kraken live path untested), MTF-SCAN T-MTF-2.

## 2026-07-25c (Fable — AUDIT-UX-1 reading guides; formulas verified; GitNexus removed)

- **AUDIT-UX-1 shipped** (red 65d41f9 → green 7f1b4ee, GATE green): every GATE
  line in the audit log now followed by a `reading:` value-range guide (RSI
  0-100/70/30, MACD sign>magnitude, vr anchored 1.0, ATR pctile 0-100
  self-relative, BB ~2σ outlier, bars warm-up floor) — rendered even for
  SKIPPED gates. Mike's direct UX feedback on the exhaustive output.
- **Formulas independently VERIFIED** (background agent vs published refs):
  RSI vs StockCharts spreadsheet (max diff 0.0049 = ref rounding), ATR +
  Bollinger + MACD vs Tulip tables (≤0.005), volume_ratio hand-checked. All
  conventions (Wilder seeds, SMA-seeded EMA, population stdev) = mainstream
  standards. Zero code changes needed. Noted in SCAN-AUDIT-LOG.md.
- **GitNexus FULLY REMOVED** (Mike: never worked): MCP server entry out of
  ~/.claude.json (backup .bak-gitnexus-removal), Pre/PostToolUse hooks out of
  ~/.claude/settings.json, hook scripts + .claude/skills/gitnexus/ +
  .gitnexus/ deleted, CLAUDE.md + AGENTS.md blocks stripped. FRICTION FTS
  entry now moot. Alternatives researched (agent): top pick
  isaacphi/mcp-language-server (pyright), runner-up Serena; null option
  (Grep+tests+review) judged legitimate for this repo size — no adoption
  without Mike.
- Clarified for Mike: SKIPPED(no filter set)/n/a = filter not configured in
  this scan (hud default = macd_signal+volume_spike only), NOT unimplemented —
  all 7 gates are implemented.

## 2026-07-25b (Fable — SCAN-AUDIT-LOG shipped; rubric RATIFIED; keltner LOW closed)

- **Rubric adjudicated + RATIFIED** (prompts/rubric-thesis-v1.md): 5 categories
  kept, correlation_awareness scoped to ENGINE positions only (Mike's
  separate-theses answer); wound scale (minor/major/fatal) ADOPTED — pending
  its own spec'd migration batch (_rubric.py schema change); **threshold→2
  dial ABORTED by Mike same day** (feeling, not data) — default 1 stands,
  per-category + resolve-pass ideas PARKED. Policy hash untouched.
- **SCAN-AUDIT-LOG shipped** (design docs/design/SCAN-AUDIT-LOG.md; merges
  77d57d7 + 476fd6d, both GATE green): `scan(audit="off|on|exhaustive")` full
  lifecycle trace — bar head/tail + full sidecar CSVs, per-indicator formula +
  values (no-recompute invariant), GATE blocks (name/purpose/check/why/
  terminal/verdict), exhaustive = all-gates-open toggle (kill semantics
  unchanged). T-AUDIT-2 same day: `tk hud --audit on|exhaustive` +
  cp1252-safe console tee. Mike: run `tk hud --equity <x> --audit exhaustive`.
- Review round 13 (Opus reviewer, SHIP-AFTER-FIXES): caught HIGH dual-RSI tag
  drop in green's refactor + header fidelity degraded to appease a weak test
  — both fixed; scan_ts reverted to end-read; slash-sidecar pinned
  (ASSUMPTIONS 168-169; agent-metrics round 13).
- keltner/_ema deferred LOW closed (merge 7e72390): volatility._ema degenerate
  period now raises (was ZeroDivisionError/silent miscompute). Used Mike's
  stalled task-chip worktree (Cowork disk-check false-refusal: C: 99% but 12G
  free — git worktrees work fine).
- Tooling: tk-bootstrap cp1252 crash fixed (utf-8 reconfigure); GitNexus
  reindexed (v42 desync gone) but FTS still failing read-only-db (FRICTION,
  NOT SOLVED); worktree uv env pywinauto mypy false-red (FRICTION, workaround).
- NOT started: MTF-SCAN T-MTF-2..4; wound-scale migration batch; P4 promotion.

## 2026-07-25 (Fable — attrition telemetry PROVEN LIVE; P4 unblocked)

- Mike ran `tk hud --equity 4963.57` against prop. First real attrition log
  (data/scans/2026-07-25/scan-020850.log): `killer filter: macd_signal
  (11/11)` — ALL 11 pairs negative 4h MACD hist. S1 silence is HONEST (bearish
  universe, momentum-long finds nothing), NOT a bug. TICKET-001 fix confirmed
  working live. The day-one question is answered.
- **P4 UNBLOCKED**: Mike rotated both API key pairs, funded $50 live, answered
  rubric-thesis-v1 open Qs ([MIKE] tags). Needs CTO next session: adjudicate
  answers into the rubric (wound scale minor/major/fatal ADOPTED;
  unresolved_attack_threshold→2 = a POLICY DIAL change, money-path batch), then
  promotion→3 live trades (MVP done-gate).
- MTF-SCAN T-MTF-1 (limits.py retention pins) dispatched to isolated worktree
  — CTO review+merge pending. keltner/_ema guard: Mike's own worktree.
- Live-trade counsel: no valid S1 setup tonight (all-bearish); day-5 clock
  reset by 7/23 NEAR trade; don't force one. Seed:
  docs/handoff/HANDOFF-2026-07-25-attrition-proven-p4-unblocked.md.

## 2026-07-24 (Fable — SPRINT-AUDIT-BUNDLE SHIPPED; money-path fail-open dead)

- Batch 2 through the cycle: red 794e9e1 (14 tests; test-writer CAUGHT audit
  L3 as a false positive — CTO verified, P5 withdrawn, swarm adjudicator
  graded down) → green (kind Literal == _MUTATING single-source, sizing
  multiplier guard, correlation zero-variance→None+warnings, atr/ema period
  guards, _context ValueError narrowing) → implementer STOPPED correctly on
  mis-fixtured P6 (no SizingComputed → empty derived log) → CTO adjudicated
  semantics + fixed fixture → money-path review round 12 **ACCEPT** (0 HIGH/
  MED, 4 LOW: 3 folded by CTO, keltner/_ema guard spun off as task chip).
- Policy gate can no longer fail open: unknown action kinds are
  unrepresentable (pydantic) and every legal kind hits ≥1 rule (invariant
  test). Old ledgered events with bogus kinds now fail loud at deserialize.
- Schemas regenerated; commit includes pre-existing drift (RuleHit
  not_configured, TICKET-001 event types, 6 never-exported contracts) —
  source is authority, per reviewer recommendation.
- Grades: red A-, green A (metrics round 12). Gate green pre-commit.

## 2026-07-24 (Fable — TICKET-001 SHIPPED via full batch cycle; canon ratified+committed)

- Mike approved the standards plan; canon committed fa2a5a9 (GLOSSARY +
  ENGINEERING-CANON D1-D7 + CORE-FLOWS ratified). Reverted keyboard-mash in
  tests/conftest.py that had turned the gate red (accidental editor input).
- **TICKET-001 through the full cycle**: pins e398211 (ASSUMPTIONS 162-164) →
  red 8fb4b0c (23 tests incl. the S1-catching un-mocked contract test + the
  authorized :490 inversion) → green (963 passed; "bullish"→"bullish_cross",
  MacdSignal/BBPosition StrEnums, loud unknown-value raise before bar fetch,
  attrition telemetry scanner→HudState→log→ScanAttritionRecorded event) →
  review round 11 **FIX-FIRST** (HIGH: hud discarded scanner attrition,
  rendered collapsed "setup" killer — the ticket's own blindness reproduced;
  the gap was test-shaped first: under-pinned red let wrong green stay green)
  → fix round 5dbb3f1 + impl (splice real per-filter stages, equity in
  header, ASSUMPTIONS 163b/163c) → focused re-review **ACCEPT** (1 MED
  deviation: doubled bars stage vs 163b wording — CTO applied 2-line dedupe
  + assert directly, re-gated green).
- Grades (round 11): test-writer B-, implementer B, fix-round B. Carried LOW
  to batch 2: hud_scan ledger append unguarded (unadjudicated).
- Batch 2 (SPRINT-AUDIT-BUNDLE) pinned + adjudicated: kind Literal ==
  _MUTATING makes the all([]) fail-open unreachable by construction (no
  runtime guard, one invariant test); _context except-narrowing per auditor.
  Money-path review round mandatory. Dispatching next.

## 2026-07-24 (Fable — standards research + canon drafting, post-audit response)

- Mike's directive: research-grounded standards to stop the compounding
  error classes (vocab drift, silent seams, untested flows). 4 sonnet research
  agents dispatched (naming/vocab, readability, contract testing, behavior
  flows) → memos in docs/research/standards-2026-07/ with citations +
  [UNVERIFIED-RECALL] honesty flags.
- **Drafted for Mike sit-down (all DRAFT, not yet canon):**
  - docs/GLOSSARY.md — module-grouped vocab source of truth (DDD ubiquitous
    language; Term/Definition/Code-form/Aliases-to-avoid; "bullish" is banned
    alias #1). CLAUDE.md Conventions gained the consult-glossary imperative.
  - docs/design/CORE-FLOWS.md — 5 codified user flows w/ behind-the-scenes
    stages, user-facing gates, fail-info contracts, unhappy taxonomy U1-U6
    (wrong-context / silent-state / repeat-action / refused / abandoned /
    upstream-silence), sprint flow-review ritual. THE review deliverable.
  - docs/design/ENGINEERING-CANON.md — decisions D1-D7: glossary+enums first
    line of defense; seam-test policy (StrEnum/Literal + assert_never + one
    un-mocked producer→consumer contract test; money gates deny on unknown);
    readability = 12 anti-pattern rules + review dimension, NO line-count/
    comment-density metrics (evidence doesn't support them); tests/flows/
    meta-suite (plain pytest, no Gherkin; ~5 CUJs; in the gate); LLM-operator
    rehearsal v1 scoped to invariant-checked procedure-fuzzing; boundary-
    condition design duty + end-of-sprint interface-drift pass.
- Rollout order proposed in canon §Rollout: ratify → TICKET-001 → money-path
  audit bundle → flows M-F1/M-F2 → reviewer rubric → LLM rehearsal.
- Mike separately engaging Codex/GPT-5.6 as external TDD/security consultant
  (his hands; sol-brief already staged).

## 2026-07-23 (evening — first live trade attempt; S1 silence ROOT-CAUSED; Opus)

- **S1 silence is a one-word bug, not a market read.** `hud/_build.py`
  `_SETUP_FILTERS` ships `macd_signal="bullish"`, but `_scanner.py` accepts only
  `"bullish_cross"`/`"bearish_cross"` and sends everything else down an
  unconditional `else: return None` — so the momentum filter has been a
  guaranteed reject-all on every scan since the constant was written. Proven
  live: scan with "bullish" → 0 matches / 0 warnings (silent else path). The
  scanner docstring explicitly warned against the "bullish" spelling.
- **Compounding fact**: even corrected to "bullish_cross", 0 matches tonight —
  ALL 11 pairs have negative 4h MACD histograms (broad crypto weakness). S1
  (momentum-long) correctly finds nothing. Silence = broken AND correctly-quiet
  at once; telemetry is the only way to tell them apart. → TICKET-001.
- **TICKET-001 written** (docs/tickets/) — enum fix (raise loud on bad value,
  don't return None) + scan-attrition telemetry (per-stage pass/fail log +
  ledger note, Mike's format). Ships as one batch w/ CTO sign-off; strategy
  behavior change, honors seed red-line.
- **First live-trade attempt (day-5 inactivity rule)**: served real hud-ack loop
  (scripts/day5_manual_trade.py, seams ONLY the scan-preview policy — binding
  policy real). Adjudicated NEAR/USD long, ~$41, R-005/R-008/R-012 co-compliant.
  Prop account NET FLAT after the dust settled; realized −$36.43 ($5000→$4963.57).
  Loss anatomy: the 21.8-unit thesis trade lost ~$0.17; the $36 was a fat-finger
  4259.7-unit (2x-leveraged) take-profit-entered-as-BUY that had to be dumped at
  market. Strategy/sizing were fine; the margin UI was not.
- **Account-attribution trap**: the ~21.8 NEAR + OCO bracket Mike still holds is
  on his REAL/spot account (11:14 fill @1.8766), NOT prop. Prop is flat.
- **Money-path venue truth**: Kraken Prop has no working OSO/bracket flow;
  Kraken Desktop is unusable for entry (mobile-only henceforth); manual exits.
  OPERATIONS.md step 3 is WRONG. Logged to FRICTION.md.
- **HUD-ack UX bug**: Confirm/Failed fire silently (subtle glitch, no message)
  AND non-idempotently — Mike clicked repeatedly waiting for feedback; two
  `failed` acks landed at 18:20:53 from that. Server-side chain is fine
  (rehearsal + dry-run 204). Needs feedback + idempotency. Queued (not TICKET-001).
- **Two audits dispatched.** (1) Test-suite audit (Opus subagent) —
  docs/reviews/test-audit-2026-07-23.md: units strong, seams untested (suite
  mocks both sides of every inter-module contract); found
  test_scan_markets_verb.py:490 CODIFIES the macd silent-drop as correct (green
  because broken). Sol brief for external second opinion:
  test-audit-2026-07-23-sol-brief.md. (2) Gating/filter silent-failure swarm
  (Haiku sniffers → Sonnet adjudicators, background workflow) —
  docs/reviews/gating-filter-audit-2026-07-23.md: 58 chunks, 12 confirmed / 47
  cleared. HIGH money-path (CTO-verified): H2 `_sizing.py` unguarded
  `multiplier` → silent negative position size; H3 `policy/_evaluate.py:64`
  `all([])` fails OPEN on unrecognized action.kind. Systemic pattern: unknown
  input coerced to benign value instead of failing loud. Reports-only, no code
  applied (money-path red-line).
- Gate green @ fdc865f at session start (1000+ tests). No src changes committed
  this session — diagnosis + tickets + audits + scripts/day5_manual_trade.py only.

## 2026-07-23 (Fable returns — half-usage retention past 7/20)

- Resumed as CTO. Gate green @ 16a2cea (1000+ tests, 89 src files). Dirty tree
  classified + committed (f4ec577: GitNexus CLAUDE/AGENTS blocks, docs/hud/hud.html).
- **Diagnosis of "no results"**: ledger has ZERO AdvisoryTicketAcked and ZERO
  ThesisGraded events — the loop works, S1 has just never fired. Collector
  healthy (Mike). Remedy plan seeded: scan-attrition telemetry (measure WHICH
  filter kills candidates) -> tune-vs-replace decision -> MTF-SCAN + S2.
- Corrections: 7/20 handoff queue item 3 (T-PAGE-1) already done 7/19; ROADMAP
  "GitHub remote" box stale — remote exists and is pushed.
- New active seed: docs/handoff/HANDOFF-2026-07-23-fable-return-s1-silence.md
  (supersedes ops-ready seed as queue; its red lines/seams remain binding).
  CLAUDE.md Current focus updated.
## 2026-07-19 (Fable, last full session) — retention truth, MTF+strategy designs, PAXG probe, Sol skill

- **Pagination RESOLVED with truth** (red a7d6be2 -> green 715beca,
  ASSUMPTIONS 161): live probe proved Kraken OHLC RETAINS only the last
  720 candles/interval — pagination there is impossible, error message now
  says so with the interval ladder (1d~2y / 4h=120d / 1h=30d / 15m=7.5d).
  Alpaca got REAL page_token pagination (cap 20 pages, loud dup guard).
- **Delegation-ready designs** (Fable-pinned, zero open questions):
  docs/design/MTF-SCAN.md (retention pins in limits.py, scan_confluence
  verb, StrategyDef registry, T-MTF-1..4) and docs/design/STRATEGY-PACK.md
  (S2 pullback / S3 breakout / S4 restricted reversion — exact filters,
  new vocab ema_above + rsi_band with momentum-family rationale, build
  order, boundary pins, worked-example procedure).
- **PAXG probe RUN with real data** (docs/research/
  paxg-basis-probe-2026-07-19.md + experiments/paxg-basis/): 497d PAXG vs
  GC=F. Naive fade "96% win" exposed as artifact (timestamp skew, thin
  closes, futures roll); next-day entry collapses it to 0.65%/trade.
  Verdict: needs collector intraday data + spot-XAU feed before any bot.
  House lesson: EVERY strategy probe runs the next-period-entry check.
- **New skill ~/.claude/skills/tk-sol**: the Claude<->Sol seam protocol —
  brief format (6 required sections) outbound, claim-audit adjudication
  inbound. Sol designs; the house pipeline ratifies.

## 2026-07-19 (Fable, day 3 finale) — hud-ack shipped; loop rehearsed; ops codified

- **hud-ack** (spec -> red e9c0fa9 -> green 6daf171, ASSUMPTIONS 160):
  `tk hud --serve` = live HUD + POST /ack. Confirm click = BINDING chain
  (thesis draft->submit->ReviewCompleted(human confirm)->approve -> fresh
  policy verdict -> AdvisoryTicketAcked); policy refusal at click = 409
  STOP (never send stale orders); Failed books technical failure only.
- **Dress rehearsal PASSED** (scripts/rehearse_hud_ack.py, temp ledger):
  full event chain + verify_chain OK. Steps 1-3 of the first-trade path
  are done; what remains is a real ticket + Mike's hands.
- **Codified for successor models**: docs/OPERATIONS.md (daily loop,
  cadence=<=2x/day after 4h closes, day-5 inactivity rule),
  docs/design/STRATEGY-BACKLOG.md (S1 live; S2 pullback-continuation
  first fallback; S3 breakout; S4 restricted reversion; MS-PAXG-1 basis
  research plan), HANDOFF-2026-07-20-ops-ready.md (GPT/Codex/lower-tier
  seam).
- UI aesthetic parked per Mike ("80's vibe") — Claude Design later.

## 2026-07-19 (Fable, day 3 close) — merge to main; HUD polish sprint

- Merged feature/bridge-read + feature/hud-orderbook to main (4302f6c, one
  merge — bridge-read was an ancestor); branches deleted local+remote.
  README rewritten to current state. Mike's CLAUDE.md edits committed.
- Fixed missing limit prices: Kraken pair map lacked RENDER/PAXG/XRP/AVAX/
  AKT (XRP legacy XXRPZUSD result key, live-verified). All 11 greenlist
  symbols now scan clean, zero provider errors.
- Palette v2 "twilight upon the parking lot" (spec addendum 2): carbon/
  tungsten/graphite surfaces, neon #ff7a1a thin / burnt #c1581f thick,
  #ffb25e sodium-lamp radial falloff in the title bar. tk hud --open
  (AC-14) + success confirmation line on stdout.
- T-PAGE-1 pagination backlog logged (cursor-based, since-semantics trap).
  HUD-ACK designed (serve mode, confirm/failed buttons, no veto button —
  bot experience preserved); spec+implement = next session's first batch.
- .claude/.codex gitignored. Gate green throughout.

## 2026-07-19 (Fable, day 3 cont.) — T5 real funnel wiring; tk hud LIVE

- **T5 shipped** (red e8728f9 -> green 2c7c3c6 -> fix c15d6ba): sizing seam
  -> sizing_info (one real mae.size_position call powers qty 8dp ROUND_DOWN
  + ATR bracket SL=limit-stop, TP=limit+2R); scan_setup seam (real
  scan_markets, macd_bullish+volume_spike 1.5, regime-gated); gate order
  open-position -> data_integrity -> setup -> sizing -> policy_verdict;
  CLI --equity required (never guess account equity). ASSUMPTIONS 159.
- **Smoke-tested against live Kraken**: first run caught ProviderRangeError
  (1h x 90d scan = 2160 bars > 720 OHLC cap) -> setup scan moved to 4h
  (540 bars, doctrine-consistent); provider errors in scan/sizing now
  degrade to failed gates per error map. Second run clean: LINK+ETH graded
  wait (no confirmed setup right now — honest), placeholder rendered.
- tk hud is now PRODUCTION-USABLE: `uv run tk hud --equity 5000` emits the
  full advisory HUD. Remaining before first prop trade: thesis provenance
  (tickets carry interim-thesis ids), sell-side emissions, review round.

## 2026-07-19 (Fable, day 3) — hud-orderbook shipped T1-T4 (design a85053c -> green fa0d3e4)

- **Pivot executed**: post-UIA-grade-C, built the advisory HUD per handoff.
  Design/spec/tasks committed (static HTML render target chosen over
  FastAPI/Textual); AC-1..10; T1-T5.
- **Batch 1 (contracts + render + build_state)**: red 2525531, green e9805da,
  CTO fix round d9ef3f8 REJECTED implementer's NotImplementedError-as-success
  sentinel + hardcoded proposal fixture (fabricated advisory numbers = money
  hazard) -> real BarSeries fixtures, third sanctioned seam size_qty with
  LOUD default (ASSUMPTIONS 158). Review round 10 ACCEPT w/ fixes (be70f94):
  tab-count assertion, exception-path test, interim-provenance warning on
  tickets, gate-reason fidelity.
- **Batch 2 (tk hud CLI)**: red 8c6ef7d, green fa0d3e4. Implementer correctly
  STOPPED on pytest basename collision (test_cli.py x2) instead of hacking
  import mode; CTO renamed to test_hud_cli.py. Atomic temp+replace write,
  exit 4, clock via mae._runtime only.
- **Known intended limitation**: production `tk hud` fails loud until T5
  (real sizing/funnel wiring) — no fabricated quantities on the surface Mike
  transcribes into the prop account. T5 is next session's first batch, then
  the one compliant inactivity-clock trade.
- Gate green at a4e2d6d (890+ tests). Collector confirmed live (hour-14
  parquet growing).

## 2026-07-19 (Fable, night 2) — P5-PROP batch A shipped (red 4343b0b -> green 1c4cb14)

- **ASSUMPTIONS round-26 (143-153)**: all four sprint-flagged ambiguities
  ratified + red/review pins: balance-snapshot MDL, equality=breach
  anti-permissive (documented asymmetry vs R-017/R-018 allow-at-boundary),
  static MDD, funding at 4h UTC marks exclusive-both-ends, cent
  HALF_EVEN per application, independent parametric draws, zero-edge
  log-space envelope 0.3936, risk ladder + monthly ruin normalization,
  scripted-granularity limitation, 2bps basis placeholder, horizon
  guard, exclusive 00:30 boundary.
- **Shipped**: contracts._prop (spec/result/trade-model union),
  prop.simulate_evaluation (scripted Decimal ledger + parametric numpy
  MC), policy prop dial block + prop_account_walls (0.021/0.036).
  35 new tests incl. cent-exact goldens (CTO re-derived independently:
  5036.80/5035.84/4974.46 confirmed pre-freeze). 793 green.
- **Review round (money-path, pre-registered focus boundary/reset)**:
  FIX-FIRST — 2 MED (horizon-span leak -> ValueError; 00:30-equality
  docstring/impl mismatch -> pinned exclusive + golden), 4 LOW (floors
  now compared unquantized; tie->mdl pinned; fee-kernel lift deferred
  to batch B; walls hygiene fixed). Grades: implementer A-, test suite A-.
- **Friction x2**: commit_gate.py lacked the (red) exemption (fixed);
  read-dedupe hook false-positives on subagent first-reads (NOT SOLVED).
- Open into batch B: R-017/R-018 PolicyContext wiring for prop:*
  accounts; EmpiricalTradeModel pin; fee kernel -> CostModel single canon.

## 2026-07-19 (Fable, late) — Prop recon complete; SPRINT-P5-PROP designed

- **Prop API hunt CLOSED (negative)**: Pro key sees main wallet only;
  Prop settings page has no API section (Mike-confirmed in UI); zero
  PROP pairs in public spot/futures APIs; docs/llms.txt has no Prop
  surface. Support ticket pending (API access + stop persistence).
- **Kraken Desktop recon (computer-use, read tier)**: Prop board =
  separate "XXX PROP" instrument suite (BTC/ETH/NEAR/LINK/... PROP),
  order ticket routes via Accounts selector ("Starter Eval 1");
  panel confirms $5,000 / MDL $150 / MDD $300 / target $500; ETH
  spot-vs-PROP basis ~2bps observed. Claude = read-only observer
  (harness tier + policy: never executes trades); executor = Mike or
  Codex via future execution bridge.
- **SPRINT-P5-PROP authored** (docs/handoff/SPRINT-P5-PROP.md): M5.1
  prop dials + barrier Monte Carlo (headline: recommended_max_risk_frac);
  M5.2 backtest/walk-forward engine (absorbs M1.3 box; StrategySpec in
  scanner vocabulary, experiment registry starts, Kraken data ingest);
  M5.3 execution bridge/HUD; M5.4 strategy #1. ROADMAP P5-PROP section
  added; memory updated. Open flags listed in sprint doc §ASSUMPTIONS.

## 2026-07-19 (Fable) — Prop-strategy questionnaire answered (CTO), Kraken GO verdict

- **Answered GPT 5.6 Sol's 378-question prop-strategy discovery sheet**:
  docs/research/prop-questionnaire-answers-CTO-2026-07-18.md. Anchors GPT
  to the built substrate (BUILT markers), flags MIKE-only items, defers
  venue facts to Report 1. Key calls: survival-first priority order,
  pullback-continuation+breakout first family, 4h/1h/15m MTF, LLM
  deny-only + P&L-blinded, risk ladder 0.05→0.10→0.15%, no manual trades
  in system account, "tradekit Substrate Contract" doc inserted into the
  design sequence (GPT adopted all of it).
- **Kraken Prop Report 1 verdict: GO with conditions** (Mike's deep
  research): automation explicitly permitted, WA/US eligible, MDL = 3% of
  BALANCE recalc'd daily 00:30 UTC, MDD static lifetime off starting
  balance, breach detection on real-time EQUITY. Unconfirmed →
  SUPERVISED_LIVE-gated: Prop API key scoping, stop persistence through
  disconnect, full Prop ToS text. Contingency if no API: advisory-HUD
  mode (Mike executes, app simulates from synced fills).
- Gate: green (19127d3 baseline, 758 passed).

## 2026-07-19 (Fable) — Test audit + garbage removal; tk-stack Phase 1 wiring

- **Test-quality audit** (6-agent rubric sweep, all 683 fns): Mike's garbage-test
  suspicion largely REFUTED — ~85-90% protective, zero mock-theater. Report:
  docs/reviews/test-audit-2026-07-18.md (verdict + gap backlog, gaps > garbage).
- **Garbage removal executed** (sonnet agent, CTO re-gated): 824→758 collected (−66,
  mostly pydantic-mechanics sweeps → one inheritance pin each). pnl_snapshot
  tautology rewritten to a real lifecycle test (exposed that projections are
  rebuild-derived, not append-applied). broker_port conformance now seeds real
  fills/positions; ManualBroker exemption documented (AdvisoryOnly by design).
  No src/ changes. Gate: green (758 passed, ruff clean, mypy clean).
- **tk-stack Phase 1 live**: tk-gate (canonical gate verdict + .tk/gate-last.json),
  tk-bootstrap (SessionStart hook: seed/dev-log/roadmap/gate-freshness/recovery
  classification), tk-friction (docs/FRICTION.md logger). Project CLAUDE.md (gate
  line, red lines, doc inventory) + AGENTS.md (Codex/Gemini) added. Global skills
  purge: 57 gstack skills archived, gstack.bak deleted; tk- suite design at
  ~/.claude/tk-stack/DESIGN.md.
- Exemplar subagent prompts + TDD examples library harvested to
  ~/.claude/tk-stack/references/ (feeds future tk-tdd/tk-implement).

## 2026-07-18 (Fable) — P4-PAPER COMPLETE: AlpacaBroker dress rehearsal + seam hardening

- Scope per Mike: "P4, paper only." Live remains structurally unreachable
  behind FOUR independent locks: live_trading_enabled dial (default false) +
  ALPACA_LIVE_KEY env absence + two-man promotion + live_path manual-resume.
- **AlpacaBroker** (real trading API, paper base): five port methods, shared
  _tokens verifier FIRST (submit-time halt seam closed for every adapter),
  no-creds = LOUD everywhere (fabricated read-verb defaults REJECTED at the
  CTO gate — the conformance harness owns its environmental setup instead),
  venue error taxonomy (404-on-order_status is the one typed venue answer;
  5xx/429/timeout/malformed RAISE VenueUnavailable — never fabricate a
  status; landed same-day off review round 7's MED, pre-live).
- **Process upgrade (Mike's note): fixtures from REALITY FIRST** — CTO
  probed the live paper API before any test authoring (docs/research/
  alpaca-paper-shapes-2026-07-18.json); zero fixture-vs-reality divergences
  all sprint (first sprint with none). Two ~$10 BTC probe/rehearsal
  positions remain in Mike's Alpaca paper account.
- **Live dress rehearsal PASSED via the real adapter**: submit→open→filled→
  activity-fill (costs-model fees)→account state, scripts/smoke_alpaca_paper.py.
- **Seam hardening**: HaltSetPayload.live_path (narrow reading — agent's
  argument beat the CTO's initial lean; procedural pin covers the residual),
  resume(confirm_live)/`tk policy resume --live-confirm`, Popen streaming
  flood-kill (proven early, not timeout), ring-3 seam scenarios (submit-time
  halt + token×demotion new-green against batch-A machinery).
- Orchestration per Mike's note: every dispatch backgrounded + wakeup
  ladder; no blocking waits; Codex fallback doc refreshed evergreen
  (CODEX-HANDOFF-CURRENT.md).
- **Review round 7 (Opus): PASS** (probes incl. secret-scan of the tracked
  tree — zero hits; flood-kill timed; mutation-reasoning on scenarios). The
  MED (HTTP taxonomy) fixed same-day with per-failure-mode proven reds.
- **Final: 824 tests green, ruff clean, mypy clean.** agent-metrics round 7.
- P4-LIVE remains Mike-gated: rotate BOTH chat-pasted key pairs, create live
  keys + fund $50-100, approve prompts/rubric-thesis-v1.md. SESSION-SEED-P4
  updated (rehearsal marked done; procedural no-agent-resume pin).

## 2026-07-17/18 (Fable) — P3 paper trading/review/reporting COMPLETE (M3.1-M3.3*)

- *Open deferrals, all Mike-paired or Mike-blocked: rubric-thesis-v1.md DRAFT
  awaits his approval; research-loop prompts (D14) = paired session; Kraken
  read-only balance tracking = his key rotation; $5k/$5k seed distribution =
  his long-term thesis content; derivatives provider stays deprioritized.
- **P2 rules sign-off closed first**: Mike confirmed with amendments → TD-24
  (per-account dial layering: percent-of-principal position/exposure dials,
  AccountConfig contract with prop-style slots, None=disabled; R-008 min
  notional stays absolute — fee-floor exception he accepted).
- **The full paper pipeline is live**: BrokerPort + conformance suite;
  PaperBroker (event-sourced accounts, deterministic mid±spread fills with
  quote snapshots, G5 through-by-tick limits, REAL ledger token verification
  with thesis binding + no-newer-deny); execute_order two-phase pipeline
  (§8.2 ordering guarantee: intent → verdict → broker, deny leaves zero
  Order* events); reconcile BOTH directions → auto-HaltSet; review module
  (LLMReviewerPort, subprocess adapters with caps, deterministic rubric,
  zero-token auto-fail short-circuits, void_signoff emission closing the P2
  debt); ManualBroker/advisory + tk fill record (never refuses, ledgers
  GateViolationDetected under lockouts — F7's teeth); memory (brief with
  hard token cap + salience truncation, search AND/phrase, wiki, lessons);
  report (memo/readiness/pnl); ledger.models accessors; SeriesClosed
  emission; strategy-tag registry (57f debt closed). TD-24 landed:
  create-paper-account, R-017/R-018 with not_configured audit hits,
  evaluate hardened to an outcome ALLOWLIST (unknown values fail closed).
- **Done-gate green**: tests/replay/test_p3_end_to_end.py — scan → thesis →
  review (fake adapter) → gates → order → paper fill → grade PASS with pnl →
  memo/brief → byte-identical projection rebuild → chain verify.
- **In-sprint catches**: dev-p3-d found a LATENT P2 bug (void() never checked
  `passed` on sign-offs — a FAILED review would have permitted a void);
  delayed-fuse macro tests (fixed dates + real clock) — new standing rule;
  report-path litter; token-verification pull-forward when the conformance
  suite proved the shape-only seam wrong. live:→PaperBroker routing is
  EXPLICITLY TEMPORARY (P4 replaces + pins).
- **Review round 6 (Opus): FIX-FIRST, zero HIGH (streak broken), 3 MED**:
  halt-bypass via resting-limit polling (order_status now halt-gated);
  token gate narrower than its pin (thesis binding + no-newer-deny landed);
  one-directional reconcile (phantom-ledger-fill direction added). Fixes
  3f207d9→425f000. agent-metrics round 6.
- **Final: 781 tests green, ruff clean, mypy clean (71 src files).**
- Next: P4 (live proof — every step pairs with Mike; needs BOTH key
  rotations + Alpaca live keys + $50-100). Seed: SESSION-SEED-P4.md.

## 2026-07-17 (Fable) — P2 thesis lifecycle + policy engine COMPLETE (M2.1, M2.2)*

- *One open DoD item: **Mike's sign-off on rules/RULES.md WHYs + config.toml dials**
  — requested, pending his reply. Everything else done.
- **The spine and the gates are live.** tradekit.thesis: draft/submit/approve/
  reject/grade/void, event-sourced, guarded (state,event)→state transitions,
  submit = validate-everything-then-append (snapshot → sizing → marker), EV
  Decimal tolerance $0.01, quantized predicate resolution. tradekit.policy:
  R-001..R-016 declarative registry + WHYs, pure byte-identical evaluate with
  deny-never-silent ledgering, dials via pydantic-settings config.toml,
  policy-version hashing, halt/resume, series accounting (per-account, 30-day
  calendar blocks), T1→T2 promotion machine with two-man confirm + demotion,
  R-016 wired to real compute_strategy_metrics. rules/RULES.md generated.
  13+ typed event payload models; theses/series/promotion_state/pnl_daily
  projections, rebuild-idempotent and log-pure.
- **Five batches, four-stage each** (addendum 23c3897): A lifecycle (0ae41bb→
  8159b2c), B grade/void (598e439→c434362), C policy (b8e0d5e→7f4c241), D
  series/promotion (101288d→f6c147b), E adversarial suite (acf478c). ~30
  flagged design calls adjudicated in ASSUMPTIONS 58-97 (highlights: pnl None
  never fabricated-zero; void sign-off = ReviewCompleted kind=void_signoff;
  read-verb-that-writes for promotion_status; edge_verdict positive-only).
- **In-sprint CTO catches**: batch-A's unguarded transition map (any stray
  ReviewCompleted could corrupt state — found by batch-B TDD, fixed batch B);
  batch-C dev's permissive fallback that let FABRICATED thesis_ids pass
  R-010/R-012 (rejected; fixture made to earn its allow; two deny pins).
- **Done-gate: 11 adversarial replay scenarios (Opus-authored), all §15 gates
  held** — VOID-farm, micro-series, cherry-pick, revenge-size, drawdown incl.
  advisory, kill switch, fabricated-id, refused-void, tamper evidence.
- **Review round (Opus, FIX-FIRST)**: HIGH — series MDD equity base pooled ALL
  accounts (winning sibling dilutes a loser's drawdown → dirty series grades
  clean → promotion opens); both derivations shared the bug so their agreement
  pin passed. Fixed with a discriminating two-account fixture (0.0788 falsely
  clean → 0.1733 dirty). MED: projection completeness now log-relative (max
  event ts, pure rebuild). 2 LOW. Fixes be4a8a8→5b547be. agent-metrics #5.
- Codex tag-team scaffolding landed mid-sprint (docs/handoff/CODEX-HANDOFF-
  2026-07-17.md + docs/research/codex-brief.md, anchor then 101288d) — unused
  this shift (Mike upgraded the plan; Fable finished the sprint), stays as the
  off-hours fallback pattern.
- **Final: 594 tests green, ruff clean, mypy clean.**
- Next: SPRINT-P3 (broker/paper trading/review/reporting). P3 owes: review
  module emits ReviewCompleted incl. void_signoff; FillRecorded typed payload
  + fill-time pnl attribution; live-tier context wiring (fail-closed till
  then); SeriesClosed event; ledger.models read accessors; strategy-tag
  registry re-derivation (ASSUMPTIONS 57f).

## 2026-07-16/17 (Fable) — P1C regime/scanner/sizing/correlation COMPLETE (M1.4, M1.5, P1 done)

- **All four remaining MAE verbs live**: size_position (wired over frozen _sizing),
  get_correlation_matrix, get_regime (HMM + EWMA override + rules fallback),
  scan_markets. Plus story 0 (Mike-approved): yfinance macro provider (never-raise
  degradation, ASSUMPTIONS 46) — closes M1.1's last box. Deps: yfinance 1.5.1,
  pandas 3.0.3, hmmlearn 0.3.3, scipy 1.18.0 — all mae/-internal.
- **The sprint's one new design**: `mae/_runtime.py` ambient data seam (verb
  signatures are pinned portless) — clock/provider-factory/cache-path indirections,
  "/" routing (Kraken vs Alpaca), and THE lookahead chokepoint: get_closed_bars
  strips the live bar so no verb can ever leak an unclosed candle downstream.
- **Three batches, four-stage each** (addendum 6e8b8a9): A = macro+runtime+sizing+
  correlation (030a520→faaa151); B = regime (a41f352→3974493); C = scanner+
  get_closed_bars+smoke (a9ea52d→5711bac). Schema ambiguities escalated by TDD
  agents and CTO-ratified in ASSUMPTIONS 47/51-54/57 (incl. "neutral" as a
  rules-only fourth regime state = anti-permissive default).
- **CTO-gate catches (pre-review)**: batch-A runtime test wrote fixture bars through
  the REAL data/cache.db (closed bars never invalidate → poisoned real scans; six
  fake rows purged, _cache_path seam added — standing rule: every file-writer gets
  a path seam); live smoke_scan crashed on Kraken pair-map gaps → Mike's universe
  (SOL/LINK/NEAR/TAO/EIGEN) mapped, result keys verified against the live endpoint.
- **Review round (Opus, verdict FIX-FIRST — the pre-registered override gate paid
  off)**: HIGH — EWMA override used the POOLED vol mean instead of the calmest
  state's emission mean (threshold ~4.8x inflated → under-fires exactly when vol
  explodes); invisible to the 0.25-spike test which cleared either threshold; fixed
  with a discriminating marginal-spike test (fails on pooled, passes on emission
  mean, proved both directions). MED: 3 uncovered scanner filter branches (now 7 new
  pinning tests). LOWs: macro degraded-path could still raise; monitor-less HMM
  defaulted to converged. Fixes e988c01→b4885a1. Round details agent-metrics #4.
- Composio spike (D17): verdict NO for data/broker core, MAYBE for P3+ reporting
  side-channels — docs/research/composio-spike.md.
- Alpaca PAPER keys landed in .env (account PA3YTZDZ9SXE, verified vs live data API,
  IEX feed). Two dev agents died at usage caps mid-task; both recovered cleanly
  (work was already on disk — check git status + pytest before assuming loss).
- **Final: 338 tests green, ruff clean, mypy clean. P1 (MAE core) COMPLETE.**
  Live: smoke_scan returns 3 real matches (ETH/SOL/LINK dailies via Kraken).
- Next: SPRINT-P2 (thesis lifecycle + policy engine). Note for P2: walk-forward
  evaluator (M1.3 leftover) lands with the backtest engine; strategy-tag registry
  should re-derive _scanner._TAG_STRATEGY/_regime._STRATEGY_TAGS (ASSUMPTIONS 57f).

## 2026-07-15 (Fable) — P1B indicators + golden vectors COMPLETE (M1.2)

- **17 indicators** in `mae/_indicators/{volatility,momentum,trend,volume,structure}.py`,
  pure functions, uniform None-alignment contract, signatures/lookbacks pinned by a
  CTO addendum in the sprint doc (31efe59) BEFORE dispatch. numpy added (stays in mae/).
- **Golden-vector freeze gate (the sprint's point, new process):** TDD agents derived
  vectors via independent from-spec scripts (pandas_ta rejected — its adjust=False
  seeding contradicts the pinned SMA-seed Wilder/EMA convention); CTO then verified
  every value with a SECOND independent implementation + TA-Lib 0.7.0 external
  cross-check (throwaway venv) before committing red. Exact TA-Lib matches: sma, ema,
  rsi, roc, bollinger, TR[1:], macd-line-via-EMAs, obv (modulo pinned obv[0]=0), DI/ADX
  divergences hand-reproduced as TA-Lib's 1..13-seed quirk. ASSUMPTIONS 39-43; vectors
  now FROZEN (regeneration requires redoing the gate).
- **Four-stage workflow, two batches:** tdd-p1b → dev-p1b (stories 1-3, c5e101a →
  08fcf70); tdd-p1b-2 → dev-p1b-2 (stories 4-5, 08cc8f7 → 61fb78a). All Sonnet.
  One dev defect, caught by the frozen goldens pre-commit: ADX Wilder smoother seeded
  with the SUM under the average-form recurrence (invisible at seed index — ratio of
  sums == ratio of averages — divergent after); dev-p1b initially blamed the golden,
  STOPped correctly, fixed on CTO push-back with exact arithmetic. Commandment 4's
  record intact. (Agent also died at a usage cap mid-fix; fix had already landed.)
- **Review round (Opus): verdict PASS — first zero-HIGH round in three sprints.**
  Reviewer independently recomputed 11 indicators against the goldens. 3 LOW fixed
  same-day (e519719): QFL gloss, degenerate-param guards (period<1/k<1 now ValueError),
  close-out items. Details in docs/reviews/agent-metrics.md round 3.
- CVD deferred to P3 (tick trades); CTO pins of record: supertrend initial direction
  (ASSUMPTIONS 41), ADX seed window (40), vwap UTC-day anchor + qfl same-bar crack (43).
- **Final: 258 tests green, ruff clean, mypy clean.** ROADMAP M1.2 all boxes checked.
- Next: SPRINT-P1C (regime/scanner/sizing — needs hmmlearn + the deferred yfinance
  macro provider decision). Mike's hands: still only the optional Alpaca paper keys.

## 2026-07-14/15 (Fable) — P1A data layer COMPLETE (stories 3-8 + review round)

- Keys landed: CoinGecko demo + Kraken read-only in `.env` (gitignored; CoinGecko
  verified live). Kraken key was pasted in chat — consider rotating before P3 live use.
- **Four-stage workflow, two rounds**: tdd-p1a (Sonnet) → dev-p1a (Sonnet) for stories
  3-5 (cache/Kraken/ratelimit, commits 7643c29→70121e9); tdd-p1a-2 → dev-p1a-2 (both
  Sonnet) for 6-8 (Alpaca/CoinGecko/conformance + live smoke, d051db2→e85e083).
- **Review round (Opus, verdict FIX-FIRST — third round running with HIGH catches):**
  H1 Alpaca crypto endpoint is multi-symbol (`bars` keyed by symbol) — flat-list mock
  hid a live-API crash; H2 ratelimit module was an orphan (nothing called it); M3 4xx
  mistyped as ProviderUnavailable; M4 malformed-200 bodies raised untyped; M5 cache was
  write-only whenever a live bar was in range (i.e. always, in production). Fix agent
  (Sonnet, fix-p1a; survived a usage-cap interruption mid-task and was resumed from
  transcript) landed red 48c5bdd → green 3fae4c9. ASSUMPTIONS 27-38 added across rounds.
- Ratelimit now wired: providers take injected clock/sleeper, token bucket + retry on
  every call; 4xx never retries; timeouts retry. Cache serves cached closed prefix and
  fetches only the uncovered suffix. Smoke re-run live post-wiring: 720x 1h BTC bars OK.
- **Final: 178 tests green, ruff clean, mypy clean.** M1.1 boxes checked except
  yfinance macro provider (deferred per sprint doc; revisit at P1C).
- Next: SPRINT-P1B indicators + golden vectors. Mike's hands: Alpaca PAPER keys
  (app.alpaca.markets) into .env as ALPACA_API_KEY_ID/ALPACA_API_SECRET when convenient
  (needed for Alpaca live smoke; tests don't need them).

## 2026-07-13 (Fable) — candlerl experiment: vision pattern classifier + PPO trader

- **New isolated sub-project `experiments/candlerl/`** (own uv env, py3.11, torch 2.11
  cu128 — RTX 5060 Ti/Blackwell works). Two decoupled models per the hierarchical
  master/slave plan Mike supplied: rendered 32-bar chart (128px) → CNN (11-pattern
  multi-label + 3-class 5-bar direction heads) → precomputed per-bar vision vectors +
  25 numeric indicators → SB3 PPO {flat,long,short}, reward = pos·logret − 10 bps·turnover.
- **Key finding (the expensive lesson)**: TA-Lib-style pattern labels are NOT learnable
  from images unless computed on **pixel-grid-quantized** prices — sub-pixel thresholds
  put identical-looking charts in different classes (macro-F1 0.34). After quantization +
  per-class val-calibrated thresholds: test macro-F1 0.46 — doji 0.87/engulfing 0.76-0.78
  strong, hammer family ~0.45 (relational judgments vs trailing averages), 3-candle stars
  weak (val support 9-47). Improvement paths in HANDOFF B8.
- **RL round 1 churned** (0.76 flips/bar → −38% cost drag, −21.6% mean vs +94.5% B&H on
  2024→2026 test). Round 2: training cost 25 bps (eval stays 10), ent_coef 0.001, γ 0.99.
- Rule-based detectors verified against TA-Lib C source (research agent); Stooq keyless
  daily data (22 tickers, 136.6k bars); leak-safe chrono splits with HORIZON embargo;
  43 tests green (TDD), review-agent pass fixed truncated-vs-terminated PPO bias + 6 more.
- CLI: fetch/build/train-vision/bridge/train-rl/evaluate/demo/predict (--ticker/--csv/
  --image). Paper suggestions only. README + HANDOFF.md (backlog B1–B9) for successors.

## 2026-07-12 (Fable bonus hour) — grading engine core, sizing math, cost model

- **Grading engine** (`thesis/_grading.evaluate_criteria`, P2 story-2 core, pre-built): pure arithmetic per DESIGN §10.2 with every ambiguity resolved against the agent — same-bar priority failure > invalidation > success (VOID can't erase a loss), stop-first on stop+target bars, lookahead guard inside the engine, per-predicate `by` deadlines never resurrect, time_expiry fires at deadline (an inverted-logic bug I caught pre-commit and pinned with a test). 12 tests. MVP constraint: one timeframe per thesis (ASSUMPTIONS 24).
- **Sizing math** (`mae/_sizing.py`, P1C story-1 core): Kelly with negative-edge clamp + ATR position identity (stopped out = lose exactly risk_usd). My own first golden vector was wrong by 3e-5 — re-derived by exact fractions (f* = .574 − 71/262); implementation was right. Canonical doc's 0.2102 example remains wrong.
- **Cost model** (`tradekit.costs`, P1A story-2): TD-8 shared friction tables (Alpaca equity/crypto, Kraken crypto), slippage-free under $100, unknown venues die loudly. Provisional until P4 live fills (ASSUMPTIONS 26).
- **Contracts**: Bar (OHLC-coherence validator), BarSeries (strict ascending), Friction, CriteriaOutcome, TIMEFRAME_SECONDS — P1A story-1 done. 28 schemas exported.
- ASSUMPTIONS 23–26 added (incl. the temporary internal-test exception — re-point + TID251-ban when verbs land). Sprint docs P1A/P1C/P2 updated with DONE markers. **Final: 108 tests green, ruff + mypy clean.**

## 2026-07-12 (final Fable session) — metrics core + full handoff package

- **Fairy-godmother handoff**: Fable 5 access ending; project handed to Opus/Sonnet/Haiku.
- Pulled M1.3 forward and completed it personally (the math most likely to be silently botched): `mae.compute_strategy_metrics` — pnl/win-rate/expectancy/PF, trade-level Sharpe+Sortino with pinned annualization convention (√(trades/yr) over log span), drawdown vs peak equity, Calmar, in-house Bailey–López de Prado PSR/DSR with n_trials selection penalty, G1 regime (DSR n≥30 / penalized 10–29 / descriptive <10), deterministic edge_verdict table. Conventions BINDING via `_metrics.py` docstring + 10 hand-derived golden-vector tests. `TradeRecord`/`StrategyMetrics` contracts added (24 schemas). **83 tests green, ruff+mypy clean.**
- Wrote **README.md** (setup, usage, current capability) and the **handoff package** in `docs/handoff/`: HANDOFF-PRIMER (ten working rules, model role assignments, state of world, known traps, session bootstrap checklist) + sprint docs P1A (data layer + costs), P1B (indicators + golden vectors), P1C (regime/scanner/sizing — incl. hand-derived Kelly vectors; canonical doc's example arithmetic is WRONG, ours is right), P2 (thesis/policy — Opus-required stories flagged), P3–P4 (paper→live).
- Remaining Mike's-hands: GitHub remote (URGENT — no offsite backup), CoinGecko key, Kraken read-only key (P3), Alpaca live keys (P4 only).
- Successor sessions start at HANDOFF-PRIMER §6 bootstrap checklist. Active sprint: **P1A**.

## 2026-07-12 (evening) — git init; ROADMAP; P0 COMPLETE (done-gate met)

- `git init` on main; baseline commit of doc set. `.gitignore` hardened (.env, data/, *.db never committable); `.gitattributes` normalizes line endings.
- **ROADMAP.md** written (P0–P5, milestone/story checkboxes, done-gates per phase).
- **P0 built via the four-stage workflow**: CTO pinned interfaces → TDD team (agent tdd-p0) wrote 38 failing tests + 19 ratified ASSUMPTIONS → dev team (dev-p0) implemented contracts + ledger to green → reviewer (reviewer-p0) verdict FIX-FIRST with 9 defects, all verified by execution.
- Notable review catches: **D1 quantize matched tick exponent, not grid** (0.05/0.5/5 ticks passed through un-quantized — falsified the G2 guarantee); D2 naive datetimes read as machine-local time in query bounds; D3 hash-preimage delimiter forgeable via control chars in identity fields; D5 the deep-module lint wasn't actually enforcing. All fixed by CTO same session; enforcement probe-verified. Agent metrics started at docs/reviews/agent-metrics.md (tdd-p0: B+, dev-p0: B).
- M0.4: `tk schema export` (22 schemas → docs/schemas/), `tk ledger verify|rebuild|query`, P0 replay done-gate test. **Final: 73 tests green, ruff clean, mypy clean (strict flags on contracts/ledger), real-CLI smoke `chain OK`.**
- ASSUMPTIONS.md now 22 items (20–22 added in fix round). Commits: 7f37184 → 7768e74 → d446ffb (red) → 5f93f15 (green) → c31cbf1 (fixes) → this.
- Next: P1 MAE core (data layer first — Kraken needs no key; CoinGecko demo key is Mike's remaining hands-item, plus creating the GitHub remote for first CI run).

## 2026-07-12 (later) — Adversarial review incorporated; DESIGN.md → v0.2

- Mike approved all v0.1 decisions incl. the three §18 asks (TD-10 promotion tightening, $25 live cap, advisory cooling-off). Confirmed rolling our own paper engine; futures *signals* deprioritized below stocks/crypto (we never trade futures — it's positioning data for spot theses); options = "maybe, later" → P5+ deferred list.
- Gemini adversarial review (Codex usage-capped) archived verbatim with dispositions at `docs/research/gemini-adversarial-review.md` (G1–G6).
- Accepted: G1 DSR gates only at n≥30/strategy, provisional penalized-Sharpe regime below (TD-14); G2 tick-size `quantize` at MAE boundary (new TD-23); G3 EWMA 3σ vol override on stale HMM (TD-13); G5 limit fills need trade-through ≥1 tick; G6 derivatives chain = Kraken Futures → Coinalyze → Binance, implementation → P3.
- **Partially rejected G4** (in-process write queue): wrong topology — tradekit is many short-lived CLI processes, not one threaded process. Kept: bounded retry-with-jitter on `append`; scouts write wiki files, not events. Escalation stays the Phase-2 daemon (TD-16).
- All three former Perplexity questions (Q1–Q3) resolved by the review; none open.
- Answered Gemini's closing question by specifying correlation methodology in DESIGN §9.1 (30d Pearson, daily log-returns, UTC inner-join, ≥20 overlap else `insufficient_overlap` → unmeasured ≠ pass).
- Next: ROADMAP.md, then P0 implementation. Repo still needs `git init` + GitHub remote (Mike's call to make now).

## 2026-07-12 — Pass B: DESIGN.md produced (Claude Code, Fable)

- Read all Pass-A inputs: SCOPE.md (D1–D17), Perplexity SME pass (F1–F7), canonical MAE doc.
- Wrote **docs/DESIGN.md** — full architecture doc: TD-1…TD-22 decision register, tech stack, 7 deep modules + 2 shared leaves + 2 thin shells, contracts (thesis contract + predicate DSL), event-sourced hash-chained ledger DDL, policy rules catalog R-001…R-016 with WHYs, promotion state machine (series hardened per SME F2/F3), two-phase order pipeline owned by `broker.execute_order`, own PaperBroker (TD-7), MAE port with derivatives-provider fallback chain, threat model, three-ring test strategy, build phasing P0–P5.
- Notable overrides of SCOPE (all flagged inline): promotion series locked to fixed 30-day blocks/≥10 trades/≥30 total (F2/F3); paper daily trade cap 20/day (anti-gaming); CoinMarketCap dropped.
- Key risk surfaced: **Binance fapi is US-geo-blocked (HTTP 451)** — canonical MAE's primary derivatives source; made derivatives a pluggable port, fallback question queued for Perplexity (DESIGN §18 Q1).
- Ran a cold-read consistency review via subagent: 20 defects found (2 HIGH), all fixed same-session.
- Next: Mike reviews DESIGN.md (§18 has 3 decisions for him + paste-ready Perplexity script) → adversarial review via Codex/gstack → ROADMAP.md → P0 implementation.

Blockers for Mike (from SCOPE §8, still open): CoinGecko demo key, Kraken read-only key, GitHub repo `tradekit` + `git init` (folder is not a git repo yet).
