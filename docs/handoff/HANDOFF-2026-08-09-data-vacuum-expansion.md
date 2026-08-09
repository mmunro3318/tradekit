# HANDOFF 2026-08-09 — data-vacuum-expansion (sprint seed)

Written for a reader with ZERO conversation context. Every path is
absolute-from-repo. Nothing here says "as discussed".

## State (auto-captured)
- branch: `main`  anchor: `1cea218`
- last COMMITTED gate: green @ `80c3af8` (2026-08-03)
- **current gate: 1314 passed, ruff clean — but UNCOMMITTED.** The whole
  session's work is a dirty tree of 26 paths. **First action for anyone
  touching this repo: read "Uncommitted tree" below before you `git` anything.**

recent commits:
```
1cea218 docs: sprint close-out - machinery complete, Mike's scheduler step is the remaining human action
88f71a4 merge feature/cadence: autonomous paper cadence (batch G2, paper sprint)
6b1558f cadence T3 green: autonomous paper runner + digest
```

## Mission

Turn a single-venue crypto tick archive into a multi-venue, multi-asset-class
market-data library that can eventually be open-sourced. The differentiator is
deliberately NOT OHLCV (Kraken and CryptoDataDownload already publish that for
free) but **L2 order-book depth with aligned cross-venue timestamps**, plus the
things nobody gives away: perpetual funding/open-interest, forced liquidations,
and cross-asset (equity/ETF) alignment.

Scope this session: greenlist 11 → 87 pairs, 3 collector processes → 8, one
shared collector core replacing copy-pasted per-venue code, 3 backfillers, and
an asset-class-partitioned on-disk layout.

---

## 1. Architecture — how the pipeline actually works

### 1.1 Data flow

```
                       scripts/collect_ticks.py :: GREENLIST_PAIRS
                          (87 symbols, ONE source of truth)
                                      |
        +-----------------------------+-----------------------------+
        |                             |                             |
   LIVE COLLECTORS              BACKFILLERS                  MAINTENANCE
   (8 processes)                (manual, batch)              (scheduled)
        |                             |                             |
        v                             v                             v
  collector_core.py            writes to separate           compact_archive.py
  VenueSpec + runner           provenance trees             merges part files
        |
        v
  PartitionedParquetSink -> <stream>-<HH>.part-NNNN.parquet
                                      |
                          compact_archive.py (every 15 min)
                                      v
                            <stream>-<HH>.parquet
```

Each venue collector self-filters: it calls its own `verify_pairs()` against
that venue's instrument list and silently drops what the venue does not list.
That is why OKX-only pairs (USDT/TRY) and Coinbase-only pairs (XSGD/USDC) can
live in one shared greenlist without breaking anyone.

### 1.2 The shared core — `scripts/collector_core.py`

READ THIS FILE FIRST. It owns everything that is not venue-specific.

A venue is a `VenueSpec` dataclass: `ws_url`, a `subscribe(symbols)` that
returns JSON payloads, a `parse(msg, now)` that returns
`[(symbol, stream, row), ...]`, and an `error_of(msg)`. `run_ws_collector`
owns sharding, reconnect/backoff, throttling, keepalive, liveness and the sink.

Key contracts you must not break:

| Thing | Contract |
|---|---|
| `PARTITION_BY_CLASS` | **True.** Single switch for the whole archive layout. Every collector routes paths through `stream_dir`. Never flip while anything is running. |
| `asset_class()` | BASE decides `stables`, QUOTE decides `cross`. `USDC/USD`→stables, `BTC/USDT`→cross, `BTC/EUR`→fx, `PAXG/USD`→rwa, else `crypto`. |
| Stream names | Must match `[A-Za-z0-9_]+`. `_assert_stream_name` raises otherwise — see §3.1 for why this is load-bearing. |
| Writes | Append-only part files. Never read-modify-write. |
| `MIN_PART_ROWS=500` | A buffer must earn a file. Escapes: `MAX_BUFFER_AGE_S=600`, and always flush before crossing an hour. |
| `flush_all(force=True)` | Shutdown only. A small buffer beats a lost one. |

### 1.3 Live collectors (all 8 running, watchdogged)

