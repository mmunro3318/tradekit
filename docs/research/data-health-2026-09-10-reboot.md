# Data health — post-reboot audit, 2026-09-10

Read-only diagnosis of `D:\tradekit-data` after the unplanned Windows Update
restart between 2026-09-09 and 2026-09-10. No repair, delete, rename, restart,
or edit was performed. Report compiled ~2026-09-10 09:00 UTC (~01:59 PDT).

## 1. Boot facts

| fact | value |
|---|---|
| Local time zone | Pacific Time (PST/PDT, `Pacific Standard Time` Windows ID), DST **active** → UTC-7 in effect |
| `LastBootUpTime` (local) | 2026-09-09 17:03:23 PDT |
| `LastBootUpTime` (UTC) | **2026-09-10 00:03:23** |
| First watchdog run after boot (UTC) | **2026-09-10 06:28:04** — `watchdog.log`, all 8 `... down - relaunching` in one batch |
| 8 collector processes came back (UTC) | **2026-09-10 06:28:06** (process `CreationDate`, cross-checked against the log — confirms `watchdog.log` timestamps are UTC, not local) |
| Downtime gap | **6 h 24 m 41 s** (00:03:23 → 06:28:04 UTC) |
| Paper Cadence first post-boot run (UTC) | 07:00:03 (per `DIGEST-2026-09-10.md`) |

**Root-cause hypothesis confirmed, not just plausible.** The watchdog task is
`Logon Mode: Interactive only` — it cannot fire while the machine sits at the
login screen. Nothing ran between 00:03 and 06:28 UTC. Process launch time
(23:28:06 PDT = 06:28:06 UTC) lines up almost exactly with Mike's stated
arrival home (~23:30 local) minus the watchdog's own 2-minute post-logon
delay (README §4: "at logon (2-minute delay)"). This is the single relaunch
event in `watchdog.log` since 2026-09-05 — every stream was healthy the whole
time in between, so this is unambiguously the reboot's effect, not a
pre-existing flapping collector.

No prior watchdog activity in the 09-09 10:00–12:00 UTC window either (see
§3 — that gap is a different, unexplained anomaly, not this reboot).

## 2. Per-stream gap table

Measured by the `YYYY-MM-DD\<stream>-HH` **path** (the row's own event-time
partition), not file mtime, per the archive's invariant. Sampled BTC_USD /
ETH_USD / one thin-liquidity or representative symbol per stream; all 8
streams showed the identical boundary (last hour `23` on 09-09, first hour
`06` on 09-10, partial from 06:28), so the pattern is treated as archive-wide
rather than symbol-specific.

