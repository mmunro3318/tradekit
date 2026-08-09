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

## 4. Verification (2026-08-09)

Collectors restarted onto the fixed code at **12:12 UTC** (all 8, by the
scheduled task, `LastTaskResult: 0`).

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