| Script | Venue | Content | Output tree | Notes |
|---|---|---|---|---|
| `collect_ticks.py` | Kraken WS v2 | trades + L10 book | `ticks/` | 76 of 87 pairs. Owns `GREENLIST_PAIRS`. |
| `collect_books_coinbase.py` | Coinbase | L20 book | `books/coinbase/` | 52 pairs. **Caps at 30 L2 streams/session — sharded.** |
| `collect_trades_coinbase.py` | Coinbase | trades | `trades/coinbase/` | 48 pairs. `market_trades` is PUBLIC, no key. |
| `collect_books_okx.py` | OKX | L20 book | `books/okx/` | 51 pairs. Replays `books` incrementals. |
| `collect_trades_okx.py` | OKX | trades | `trades/okx/` | 37 pairs. |
| `collect_liquidations_okx.py` | OKX | forced liquidations | `liquidations/okx/` | **Venue-wide, 771 instruments** (SWAP+MARGIN+FUTURES). |
| `collect_perps_hyperliquid.py` | Hyperliquid | funding/OI/mark/oracle + trades | `perps/hyperliquid/` | **All 232 perps.** WS + REST backstop. |
| `collect_equities_alpaca.py` | Alpaca | SIP equity trades (+opt. NBBO) | `equities/alpaca/` | 10 symbols. Delayed poller, see §4.5. |

### 1.4 Backfillers (manual, NOT watchdogged)

| Script | Source | Fills | Bounds |
|---|---|---|---|
| `backfill_ticks.py` | Kraken REST | Kraken TRADE gaps | Pre-existing. Cannot do books — Kraken publishes no historical book endpoint. |
| `backfill_binance_archive.py` | `data.binance.vision` | Binance GLOBAL history | 2017-08-17 → yesterday. `--dry-run` defaults ON. |
| `backfill_books_chd.py` | cryptohftdata.com | Kraken L2 BOOK gaps | **~2025-06-29 floor AND ~11-day recent lag.** `--dry-run` defaults ON. |

Backfill writes to `archive/binance/` and `backfill/chd/` — **separate trees
from live-collected data, deliberately.** Provenance must stay separable for
the open-source release. Do not merge vendor data into our own directories.

### 1.5 Maintenance

- `scripts/compact_archive.py` — merges closed-hour part files. Runs from the
  watchdog. Idempotent, skips the current hour.
- `scripts/migrate_layout.py` — flat → class-partitioned. **Already applied**
  (124 dirs, 2026-08-08). Refuses to run while collectors are live.

### 1.6 How to (re)initialize from cold

```powershell
# 1. Everything is driven by ONE scheduled task, every 15 min, idempotent:
Start-ScheduledTask -TaskName 'TradeKit Collector Watchdog'

# 2. Verify it did not fail (see §3.6 — this silently broke for ~10h):
Get-ScheduledTaskInfo -TaskName 'TradeKit Collector Watchdog' |
    Select-Object LastRunTime, LastTaskResult    # LastTaskResult MUST be 0

# 3. Confirm 8 collectors:
(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'collect_' -and $_.CommandLine -match '\.venv' }).Count
```

Adding a venue = one row in `$Collectors` in
`scripts/collector_watchdog.ps1`. A script that does not exist is skipped
quietly, so half-built collectors can sit in the table.

Secrets live in `C:\Users\admin\dev\tradekit\.env` (gitignored):
`CRYPTOHFTDATA_API_KEY`, `ALPACA_API_KEY_ID`/`ALPACA_API_SECRET`,
`COINGECKO_API_KEY`. **Coinbase and Hyperliquid need NO key** — their market
data is fully public. Do not add keys for them.

---

## 2. Venue access — verified facts, do not re-derive

| Venue | Live API | Historical | Notes |
|---|---|---|---|
| Kraken | ✅ open | trades only | WS v2 uses **BTC**, REST `wsname` still says **XBT**. No historical book endpoint. |
| Coinbase | ✅ open, no key | none | `level2` caps at **30 products/session**; the 31st gets one error frame then SILENCE. |
| OKX | ✅ open, no key | none | Only new deep venue reachable. `books-l2-tbt` is auth-gated. `checksum` is always 0 on the public feed. Closes idle conns ~30s — needs app-level `ping`. |
| Hyperliquid | ✅ open, no auth | S3 requester-pays | 1200 weight/min. `metaAndAssetCtxs` = all 232 perps in ONE weight-20 call. |
| Binance GLOBAL | ❌ 451 | ✅ `data.binance.vision` | **Live blocked, archive open.** `fstream` also blocked (proved by control test). |
| Binance.US | ✅ open | ✅ (5-day lag) | **RETIRED.** ~2,669 BTC prints/day vs Kraken's 42,063. WS trade channel publishes NOTHING. |
| Bybit | ❌ 403 | via cryptohftdata | Reachable only through the vendor or CoinGecko. |
| Alpaca | ✅ w/ key | SIP at T-15min | Real-time SIP needs a paid plan; history does not. Both tiers go back ~9 years. |
| CoinGecko | ✅ Demo key | aggregate | 30 req/min. **Returns Binance + Bybit prices/spreads** — the legitimate route to blocked venues. |
| cryptohftdata | ✅ w/ key | L2 books | Floor ~2025-06-29, recent lag ~11 days. **No Coinbase, no Binance.US.** klines 404 despite being advertised. |

