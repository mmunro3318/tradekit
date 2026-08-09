# HANDOFF 2026-08-09 — event-time-partitioning (sprint seed)

Written for a reader with ZERO conversation context. Every path is
absolute-from-repo. Nothing here says "as discussed".

Read `docs/handoff/HANDOFF-2026-08-09-data-vacuum-expansion.md` FIRST for the
pipeline architecture and the venue-access facts — it is still the reference
for how the collectors work. This seed only carries what changed after it,
**including two corrections to it**, listed in §6.

## State (auto-captured)
- branch: `fix/event-time-partitioning`  anchor: `7fc6180`
- last gate: green @ `4826939` (2026-08-09T12:18 UTC)

recent commits:
```
7fc6180 feat(collector): repartition_archive — repair history misfiled by flush time
4826939 fix(collector): retire the three private ParquetSinks (GATE: green)
3c55068 fix(collector) green: file every row by its own event time (GATE: green)
2212dbc fix(collector) red: event-time partitioning + nanosecond-exact Alpaca cursor (red)
a619f80 docs: data-vacuum sprint seed, dev-log, friction log, regenerated HUD
211fe86 feat(collector): data-vacuum expansion — 8 live streams on a shared core
c02c71b chore: vendor test-suite-auditor agent + code-review/tdd-audit skills
```

`211fe86`..`a619f80` are the previous session's work, which had been sitting
green and **uncommitted** — that is now committed and no longer a risk.

## Mission

The archive was filing every row by INGEST time rather than by the row's own
timestamp, so hour-partitioning could not be trusted on any stream. Fix the
sinks, repair what was already written, and prove it with measurements rather
than with a claim. Secondary: kill an Alpaca cursor bug that had been
re-storing the same 15 prints on every poll since Friday's close.

## 1. What was wrong, with numbers

Every sink named its target file from FLUSH time. Measured on 2026-08-08 alone,
BEFORE the fix:

| stream | rows | wrong-hour | wrong-day |
|---|---|---|---|
| ticks (kraken book) | 24,236,349 | 1.87% | 38,148 |
| books/coinbase | 1,889,897 | 0.74% | 427 |
| books/okx | 207,137 | 5.65% | 0 |
| trades/coinbase | 92,076 | 5.90% | 110 |
| trades/okx | 35,323 | 4.72% | 0 |
| perps/hyperliquid (ctx) | 399,050 | 3.12% | 0 |
| liquidations/okx | 299 | 18.39% | 0 |
| equities/alpaca | 5,150,262 | 14.7–18.5% | 100% at weekends |

Note the collector_core streams score WORSE than the legacy ones. That is a
direct cost of the previous session's `MIN_PART_ROWS` change: making a buffer
wait until it earns a file means more buffers straddle an hour boundary. The
previous FRICTION entry claims the hour escape handled it — the escape fired
correctly and then wrote the rows into the NEW hour's file, which is the bug
it claimed to prevent.

## 2. The three fixes

1. **`PartitionedParquetSink` partitions on the row's own timestamp.** It
   buffers `(ts, row)` pairs; one flush writes one part file per `(day, hour)`
   the buffer spans. **`flush()` takes no `ts` argument — do not add one back.**
   A parameter that looks like it decides the path but does not is how this
   survived review the first time. Consequence accepted: a collector can now
   write into an already-compacted hour; `compact_hour` already merges into an
   existing target, so that is safe.

2. **Alpaca cursor is microsecond-exact with boundary suppression.**
   `start` was formatted `%H:%M:%SZ`. Alpaca's `start` is INCLUSIVE and it
   stamps nanoseconds, so second-truncation re-requested the whole final
   second forever: 15 prints × 176 passes = 2,625 redundant rows over the
   closed weekend. No arithmetic cursor is correct (`newest + 1us` drops
   prints inside that microsecond), so `last_stored_cursor` returns the newest
   instant PLUS the identity of every row at it, and those are dropped on
   arrival. Suppression is scoped to that one instant.

3. **The three private per-venue ParquetSinks are retired.** `collect_ticks`,
   `collect_books_coinbase` and `collect_books_binance` each had their own
   copy — 74% of the archive by volume, and not one test between them. All
   three had the flush-time bug PLUS read-modify-write (read the whole hourly
   file back and rewrite it, every 60s). That is quadratic in rows/hour and a
   kill mid-write takes the hour with it. **It already did** — see §5.

Alpaca also stopped routing through `asset_class()`: no `_CLASS_RULES` rule
matches an equity ticker, so all ten symbols were filed under
`equities/alpaca/crypto/`. Its sink now runs `partition=False`; the tree was
flattened up one level on 2026-08-09.

## 3. `scripts/repartition_archive.py`

