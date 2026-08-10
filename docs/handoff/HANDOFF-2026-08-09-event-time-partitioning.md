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

**Hour 15 UTC — a COMPLETE, CLOSED hour entirely on the final build — PASS:**

| stream | symbols | rows | wrong-hour |
|---|---|---|---|
| ticks | 75 | 1,528,043 | 0 |
| books/coinbase | 51 | 103,876 | 0 |
| books/okx | 51 | 71,391 | 0 |
| trades/coinbase | 46 | 37,607 | 0 |
| trades/okx | 33 | 19,743 | 0 |
| perps/hyperliquid | 232 | 192,982 | 0 |
| liquidations/okx | 60 | 287 | 0 |
| equities/alpaca | 0 | 0 | 0 (market closed — correct) |
| **TOTAL** | | **1,953,929** | **0 (0.0000%)** |

Corroborating checks:
- **32,308 rows stamped `15:59:xx`**: every one in an hour-15 file. The hour
  boundary is where this bug always hid, so this is the check that matters.
- **855,546 rows** stamped after the restart: 0 misfiled.
- 0 duplicate rows on every stream carrying a unique id (trades/coinbase,
  trades/okx, perps trades) and on books/coinbase, books/okx, perps ctx.
  Kraken's shared timestamps are finding 5b(b), not duplicates in these.
- `LastTaskResult: 0`, 0 missed runs, 8/8 collectors up, compaction current
  (hour 15 merged in 187s), archive 7.59 GB with 457 GB free.

**Verify like this, not by reading the code.** A green partition audit at
15:12 sat alongside a cursor that had been re-storing five days of Alpaca tape
every five minutes since 14:55 (§5c). Partition correctness and cursor
correctness are different properties.

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

## 4b. The whole archive, after repair

Audited every tree, every day, 2026-08-09 ~18:15 UTC.

**Every CLOSED day, in every tree, is 0.00% wrong-hour:**

| tree | rows on 2026-08-08 | wrong-hour |
|---|---|---|
| ticks (book) | 23,213,832 | 0 |
| ticks (trades) | 155,780 | 0 |
| books/coinbase | 1,889,470 | 0 |
| books/okx | 207,137 | 0 |
| trades/coinbase | 90,145 | 0 |
| trades/okx | 35,323 | 0 |
| perps/hyperliquid (ctx) | 399,050 | 0 |
| perps/hyperliquid (trades) | 105,778 | 0 |
| liquidations/okx | 299 | 0 |
| equities/alpaca (all days) | 5,147,637 | 0 |

The ticks repair moved 2,678,592 rows over 308,854,446 read, 0 skipped, and a
second pass reads the identical 308,854,446 and moves nothing — idempotent,
nothing lost.

**What is still misfiled, and why that is correct.** An archive-wide audit
shows small non-zero rates (ticks 0.04%, books/okx 6.07%, trades/coinbase
6.26%). Every one of those rows is in **today's partition**, written by the
old code during hours 00–14 before the fixes went live. `repartition_archive`
never touches the day a live collector owns, by design. **Run it once after
00:00 UTC and 2026-08-09 clears too** — the younger trees show the highest
percentages simply because most of their data IS today (books/okx and perps
only started 2026-08-08).

Not corruption: an audit pass reported `FileNotFoundError` on a perps
`ctx-17.part-0006.parquet`. That is the audit listing a directory a moment
before `compact_archive.py` merged and unlinked that part. Harmless race
between two readers of a live tree.

## 5c. The regression this session caused, and how it was caught

Repairing the archive broke the Alpaca cursor, and the partition audit stayed
green throughout.

`repartition_archive` moved every row out of `RIOT/2026-08-08` into its true
day and deleted the files, but left the empty directory. `last_stored_cursor`
read only the single newest day directory, found nothing, and returned None —
which the caller reads as "nothing stored", so `start` fell back to the 5-day
lookback floor:

```
14:55:13 rows=3710400 COIN=456898 MSTR=874838 HOOD=707493 ...
15:04:41 rows=3682342 ...
15:13:14 rows=3661542 ...
```

Counts drift DOWN because the 5-day floor slides forward — the signature of a
cursor that never advances. 82,087,002 rows were written, of which
76,939,365 were duplicates; collapsing them returned the tree to exactly
5,147,637 rows, the same distinct-observation count as before. Nothing lost.