| stream | last data hour pre-boot (UTC) | first data hour post-boot (UTC) | lost hours | recoverable? |
|---|---|---|---|---|
| `ticks` (Kraken) **trades** | 2026-09-09 23 | 2026-09-10 06 (from 06:28) | 00–05 full + partial 06 (~6.4 h) | **Yes** — `scripts/backfill_ticks.py` (Kraken REST `/0/public/Trades`). Never overwrites existing files, only fills hours with no `trades-HH.parquet`. |
| `ticks` (Kraken) **book** | 2026-09-09 23 | 2026-09-10 06 (from 06:28) | same | **Partial, delayed, off-tree.** No REST order-book endpoint exists (confirmed in `backfill_ticks.py`'s own docstring), but `scripts/backfill_books_chd.py --exchange kraken_spot --datatype orderbook` can pull the same hours from the `cryptohftdata.com` vendor. Two catches: (a) the vendor's recent-side window lags **~10-11 days behind "now"** (measured 2026-08-08), so today's gap is not fetchable yet; (b) output lands in a **separate** provenance tree (`<root>\backfill\chd\...`), never merged into the live archive — it would sit alongside, not fill, the hole. |
| `books\coinbase` **book** | 2026-09-09 23 | 2026-09-10 06 (from 06:28) | ~6.4 h | **No.** No script covers Coinbase order-book. `backfill_books_chd.py`'s `ARCHIVE_MAP` (the table that lets it auto-diff against our own tree) only wires `kraken_spot` and `binance_spot` — Coinbase isn't in it. Book depth is gone. |
| `books\okx` **book** | 2026-09-09 23 | 2026-09-10 06 (from 06:28) | ~6.4 h | **No.** Same reasoning — OKX isn't in `ARCHIVE_MAP` either. Gone. |
| `trades\coinbase` | 2026-09-09 23 | 2026-09-10 06 (from 06:28) | ~6.4 h | **No — correcting the working assumption.** The task brief and `ARCHIVE-MAP.md` both assume a Coinbase trades backfiller exists ("trade tape sometimes can [be re-collected] ... backfillers exist for Coinbase/Kraken trades"). It does not: `grep coinbase scripts/*` finds only the live collectors (`collect_books_coinbase.py`, `collect_trades_coinbase.py`) and `repartition_archive.py`/`migrate_layout.py`/`compact_archive.py` (generic tools). There is no `backfill_*coinbase*` script. This gap is not recoverable with anything currently in the repo. |
| `trades\okx` | 2026-09-09 23 | 2026-09-10 06 (from 06:28) | ~6.4 h | **No.** No OKX trades backfiller exists. |
| `perps\hyperliquid` (`ctx` + `trades`) | 2026-09-09 23 | 2026-09-10 06 (from 06:28) | ~6.4 h | **No.** No Hyperliquid backfill script exists. |
| `liquidations\okx` | 2026-09-09 23 (per-instrument; confirmed stream-wide across all instrument dirs) | 2026-09-10 06 (stream-wide, confirmed across all instrument dirs — not just the one symbol sampled first) | ~6.4 h | **No.** Venue-wide forced-liquidation feed, no REST history, no backfill script. Any liquidation events during the gap are permanently gone. |
| `equities\alpaca` **trades** | 2026-09-09 23 (GLD has a `trades-00.part-0000` for 09-10 — a trade landed 00:00–00:03 UTC before the crash; IBIT does not, consistent with thinner extended-hours liquidity, not a defect) | 2026-09-10 08 (first bar after relaunch; market was closed 00:20–~12:00+ UTC anyway) | **~17 min of genuine loss** (00:03–00:20 UTC extended-hours tail, per README's own 00:20 UTC Wed/Fri close-of-tape figure), not the full 6.4 h — the rest of the "gap" is ordinary weekday overnight market closure, not collector downtime | **No.** No Alpaca backfill script exists; SIP trade history isn't free. The loss is real but small (well under an hour, thin-liquidity extended-hours prints only). |

**Not recoverable at all: book depth on 6 of 8 streams** (Coinbase, OKX
books; Kraken book is nominally scriptable but not for **this** gap, given
the vendor lag) — consistent with the archive's standing rule that book depth
has no REST equivalent. **Trade tape: only Kraken's is actually recoverable**
today; Coinbase/OKX/Hyperliquid/Alpaca trades are not, contrary to the
"trades usually can" assumption in the brief.

## 3. Paper cadence

- `TradeKit Paper Cadence`: **Last Result = 0**, Last Run 2026-09-10 01:00:01
  PDT = **08:00:01 UTC**. Task is also `Logon Mode: Interactive only`, so it
  shares the watchdog's exact failure mode — it simply couldn't fire while
  logged out.
- `DIGEST-2026-09-10.md` sections present: **07:00, 08:00 UTC** (report
  written before the 09:00 run was due). Missing: **00:00–06:00 UTC** (7
  hourly runs) — same reboot window as the collectors, first run landing
  32 minutes after the watchdog's own first post-boot pass.
- `DIGEST-2026-09-09.md` sections present: every hour **00:00–23:00 UTC
  except 10:00 and 11:00**. This gap is **not explained by the reboot** (boot
  was 09-10 00:03 UTC, hours later) and `watchdog.log` shows **zero**
  relaunch activity in or around that window — collectors stayed up the whole
  time. Root cause unknown from what's observable here (could be a brief
  sleep/lock that didn't drop the collector processes but did block the
  scheduled task, or something else). Flagging for Mike; not investigated
  further — out of scope for a reboot audit and the collector data itself
  shows no corresponding hole.
- **TAO/USD**: still open, **no exit recorded** in any run across either
  digest file (`### Exits` reads `- none` in all 22+2 runs checked; the
  `### Attrition` line for TAO/USD reads `killed_by=None` in every run,
  meaning it was never dropped by a prefilter either). No warnings
  specifically about TAO in either digest.

## 4. Health now (as of ~2026-09-10 08:59 UTC)

- **Processes:** 8/8 collector `python.exe` processes running, all launched
  2026-09-09 23:28:06 PDT (06:28:06 UTC) — i.e. all still the post-reboot
  relaunch, none has died and needed a second relaunch since.
- **Watchdog task:** `LastTaskResult = 0`, next run 01:58 PDT (on schedule).
- **Min-behind per stream** (newest data hour vs. current UTC hour 08):
  ticks, books-coinbase, books-okx, trades-coinbase, trades-okx,
  perps-hyperliquid, liquidations-okx (checked across **all** instrument
  dirs, not just the one symbol first sampled), equities-alpaca — **all at
  hour 08, i.e. 0 min behind.** Fully current.
- **Correctness audit** (closed day 2026-09-09 only; `scripts/audit_tree.py`
  does not exist in this repo — see §7 — so a scoped, read-only equivalent
  was written ad hoc and run against 6 symbol subtrees, ~1.30M rows total):

  | subtree | files | rows | wrong-hour | wrong-day |
  |---|---|---|---|---|
  | `ticks\crypto\BTC_USD` | 370 | 161,206 | 0 (0.0000%) | 0 |
  | `books\coinbase\crypto\ETH_USD` | 183 | 78,637 | 0 (0.0000%) | 0 |
  | `books\okx\crypto\BTC_USD` | 184 | 77,873 | 0 (0.0000%) | 0 |
  | `trades\coinbase\crypto\BTC_USD` | 694 | 462,545 | 0 (0.0000%) | 0 |
  | `perps\hyperliquid\crypto\BTC-PERP` | 763 | 414,456 | 0 (0.0000%) | 0 |
  | `equities\alpaca\IBIT` | 196 | 104,638 | 0 (0.0000%) | 0 |

  Clean. No re-partitioning defect around this reboot.
- **Orphan locks:** none. No `.lock` file at the archive root (only the
  known `COMPACTION-PAUSED` sentinel, last written 2026-08-23, expected —
  manual-compaction mode). No `compact_batch.py`/`compact_archive.py`/
  `repartition_archive.py`/`downsample_book.py` process alive.
- **Stale `.tmp` files:** none in **today's** (2026-09-10) directories across
  all 8 streams. But the full-archive sweep (started in §7's friction note,
  finished in the background after this report's first draft) surfaced
  **2 genuinely orphaned `.tmp` files, both dated 2026-09-09**, i.e. the day
  *before* today — outside the window my first scoped check covered, which
  only looked at 09-10:

  | file | size | mtime (local) | mtime (UTC) |
  |---|---|---|---|
  | `perps\hyperliquid\crypto\BERA-PERP\2026-09-09\ctx-23.part-0004.parquet.tmp` | 4,272 B | 4:59:08 PM | 23:59:08 |
  | `ticks\fx\BTC_EUR\2026-09-09\book-23.part-0005.parquet.tmp` | 33,436 B | 4:59:09 PM | 23:59:09 |

  Both are **~4 minutes before `LastBootUpTime`** (00:03:23 UTC) — writes
  genuinely in flight when Windows Update began tearing the machine down.
  Neither has a completed sibling (`ctx-23.part-0004.parquet` /
  `book-23.part-0005.parquet` for the same index don't exist), and each
  collector's part counter moved past that index on relaunch rather than
  resuming it, so these two files are permanently orphaned — the temp+rename
  invariant held (no half-file masquerading as a real parquet: `*.parquet`
  globs skip `.tmp`), but the two bytes-worth of in-flight rows they held
  were never committed and are gone. This is exactly the invariant-#2
  "evidence of a killed job" the skill describes, and it is the most direct
  physical proof that the crash was a hard kill, not a clean shutdown, for
  at least these two collectors (Hyperliquid perps, Kraken ticks). No other
  `.tmp` files turned up anywhere else in the full sweep. This does not
  change §2's gap accounting — the lost rows were already inside the
  already-counted lost hour (23:00–00:00 / hour 00 boundary) — it's
  corroborating evidence, not additional loss.

## 5. Compaction backlog

- `compaction.log` last entry: **2026-08-23** (matches the `COMPACTION-PAUSED`
  sentinel's mtime). **18 days** of backlog as of this report.
- Sampled part-vs-merged file counts (3 subtrees, not the whole archive —
  full-tree enumeration is the ~1.6M-file walk the skill warns against):

  | subtree | total files | `.part-NNNN` | merged hourly |
  |---|---|---|---|
  | `ticks\crypto\BTC_USD` | 2,644 | 1,242 (47%) | 1,402 |
  | `books\coinbase\crypto\BTC_USD` | 1,334 | 633 (47%) | 701 |
  | `equities\alpaca\IBIT` | 796 | 408 (51%) | 388 |

  Roughly half the files in these subtrees are still unmerged parts. The
  README's own measured baseline (compacting 667 hours / 4,080 parts in 30 s
  as of 2026-08-23) suggests a full-archive run today would be a multi-minute
  job, not multi-hour — but this is an estimate from 3 symbols, not a real
  count, and **no compaction command was run**, per instructions. This
  remains Mike's call.

## 6. Findings, root cause, options

**Findings (numbers):**
1. 6 h 25 m of total collection blackout across all 8 streams, 2026-09-10
   00:03–06:28 UTC, caused by the watchdog/cadence tasks' `Interactive only`
   logon requirement combined with nobody being logged in.
2. Of that blackout: book depth on 2 streams (Coinbase, OKX) and trade tape
   on 4 streams (Coinbase trades, OKX trades, Hyperliquid, Alpaca) plus
   liquidations on 1 stream are **permanently and completely unrecoverable**
   with anything in this repo today. Kraken trades are recoverable via
   `backfill_ticks.py`. Kraken book is nominally scriptable via
   `backfill_books_chd.py` but not for this specific window (vendor lag).
3. Alpaca's real loss is much smaller than the raw gap suggests: ~17 minutes
   of Wednesday extended-hours tape (00:03–00:20 UTC), because the market
   was closing anyway during most of the blackout.
4. Everything is healthy right now: 8/8 processes, watchdog green, all
   streams at 0 min behind, 0.00% wrong-hour / 0 wrong-day on the closed
   day across every subtree sampled, no orphan locks, no stale tmps in
   today's directories. Two orphaned `.tmp` files dated 2026-09-09 (§4) are
   leftover clutter from the hard kill, not an ongoing health problem —
   harmless (skipped by every `*.parquet` glob) but will sit there forever
   uncleaned.
5. Paper Cadence lost the same 7 hourly runs for the same reason; TAO/USD
   (the one open paper position) shows no exit and no warnings in any run
   across both digest files — nothing needs Mike's attention there beyond
   awareness of the gap.
6. A second, unrelated, unexplained gap exists in `DIGEST-2026-09-09.md`
   (hours 10:00 and 11:00 UTC missing) with no corresponding collector
   outage — worth a look, but out of scope here.
7. This repo's working assumption that Coinbase trades has a backfiller is
   wrong — only Kraken does.

**Root-cause hypothesis:** confirmed, not speculative — the watchdog and
cadence scheduled tasks are both `Logon Mode: Interactive only`; the machine
sat at the login screen from boot (00:03 UTC) until Mike's login
(~06:26–06:28 UTC), and nothing ran in between. This is exactly the
known-open risk already recorded in `ARCHIVE-MAP.md`: *"Left explicitly in
Mike's hands: `-LogonType S4U` for headless boot (the watchdog runs only
while `admin` is logged in — a machine at the login screen collects
nothing)."* That fix was never applied, and this reboot is the fix's absence
costing ~6.4 hours of order-book depth on two venues, permanently.

**Options (Mike's call, not executed):**
1. **Do nothing.** The loss is bounded, already happened, and cannot grow.
   Simplest, but the exact same failure recurs on the next unplanned reboot
   (Patch Tuesday reboots are routine on this machine, per the update
   cadence that caused this one).
2. **Register the watchdog (and ideally the cadence task) with
   `-LogonType S4U`** so they run without an interactive session, closing
   the gap for future reboots. This is the fix already named as
   Mike's-hands-only in `ARCHIVE-MAP.md`; it does not touch this repo's code.
3. **Backfill what's recoverable now:** run `backfill_ticks.py --dry-run`
   first to confirm it reports the 6 missing Kraken trade hours, then (with
   Mike's go-ahead) the real run. This recovers the one stream that can be
   recovered; everything else stays lost regardless of when it's run.
4. **Investigate the second 09-09 10:00/11:00 cadence gap** separately — it
   has no collector-outage correlate, so it's a different failure mode than
   this reboot and deserves its own look.

**Recommendation:** Option 2 (S4U) is the actual fix for the recurring
failure mode; it is cheap and was already identified before this incident.
Option 3 is worth doing regardless, since it is the only lever that
recovers any of the lost data and costs nothing to defer. Compaction (§5)
and the 09-09 cadence gap (§3) are lower urgency and independent decisions.

## 7. Friction

- **`scripts/health_snapshot.ps1`, `scripts/coverage.py`, and
  `scripts/audit_tree.py` do not exist in this repo** — confirmed via
  directory listing and repo-wide glob (`**/health_snapshot*`,
  `**/coverage.py`, `**/audit_tree*` all return nothing). Both the task
  brief and the `tk-data-health` skill's own workflow reference them as
  step 1/3/4. Worked around by: (1) reconstructing the liveness/min-behind
  check directly in PowerShell (process count, `Get-ScheduledTaskInfo`-style
  `schtasks` query, newest-file-per-stream walk); (2) skipping the
  day-partition coverage scan (§3's digest section audit substitutes for
  the cadence side; no equivalent was attempted for the raw archive's day
  partitions given time budget — if this matters, it needs either the
  missing script written or a scoped manual walk); (3) writing a small,
  scoped, read-only ad hoc Python script
  (`spotcheck_audit.py`, in the session scratchpad, not the repo) using
  `pyarrow` to replicate `audit_tree.py`'s ts-vs-directory check for 6
  subtrees on the closed day. This should be flagged to Mike/logged via
  `docs/FRICTION.md` — three tools the skill and this task depend on are
  missing from the tree.
- **A recursive `.tmp` search across all 8 top-level trees timed out** (hit
  the tool's 120 s foreground limit and was auto-moved to background instead
  of failing outright — not something I requested). Re-scoped to a per-
  stream, current-day-only sample in the meantime, per the skill's own
  warning against whole-tree walks (~1.6M files) — that scoped check missed
  the two orphaned 09-09 `.tmp` files in §4 because it only looked at
  09-10. The backgrounded sweep was left running (harmless, read-only
  `Get-ChildItem`) rather than force-killed, and **did finish on its own**
  a few minutes later, `exit 0` — its output was then used to locate and
  confirm the two orphaned files, since a targeted, scoped re-query around
  the crash timestamp is fast on its own. Lesson for next time: scope the
  first `.tmp` sweep by **the day the crash actually fell on**, not "today,"
  since the process is killed mid-write on the day of the incident, and
  a partial `Select-Object FullName, LastWriteTime` on very deep paths can
  render with a blank/truncated `FullName` column in this console width —
  don't read that as "no path," re-query narrower instead of trusting the
  blank.
- **`ts` timestamp format assumption**: confirmed empirically (not just from
  the README) that `ts` strings slice cleanly as `ts[:10]` for the date and
  `int(ts[11:13])` for the hour across all 6 sampled subtrees — no exotic
  formatting encountered.