Repairs history. Possible only because the timestamp is in the data — nothing
is refetched.

```bash
uv run python scripts/repartition_archive.py D:/tradekit-data/ticks            # dry run
uv run python scripts/repartition_archive.py D:/tradekit-data/ticks --no-dry-run
```

It deletes source files, so it is deliberately timid, and these rules are
tested, not aspirational:

- `--dry-run` defaults ON.
- Days at or after the cutoff (default: today UTC) are neither read **nor
  written into** — a live collector owns those.
- If ANY file in a `(symbol, day, stream)` unit is unreadable, the whole unit
  is skipped rather than rewritten around the gap.
- A row whose `ts` will not parse stays exactly where it is.
- An hour already correct is not rewritten at all, not even byte-identically.
- All reads happen before any write, so a read failure aborts before any
  destruction.
- Byte-identical rows are collapsed and the count is reported first.

**Safe to run against a live tree** because of the cutoff rule, but first
confirm compaction is caught up (no `part-NNNN` files in past days) so it
cannot race `compact_archive.py`.

## 3b. It took FOUR fixes, and only measurement found the last three

Each round of measuring live data exposed another caller that had not been
fixed. This is the most important thing in this document.

| measured | overall wrong-hour | what was still wrong |
|---|---|---|
| 2026-08-08, before anything | 0.74–18.4% | the sink named files from flush time |
| hour 13, after the sink fix | 0.1083% | `run_ws_collector` passed ARRIVAL time |
| hour 14, after the runner fix | 0.0009% | `collect_perps_hyperliquid` (custom orchestrator) did too |
| **hour 15, after the sink stopped trusting callers** | **0.0000%** | — |

`PartitionedParquetSink.add(symbol, stream, row, ts)` looked like it wanted
the row's timestamp, but every caller had `now` in hand and passed that. Three
callers made the same mistake independently, so the parameter was the bug, not
the callers. `add` now treats `ts` as the ARRIVAL time — a fallback — and
`event_ts(row, ts)` prefers the row's own stamp whenever it parses. **Do not
"simplify" that back to trusting the caller.**

## 4. Verification (2026-08-09)

Collectors restarted onto the final build at **14:25 UTC** (all 8, by the
scheduled task, `LastTaskResult: 0`).

**Hour 15 UTC, the first full hour on the final build — PASS:**

| stream | symbols | rows | wrong-hour |
|---|---|---|---|
| ticks | 73 | 365,078 | 0 |
| books/coinbase | 48 | 19,417 | 0 |
| books/okx | 51 | 13,023 | 0 |
| trades/coinbase | 34 | 7,582 | 0 |
| trades/okx | 20 | 6,165 | 0 |
| perps/hyperliquid | 232 | 31,203 | 0 |
| liquidations/okx | 6 | 11 | 0 |
| equities/alpaca | 0 | 0 | 0 (market closed — correct) |
| **TOTAL** | | **442,479** | **0 (0.0000%)** |

Corroborating checks, same run:
- **855,546 rows** stamped after the restart, across all 8 streams: 0 misfiled.
- **56,053 rows stamped `14:59:xx`**: every one in an hour-14 file. The hour
  boundary is where this bug always hid, so this is the check that matters.
- 0 duplicate rows post-restart on every stream carrying an id.
- Every stream written within ~1 minute at the time of the sweep.

- **Alpaca, live proof:** every pre-fix poll logged `rows=15` — the same 15
  phantom prints. Every post-fix poll logs `rows=0`, which is correct on a
  closed Sunday market.
- **Alpaca tree repaired:** 5,148,222 rows read, 851,441 moved (16.5%), 585
  duplicates collapsed, 0 skipped. Second pass a clean no-op.
  Post-repair audit: **0.00% wrong-hour on every day, 0 duplicate keys**,
  5,147,637 rows — exactly the distinct-observation count measured before the
  repair. Nothing lost.
- The stale `equities/alpaca/*/2026-08-09/` partitions held 2,145 rows of
  which **zero** were unique; proved row-by-row against the rest of the tree
  before deleting.
- **Compaction confirms it in production:** the 12:28 cycle merged rows into
  **hour 11**, i.e. stragglers buffered at 11:5x and flushed at 12:0x now land
  in hour 11 rather than hour 12.

## 5. The corrupt file — open item

`D:/tradekit-data/books/coinbase/crypto/CAKE_USD/2026-08-08/book-05.parquet`
has a `PAR1` header and **no footer magic bytes**: killed mid
read-modify-write by the old sink. 10.4 KB against 27–127 KB neighbours, so
it is one hour of a thin pair's L20 book. Unrecoverable without the footer.