GLD happened to keep one file in that day, so 3 of 10 symbols behaved and the
log line read plausibly at a glance.

Fixed at both ends: the cursor walks days newest-first and stops at the first
that yields a timestamp (an empty day is a real state, not an impossible one),
and the repair tool removes a day directory it has emptied.

**Two lessons worth more than the fix.** A repair tool that leaves a husk can
break a consumer that reads directory structure as state. And a green
verification of one property says nothing about another — this was found by
reading the collector's own log, not by re-running the audit that had just
passed.

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

**(b) RESOLVED 2026-08-10 — Kraken book now throttled to 1 Hz.** Ratified by
Mike; see ASSUMPTIONS 180 and §9 below. The description of the problem is kept
here for the record.

**(b, as found) Kraken book was unthrottled — ~23% of its rows byte-identical.**
`collect_ticks.py` contains no `RowThrottle` at all. Every other venue goes
through `run_ws_collector`, which coalesces `book` to 1 Hz
(`BOOK_ROW_INTERVAL_S`). So the archive's LARGEST stream has a different
temporal resolution from every other book stream, which directly undercuts
the stated differentiator: "L2 depth with aligned cross-venue timestamps".

Measured on BTC_USD, complete hour 15 UTC 2026-08-09 — 40,334 book rows,
against a 1 Hz ceiling of 3,600:

| | rows |
|---|---|
| total | 40,334 |
| distinct timestamps | 30,820 |
| **byte-identical duplicate rows** | **9,186 (23%)** |
| distinct book states sharing a timestamp | 6,508 |

Two separate problems in that table. The 9,186 identical rows are pure waste:
the same top-10 written again because nothing coalesces them. The 6,508 are
worse in kind — genuinely different book states that are indistinguishable by
`(symbol, ts)`, because `now` is computed once per MESSAGE
(`collect_ticks.py:478`) and one frame can yield several rows.

Kraken trades are fine by comparison (1,474 rows, 7 identical): several fills
of one order sweeping levels legitimately share a venue timestamp.

Adding the 1 Hz throttle would cut the biggest stream by roughly an order of
magnitude and make it comparable with its peers. But that is a resolution
decision with a real cost — full depth-update resolution is genuinely more
information — so it is **Mike's call and deliberately not changed here.**

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
2. **Finish the `ticks` history repair — it is PARTIAL.** Everything else is
   done and verified: `equities/alpaca` (0.00% wrong-hour, 0 duplicates),
   `liquidations/okx`, `trades/okx`, `trades/coinbase`, `books/okx`,
   `perps/hyperliquid`, and `books/coinbase` (re-run after the corrupt file
   was quarantined: 0 skipped).

   `ticks` is roughly 30% applied — 2026-08-08 measures **1.38% wrong-hour,
   down from 1.87%**. Long whole-tree runs kept being killed, so use the
   chunked runner, which records progress per symbol and resumes:
   `scratchpad/repair_ticks_chunked.py` with `ticks_repaired.txt`. Per-symbol
   scoping is safe — `repartition_archive` never moves a row between symbols,
   only between day directories inside one — so
   `repartition_archive.py D:/tradekit-data/ticks/crypto/BTC_USD` is a valid
   unit of work. Re-measure with the audit script; the target is 0.00%.

   **Expect the row count to fall.** Repairing one day of `ticks` removed
   ~992,649 byte-identical rows (24,236,349 -> 23,243,700). That is not loss,
   it is finding 5b(b) being collected: Kraken book is unthrottled and
   re-writes the same top-10 repeatedly.
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


## 9. Kraken book brought to 1 Hz (2026-08-10, Mike ratified)

`collect_ticks` never had a row throttle — it predates collector_core and
never inherited `throttled_streams={"book"}` — so the archive's largest stream
was recorded at Kraken's update rate while every other book stream was
coalesced to 1 Hz. Now uniform, in the collector and in the history.

**Collector.** `RowThrottle(BOOK_ROW_INTERVAL_S)` gates the WRITE only;
`apply_update` still runs on every message, so the maintained book state is
unchanged and no update is missed. Trades are untouched and must stay that
way — pinned by a counter-test.