### 2.1 Content that does NOT exist (stop looking)

- **Kraken historical order books** — only via cryptohftdata.
- **Binance `liquidationSnapshot`** — coin-margined only, and DISCONTINUED
  (last file 2024-10-14). No live substitute (fstream geo-blocked).
- **Binance `bookDepth`** — is NOT an order book. It is a 1-second snapshot of
  cumulative depth at 11 fixed % bands. `bookTicker` (best bid/ask, tick-level)
  IS real and IS current.
- **Hyperliquid liquidations** — no official feed. Only a zero-hash-trade
  heuristic, recorded as the `is_candidate_liquidation` COLUMN, never as truth.
  Observed rate swung 5.5% → 21.9% between samples. Do not build on it.
- **CBDCs** — every one is a pilot with no public market. Never collectable.

---

## 3. Insights: mistakes made this session

These cost real time. They are here so nobody pays twice.

### 3.1 My bugs (in `collector_core.py`)

1. **Part numbering restarted at 0 per sink instance → silent data loss.** An
   in-memory counter with no disk check meant a second sink writing the same
   hour overwrote `part-0000`. Bit REST pollers and, worse, any
   watchdog-relaunched collector (which would clobber everything since the top
   of the hour). Fixed: `_next_part` seeds from disk once per hour.
2. **`_PART_RE` was `[a-z_]+` → the SAME data loss, through a different door.**
   A stream named `aggTrades` or `book5` matched nothing, so `part_files()`
   returned empty, so compaction became a permanent silent no-op AND
   `_next_part` always returned 0. Three writes left one file with one row.
   Fixed: `[A-Za-z0-9_]+` plus `_assert_stream_name` so it can never be silent.
   **Lesson: one regex fed two consumers; fixing the visible one would have
   left the invisible one destroying data.**
3. **Tiny part files.** Flushing every buffer every 60s wrote 6-row files at
   232 symbols. 6.54 GB/day, of which most was parquet footer overhead. Fixed
   with `MIN_PART_ROWS` + bounded escapes → 2.55 GB/day.
4. **Wrote a `/USD$` fx rule** that would have swallowed every major into the
   fx sleeve. Caught before deploy.
5. **Relayed subagent numbers without checking units** — see §3.2.

### 3.2 Subagent failure modes (all caught by independent verification)

- **Volume units.** An agent read OKX `volCcy24h` (QUOTE currency) as USD.
  USDT/TRY reported as "$470M" is really **$9.9M**. Kraken figures were ~3x
  high too. **Always recompute notional yourself: base_volume × price × fx.**
- **"Fabricated" over-called.** GBPT, A$DC, CADC, AUDF, CNHC, AE Coin are REAL
  — just not on reachable venues. "No CoinGecko hit + not on our 3 venues"
  ≠ "does not exist". The genuinely fictional: FedNow (a payment rail),
  RubleRogue, KZT-CNH, SAR-X, KRW-C, THBD, ARS-Crypto, EEUR, XAUD, CADT,
  CNHX, RAK-AED, UAED, USGD.
- **"It works" without evidence.** The Binance.US trades adapter was reported
  working; it produced 0 rows in 300s. Root cause was the venue, not the code
  — but only a control test (depth20 → 103 frames vs @trade → 0 on the SAME
  socket) proved it.
- **Reporting stale state.** An agent reported 4 failing tests that were
  already fixed. Re-verify before acting on a status claim.
- **Wrong-cwd writes.** Agents created `D:\tradekit-data\ticks\.ruff_cache`
  (twice) and `scripts/docs/hud/hud.html`. Tell agents their cwd explicitly.

**The pattern: every subagent bug was found by re-running its work, never by
reading its report.** Budget for verification; it is not optional.