It blocks `repartition_archive` from repairing that whole
`(CAKE_USD, 2026-08-08, book)` unit, by design. To unblock: rename it to
something `_HOUR_FILE_RE` does not match (e.g. `book-05.parquet.corrupt`) —
**preserve the bytes, do not delete** — then re-run the tool on
`books/coinbase`.

## 5b. Two OPEN findings, both pre-existing, neither fixed

Found while verifying. Characterised, not solved — do not assume either is
handled.

**(a) Coinbase persists snapshot blocks it is supposed to skip.**
`trades/coinbase` stores 100-row descending blocks — exactly 100 per thin
symbol, in multiples of 100 across reconnects (AUDD_USDC 200, W_USD 300,
ADA_BTC 100, XSGD_USDC 100). 100 is the `market_trades` snapshot size, and
`parse()` skips `type: "snapshot"`. That skip was verified directly: real
frames from ADA-BTC, XSGD-USDC, AUDD-USDC and BTC-USD fed through the
collector's own `parse()` produced 4 snapshots, all skipped, and emitted
nothing stale. **The mechanism is unexplained.** Since the event-time fix
those rows land in their true day/hour, where they are exact duplicates that
`repartition_archive` collapses — so it is redundancy, not corruption. Next
step: instrument the running collector to log event types and frame counts,
rather than probing a separate connection.

**(b) Kraken book rows are not throttled, and share timestamps.**
`collect_ticks.py` contains no `RowThrottle` at all. Every other venue goes
through `run_ws_collector`, which coalesces `book` to 1 Hz
(`BOOK_ROW_INTERVAL_S`). So the archive's LARGEST stream has a different
temporal resolution from every other book stream — which directly undercuts
the stated differentiator, "L2 depth with aligned cross-venue timestamps".
Measured on BTC_USD hour 15: 1,555 rows in ~12 minutes (~2.2/s, against 1/s
elsewhere), and only 1,101 distinct timestamps, because `now` is computed once
per MESSAGE (`collect_ticks.py:478`) and one frame can yield several rows.
Rows sharing a microsecond are indistinguishable.

This is a product decision, not a bug fix: full resolution costs disk and
breaks cross-venue alignment; 1 Hz matches the rest of the archive and would
cut the biggest stream substantially. **Mike's call** — deliberately not
changed.

## 6. Two corrections to the previous seed

1. **There is no "53-hour July book gap".** The seed says ETH/USD and SOL/USD
   are missing a 53h span from 2026-07-19 23h. Verified 2026-08-09:
   **Coinbase books collection began 2026-07-26** (ticks began 07-19), and
   ETH_USD has all 15 day-directories since. There is nothing before 07-26 to
   repair — backfilling it is a legitimate but different job with a different
   cost. The genuine loss is ~19h of shared tick+book outage.
2. **Burn is lower than the seed's 2.55 GB/day**, which was measured during
   the 9.5h compaction backlog when uncompacted part files inflated the tree.
   **Re-measure it now** the archive is deduplicated, compacted and
   repartitioned; the retention-vs-disk decision in the seed is much less
   urgent than it reads.

## 7. Next actions (ordered)

1. **Merge `fix/event-time-partitioning`.** Gate green at `4826939`; re-run
   `tk-gate` first, HEAD has moved since.
2. **Finish the crypto-tree repartition** if it did not complete — it is
   idempotent, so just re-run per tree. `equities/alpaca` is done and verified.
   `liquidations/okx`, `trades/okx`, `trades/coinbase`, `books/okx` and
   `perps/hyperliquid` are done. `books/coinbase` and `ticks` (5.49 GB, the
   long one) are the remainder.
3. **Rename the corrupt CAKE_USD file** (§5) and re-run `books/coinbase`.
4. **Re-measure burn** and settle retention vs. disk.
5. **Binance archive backfill** — biggest untapped source, history to 2017,
   currently 0% used. `scripts/backfill_binance_archive.py`, `--dry-run`
   defaults ON.
6. **Alpaca NBBO for IBIT + GLD only** (~25 MB/day). Add `--quotes IBIT,GLD`
   to the alpaca row in `scripts/collector_watchdog.ps1`.
7. **GitHub remote + push** (Mike's hands).

## 8. Standing traps

- `LastTaskResult` must be `0`. A "Ready" state says nothing — the watchdog
  task silently failed for ~10h on 2026-08-09 because its action pointed at
  `pwsh`, which resolves only to a Store app-execution alias here.
- Changing `scripts/collector_core.py` does nothing until the collectors are
  **restarted**. The watchdog only relaunches processes that have DIED. Kill
  all 8 and `Start-ScheduledTask -TaskName 'TradeKit Collector Watchdog'`.
- Do not read pytest pass counts from rtk-filtered output; it reported
  "No tests collected" on a green 1314-test suite. Use `tk-gate`.