**History.** `scripts/downsample_book.py`, dry-run by default, book only, tree
lock shared with `repartition_archive`, days at/after the cutoff untouched.
It keeps the FIRST row of each window and slides from the last KEPT row, which
is what the live throttle does; a calendar-second grid would sample history
differently from new data.

| | rows |
|---|---|
| stored | 342,389,849 |
| kept at 1 Hz | 14,658,656 |
| **dropped** | **327,731,193 (95.7%)** |

    ticks tree      4.48 GB -> 0.85 GB
    whole archive   6.98 GB -> 3.36 GB   (52% smaller)

**Verified after the run:**
- Second pass drops 0 — idempotent.
- **Every closed day: zero book rows less than 1s apart.** The only sub-1s
  gaps left are in 2026-08-10, from the 7 minutes before the 00:07 UTC deploy;
  one more run after that day closes clears them.
- 0 book rows in the wrong hour — the partition invariant survived the rewrite.
- Trades untouched: 1,519,608 rows, none removed.
- Post-deploy live check: all sub-second gaps fall in **900-1000 ms**, none
  below. That is clock jitter, not throttle failure — the gate reads the
  monotonic clock while `ts` is captured at message receipt, and every venue
  gates the same way.

**Correction worth carrying.** I quoted ~10x (89.9%) when proposing this. That
came from counting distinct seconds on 2026-08-08 — a **Saturday**. Weekends
are the quiet days: ETH/USD averaged 18.0 book updates/second that day against
45.7 on weekdays. The real figure is 95.7%. The decision did not change but the
number quoted for approval was wrong by 2.3x. Do not extrapolate this archive
from a single day without checking the day of the week.

**Still to do:** after 2026-08-10 closes, run BOTH `repartition_archive` and
`downsample_book` over every tree once more to sweep that day's pre-deploy
rows. That is the routine that finishes any partition, not a special case.


## 10. Cold start after a reboot (checked 2026-08-10)

Asked directly: does the pipeline come back on its own after a restart?

**As found: no, not cleanly.** The watchdog task looked healthy by every check
this project normally runs — State `Ready`, `LastTaskResult: 0`, 8/8 collectors
up — but it was registered for steady-state babysitting, not cold start.

| | as found | now |
|---|---|---|
| triggers | one 15-min repeating TIME trigger | + `AtLogOn`, 2 min delay |
| `StartWhenAvailable` | False | True |
| `LogonType` | Interactive | Interactive (unchanged, see below) |

With only a time trigger and `LogonType: Interactive`, **nothing collects
until `admin` logs in**, and then up to 15 minutes pass before the first run.
The at-logon trigger closes that gap. Its 2-minute delay is deliberate: D: is
a USB disk and has to enumerate first.

**The disk guard matters more than the trigger.** D: is a USB disk (JMicron
bridge) and `collector_core.resolve_data_root()` silently falls back to
`<repo>/data` when `D:/tradekit-data` is missing. A watchdog run firing before
USB enumeration would have started all eight collectors writing to C: with no
error — an archive split across two roots that nothing would surface for days.
That risk goes UP once the task fires earlier, so the guard ships with the
trigger: `collector_watchdog.ps1` now logs and exits 1 if the disk is absent.
Non-zero is deliberate, because `LastTaskResult` is the one signal this
project already knows to check. Verified both branches — exit 1 with the disk
absent, exit 0 and 8/8 with it present, collectors untouched either way.

### Still open, both Mike's call

1. **Fully headless restart.** `LogonType: Interactive` means a machine that
   reboots and sits at the login screen collects nothing. That needs
   `-LogonType S4U`. Deliberately not changed: it moves the collectors into
   session 0, which is a session/security decision rather than a bug fix.

2. **`uv` resolves by accident.** The user PATH entry is the literal string
   `$HOME/.local/bin` (with backslashes) — a PowerShell variable Windows never
   expands, so the entry is dead. `uv` is found only because a second copy
   sits in `AppData/Local/hermes/bin/uv.exe`. Works today; breaks silently if
   hermes is removed or reordered. Fix is `%USERPROFILE%\.local\bin`, but it
   is Mike's environment.

Unrelated but noticed: the **paper-trading cadence task was never registered**
— the collector watchdog is the only tradekit task on the box. Still the open
"Mike's hands" item from the previous sprint, not a regression.