### 3.3 Pre-existing bugs found (not introduced this session)

- **`collect_ticks.py` had NO time-based flush.** `FLUSH_INTERVAL_S` was
  defined, documented, and never used. Only 8 of 56 pairs ever wrote. Quiet
  pairs held rows in RAM (lost on crash) and were **mis-filed into the flush
  hour's file**. Historical thin-pair hour attribution is unrecoverable.
- **`verify_pairs` compared REST `wsname` (XBT) to WS v2 symbols (BTC)** —
  every BTC pair would have been silently dropped.

### 3.4 Dead code — REMOVED

`_next_part` had a `try/except ValueError` around the part-index `int()`.
`part_files` only returns `_PART_RE` matches, whose index is `\d{4}`, so the
parse could never fail. **Removed 2026-08-09**, replaced with a comment
stating the invariant. No behaviour change; suite still green.

### 3.5 Logs were empty because of stdout buffering

The original watchdog comment said collectors "die silently from time to time
(empty logs)". The logs were empty because **Python block-buffers stdout when
redirected**, so a killed process loses everything it printed. Fixed by
launching with `python -u`. Logs now populate. **This is why the historical
deaths were never diagnosable.**

### 3.6 The watchdog scheduled task was silently FAILING

Found 2026-08-09. `LastTaskResult: 2147942402` (= `0x80070002`,
ERROR_FILE_NOT_FOUND) on every 15-minute run. Cause: the action executed
`pwsh`, which on this machine resolves only to a Microsoft Store
**app-execution alias** (a zero-byte reparse point) that does not resolve in
a Task Scheduler context. Collectors survived only because nothing happened to
kill them; **compaction did not run for ~9.5 hours** (backlog took 1048s to
clear). Fixed by repointing the action at the full path to
`C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe`; verified
`LastTaskResult: 0` and a scheduled-task-driven relaunch of all 8 collectors.

**Check `LastTaskResult` whenever anything looks stale. A green-looking
"Ready" state says nothing about whether the last run succeeded.**

---

## 4. Asset insights worth keeping

### 4.1 Decisions made
- **BASE has no token.** Launched deliberately tokenless on ETH gas; Coinbase
  moved to "exploring" Sept 2025, still nothing confirmed. Express the thesis
  via **AERO** (~50-60% of Base DEX volume), **COIN** (equity), **USDC**, ETH.
  Base left the OP Stack in Feb 2026 — an argument against OP as a Base proxy.
- **ACX refused.** Risk Labs is converting the token to C-corp equity — the
  series has a scheduled death. Do not add it.
- **CAKE kept as a reference series.** NOT abandoned ($2.69B weekly DEX volume
  Jun-2026, supply cap cut to 400M Jan-2026). Its thin US tape is a venue
  artifact. The Binance archive will give its real tape.
- **ZEC** is #5 on Hyperliquid by open interest ($207M) and 3rd most liquid
  thing we collect. Shielded pool 8%→31%, Grayscale ETF filed.
- **Binance.US retired** for OKX (numbers in §2).

### 4.2 Stablecoin/FX reality (measured 2026-08-08, TRUE USD notional)

Deepest first: USDT/USD $34.9M · USDC/USD $16.0M · **USDC/EUR $13.0M
(15,513 trades — busiest in the sleeve)** · USDC/USDT $9.2M ·
**USDT/TRY $9.9M (OKX — the capital-controls instrument)** · USDT/EUR $4.4M ·
USDT/JPY $4.3M (but only 64 trades at 40bp) · USDC/GBP $4.0M ·
USDT/BRL $3.5M.

Perplexity's list surfaced 4 tradeable tokens our own scan missed and are now
collecting: **AUDF, BRL1, MXNB, EURQ** (all very thin, coverage only).

### 4.3 The arbitrage premise — honest read

Liquidity is NOT the constraint; **fees are**. Spreads on the deep pairs are
0.1–2.3 bps. Retail taker fees are 10–40 bps, paid twice on a round trip. You
need a **20–80 bps dislocation** to clear costs, not the 1–2 bps quoted spread.
Outside ~8 deep pairs, a $500 clip is 2–10% of daily volume.

**Nobody has yet measured whether cross-venue premium actually reaches that.**
That synchronised multi-venue snapshot is the cheap experiment that decides
whether any of this is real. Do it before deploying capital.

### 4.4 Pasture rotation (designed, NOT implemented)

Tier 0 always-on for deep reference legs. Tier 1 rotated by UCB1:
`score_i = mean_deviation_i + sqrt(2 ln(t) / n_i)`. Cold-start with a coprime
stride (`gcd(k,N)=1` visits all N in N steps, scattered, so a pair that only
dislocates at 09:00 UTC is not permanently sampled at the wrong hour).
**Critical refinement: score deviation NET of estimated round-trip cost**, or
the bandit concentrates on the widest-spread pairs, which are wide precisely
because they are untradeable.

### 4.5 Alpaca specifics
Real-time SIP = paid plan. Historical SIP = free at **T-15min** (403 inside
that window). Both tiers go back ~9 years, so **the $100/mo upgrade buys
real-time only — not history. Not worth it for an archive.**
Measured: trades ~2 MB/symbol/day; NBBO quotes ~10-15 MB/symbol/day.

---

## 5. Discussed but NOT acted on

| Item | Status / reasoning |
|---|---|
| Geolock circumvention (virtual numbers, UAE accounts) | **Declined.** Those blocks implement US regulatory settlements; it means false attestations at signup and funds with no recourse. Unnecessary anyway — `data.binance.vision`, cryptohftdata and CoinGecko already deliver the data legally. |
| Bug-bounty automation (Playwright fuzzing) | Not built. Automated scanning outside a declared scope breaks most programs and is legally risky. Also Hyperliquid pays in USDC **on Hyperliquid**, which Mike cannot receive — that program pays nothing even on a win. |
| cryptohftdata via Playwright scraping | Unnecessary — it is already a plain REST API we have working access to. The ~2025-06-29 floor is SERVER-side; scraping cannot reach data the backend lacks. |
| RWA expansion (FIGR_HELOC, USYC, BUIDL, syrupUSDC, GRO…) | Researched, not added. Most are permissioned//institutional with no public order book — they have NAV, not a tradeable tape. Only PAXG/XAUT/ONDO/CFG are collectable, and all 4 already are. |
| Watchlist tokens (real, unreachable) | FRAX, GUSD, EURS, EURT, VEUR, CADD, CADC, CNHC, AE Coin, BRZ, GBPT, A$DC, JPYC, GYEN, KRWQ, TRYB, IDRX, IDRT, ZARP, ZARU, PHPC, cNGN, EURCV, EURI, EURE, EURAU, CHFAU, ZCHF, VCHF. Re-check listings periodically. |
| `fundingHistory` reconciliation | Hyperliquid collector does not backfill/reconcile funding. Endpoint is known-good. |
| Retention policy | `RETENTION_DAYS = 730` in `collect_ticks.py` is now unreachable — disk fills in ~193 days first. Decide: shorter retention, or more disk (Mike is adding drives). |
| Concurrent-sink race | Two SIMULTANEOUS sinks on one tree could still collide on a part number. Not reachable today (each collector owns its tree; watchdog will not double-launch). Left unfixed deliberately. |
| Compaction blocks the watchdog | `compact_archive.py` runs with `-Wait`. Steady state ~1-2s, but the 9.5h backlog took 1048s, during which collectors were not checked. Collector checks run FIRST, so it degrades gracefully. Consider making it async if backlogs recur. |

---

## 6. Uncommitted tree — READ BEFORE `git`

26 dirty paths, all this session's work, **all green (1314 passed, ruff
clean)**. Nothing is committed. Includes:
- Modified: `collect_ticks.py`, `collect_books_{coinbase,binance}.py`,
  `collector_watchdog.ps1`, 2 test files, `cc-dev-log.md`, `docs/FRICTION.md`
- New: `collector_core.py`, `compact_archive.py`, `migrate_layout.py`,
  5 collectors, 2 backfillers, 2 test files

Two unrelated strays, NOT from collector work — decide and clean:
- `docs/hud/hud.html` — modified, but it is regenerated HUD report output
  (different limit prices), not a code change.
- `scripts/docs/hud/hud.html` — stray duplicate from a subagent running with
  the wrong cwd. Almost certainly safe to delete.

---

## 7. Next actions (ordered)

1. **Commit this tree** before anything else. It is green but a single
   `git checkout` would destroy a full session of work.

2. **Start the Binance archive backfill.** Biggest untapped source; the
   world's deepest venue, history to 2017, and we currently use 0% of it.
   ```bash
   uv run python scripts/backfill_binance_archive.py \
       --market spot --datatype aggTrades \
       --start 2026-01-01 --end 2026-08-08 --dry-run      # inspect the plan
   # then re-run with --no-dry-run
   ```
   Sizing: ~7 MB/symbol/day compressed, ~9.4 MB/symbol/day as parquet.
   ~15-25 MB/day for a 30-symbol basket → **6-9 GB/year**. Start with
   aggTrades; then `--market um --datatype metrics` (5-min OI + long/short
   ratios) and `bookTicker`. **Watch disk** — see §5 retention.
   Gotcha already handled: spot klines timestamps are MICROseconds, futures
   are MILLIseconds; detection is by magnitude, never per-market assumption.

3. **Repair the July book gaps.** Real, confirmed: ETH/USD and SOL/USD are
   missing a 53-hour span from 2026-07-19 23h, and there are 72 missing hours
   for ETH/USD overall (~572 MB).
   ```bash
   uv run python scripts/backfill_books_chd.py --pair ETH/USD --pair SOL/USD
   # inspect, then --no-dry-run
   ```
   The gap window sits INSIDE both cryptohftdata bounds (after the
   2025-06-29 floor, before the ~11-day recent lag) — so it is fillable now,
   but the recent-lag boundary moves daily. Do not defer indefinitely.

4. **ETF NBBO — see §8. Recommendation: enable for IBIT and GLD only.**

5. Decide retention vs. disk (§5).

---

## 8. ETF vs. crypto — is there an edge?

Asked directly; here is the honest answer.

**Mechanism.** Spot BTC ETFs (IBIT/FBTC/GBTC) hold real BTC. Share price
should track NAV. Authorized Participants create/redeem in blocks and arb the
gap away. **Retail cannot create or redeem** — only APs can. So the
premium/discount on a liquid ETF is usually a few bps precisely *because*
it is already arbitraged, and it is not directly capturable by us.

**Where the real structure is — and this one we CAN measure:**
- **Crypto trades 24/7; ETFs trade 09:30–16:00 ET.** Overnight and across
  weekends the ETF price is stale against spot, and it reprices at the open.
  That gap is large, recurring, and predictable in sign. It is not
  "arbitrage" (you cannot trade a closed ETF) but it is a tradeable *signal*,
  and we are one of the few setups that can measure it properly because we
  hold 24/7 crypto ticks AND full SIP equity ticks on the same clock.
- **Stress events**, where the AP mechanism strains and the gap genuinely
  blows out. GBTC is the historical proof: as a closed-end trust that could
  not redeem, it traded to a ~-49% discount in 2022, which collapsed on ETF
  conversion in Jan 2024. That was one of the trades of the cycle, and it
  existed *because* the arb mechanism was absent.

**So do we need NBBO right now?** Mostly no. **Trades alone** are enough to
measure premium/discount and the overnight gap — that is the characterisation
work, and it is already collecting at ~2 MB/symbol/day. NBBO only matters once
you intend to *execute*, because then the spread and quoted size decide
whether the measured edge survives contact.

**Recommendation: turn quotes on for IBIT and GLD only** (~25 MB/day):
- **IBIT** — most liquid BTC ETF, the one you would actually trade, and the
  cleanest counterpart to our BTC/USD tape.
- **GLD** — PAXG/XAUT vs GLD is the cleanest RWA basis in the whole archive,
  and gold ETF quotes are extremely tight, so the basis is meaningful.

Skip NBBO on MARA/RIOT/HOOD entirely — those are equity beta with a crypto
correlation, not basis instruments.

```powershell
# In scripts/collector_watchdog.ps1, change the alpaca row's launch to add:
#   --quotes IBIT,GLD
```

---

## 9. Health at handoff (2026-08-09 ~07:40 UTC)

All 8 streams live, relaunched by the SCHEDULED TASK (not manually), logs
populating for the first time.

| stream | symbols |
|---|---|
| ticks | 76 |
| books/coinbase | 52 |
| books/okx | 51 |
| trades/coinbase | 48 |
| trades/okx | 37 |
| liquidations/okx | 38 |
| perps/hyperliquid | 232 |
| equities/alpaca | 10 |

- gate: **1314 passed**, ruff clean
- disk: **8.6 GB used, 458 GB free**
- burn: **~2.55 GB/day → ~193 days** (depends on compaction running — verify
  `LastTaskResult: 0`)
- compaction: caught up (2,817,445 rows merged after the 9.5h outage)
