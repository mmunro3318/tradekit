<!-- CANONICAL COPY. The working copy lives at D:	radekit-data\README.md so the
     drive is self-describing. Edit this one, then copy it across — a recovery
     document that exists only on the drive it recovers is not a recovery document.
     Re-copy it whenever the archive drive is swapped. -->

# TradeKit market-data archive

This drive holds the raw market-data archive collected by
[`tradekit`](file:///C:/Users/admin/dev/tradekit). Everything under
`D:\tradekit-data\` is written by eight always-on collector processes; nothing
in it is derived, aggregated or back-filled by hand.

The differentiator is deliberately **not** OHLCV — Kraken and CryptoDataDownload
publish that for free. It is **L2 order-book depth on a shared clock across
venues**, plus the things nobody gives away: perpetual funding and open
interest, forced liquidations, and cross-asset equity/ETF alignment against
24/7 crypto.

*Snapshot taken 2026-08-10 23:30 UTC. Row counts move constantly; the structure
does not.*

| | |
|---|---|
| coverage | 2026-07-19 → present, continuous except the gaps in §5 |
| rows | ~58.6 million |
| parquet files | 52,971 |
| size | 4.22 GB |
| venues | Kraken, Coinbase, OKX, Hyperliquid, Alpaca (SIP) |
| format | Parquet, zstd level 3 |

---

## 1. What is on the drive

```
D:\
├── tradekit-data\            <- the archive. Everything below is ours.
│   ├── ticks\                     Kraken   trades + L10 book
│   ├── books\coinbase\            Coinbase L20 book
│   ├── books\okx\                 OKX      L20 book
│   ├── trades\coinbase\           Coinbase trades
│   ├── trades\okx\                OKX      trades
│   ├── perps\hyperliquid\         Hyperliquid funding/OI/mark + trades
│   ├── liquidations\okx\          OKX      forced liquidations, venue-wide
│   ├── equities\alpaca\           Alpaca   SIP equity prints
│   ├── logs\                      one log per collector + watchdog + compaction
│   └── sample-data-cryptostruct\  VENDOR SAMPLES, not collected by us (742 MB)
├── Hermes\                   <- unrelated to tradekit
└── notes.md                  <- unrelated to tradekit
```

`sample-data-cryptostruct\` is third-party sample data downloaded for
evaluation. It is **not** part of the archive and is not maintained. It can be
deleted without loss.

## 2. Path grammar

```
<tree>\<asset-class>\<SYMBOL>\<YYYY-MM-DD>\<stream>-<HH>.parquet
```

- `<asset-class>` — `crypto`, `stables`, `fx`, `cross`, `rwa`. The BASE asset
  decides `stables` (peg monitoring) and the QUOTE decides `cross` (a basis
  series). `USDC/USD` is stables; `BTC/USDT` is cross, not stables.
- `<SYMBOL>` — the venue symbol with `/` and `:` replaced by `_`
  (`BTC/USD` → `BTC_USD`).
- `<YYYY-MM-DD>` and `<HH>` are **UTC**, and are derived from **the row's own
  timestamp** — not from when we received or wrote it. See §4.
- `equities\alpaca\` has **no** `<asset-class>` level. The venue tree is the
  asset class there.

During the current hour you will also see `<stream>-<HH>.part-NNNN.parquet`.
Those are append-only fragments; `compact_archive.py` merges them into the
single hourly file once the hour closes. Both forms are valid Parquet and can
be read directly.

Example:

```
D:\tradekit-data\ticks\crypto\BTC_USD\2026-08-08\book-04.parquet
D:\tradekit-data\books\coinbase\stables\USDC_EUR\2026-08-09\book-13.parquet
D:\tradekit-data\equities\alpaca\IBIT\2026-08-10\trades-14.parquet
```

## 3. The eight streams

| tree | stream | symbols | rows | since | tree size | schema |
|---|---|---|---|---|---|---|
| `ticks` | `book` | 77 | 18,442,892 | 07-19 | 1.03 GB | `ts` + L10 × (bid/ask price+qty) = 41 cols |
| `ticks` | `trades` | 77 | 1,853,012 | 07-19 | ″ | `ts, price, qty, side, ord_type` |
| `books\coinbase` | `book` | 53 | 15,442,757 | 07-26 | 1.89 GB | `ts` + L20 = 81 cols |
| `books\okx` | `book` | 51 | 3,896,821 | 08-08 | 408 MB | `ts` + L20 = 81 cols |
| `trades\coinbase` | `trades` | 51 | 2,275,221 | 07-31 | 37 MB | `ts, price, qty, side, trade_id` |
| `trades\okx` | `trades` | 50 | 1,374,389 | 08-08 | 19 MB | `ts, price, qty, side, trade_id` |
| `perps\hyperliquid` | `ctx` + `trades` | 232 | 8,935,461 | 08-08 | 255 MB | `ts, coin, funding, open_interest, open_interest_usd, mark_px, oracle_px, premium, mid_px, day_ntl_vlm` |
| `liquidations\okx` | `liquidations` | 451 | 16,611 | 08-08 | 10 MB | `ts, inst_id, inst_family, inst_type, pos_side, side, …` |
| `equities\alpaca` | `trades` | 10 | 6,403,655 | 08-03 | 92 MB | `ts, price, qty, exchange, conditions, tape, trade_id` |

Sizes are per tree, so the two `ticks` streams share one figure.

Notes that matter when you query this:

- **Book rows are snapshots, not deltas.** Each row is the full top-N at that
  instant. You do not need to replay anything.
- **Book rows are coalesced to 1 Hz on every venue.** That is a deliberate,
  ratified choice (see the repo's `tests/ASSUMPTIONS.md` §180): a cross-venue
  join is capped by the coarsest stream, so uniform 1 Hz is the honest
  resolution. Intra-second book dynamics are **not** in this archive and
  cannot be recovered.
- **Trades are never coalesced**, on any venue. Every print is here.
- `liquidations\okx` counts 451 "symbols" because it is a venue-wide feed —
  each instrument that has ever been liquidated gets a directory.
- `equities\alpaca` is the **delayed SIP** tape (T-15 min), which is the full
  consolidated tape, not IEX. Real-time SIP needs a paid plan; the history
  does not, and for an archive the delay is irrelevant.

## 4. How the pipeline works

```
              scripts\collect_ticks.py :: GREENLIST_PAIRS
                  (87 symbols — ONE source of truth)
                                |
   +----------------------------+----------------------------+
   |                            |                            |
LIVE COLLECTORS           BACKFILLERS                   MAINTENANCE
(8 processes)             (manual, batch)               (every 15 min)
   |                            |                            |
   v                            v                            v
collector_core.py         separate provenance          compact_archive.py
VenueSpec + runner        trees, never merged          merges closed hours
   |                      into the live tree
   v
PartitionedParquetSink
   |
   +--> <stream>-<HH>.part-NNNN.parquet      (during the open hour)
                    |
                    +--> compact_archive.py --> <stream>-<HH>.parquet
```

**Supervision.** One Windows scheduled task, `TradeKit Collector Watchdog`,
runs `scripts\collector_watchdog.ps1` at logon (2-minute delay) and then every
15 minutes forever. It relaunches only the collectors that have died, then runs
compaction. It is idempotent — running it when everything is healthy does
nothing.

**Each venue self-filters.** A collector calls the venue's own instrument list
and silently drops greenlist pairs that venue does not offer. That is why
OKX-only pairs and Coinbase-only pairs can share one greenlist.

### Invariants you can rely on

1. **A row's directory is derived from the row's own `ts`.** If a file is at
   `…\2026-08-08\book-04.parquet`, every row in it is stamped 2026-08-08 hour
   04 UTC. Verified continuously; the last full-archive audit found zero
   violations on every closed day.
2. **Writes are append-only and atomic.** Part files are written to a temp name
   and renamed into place. A crash mid-write leaves no half-file.
3. **`ts` is always the first column**, always UTC, always ISO-8601 with an
   offset or `Z`. Beware: it is a *string*, and ISO-8601 does not sort
   lexicographically across mixed fractional precision (`12:00:00Z` sorts after
   `12:00:00.5Z`). **Parse before sorting.**
4. **Nothing is ever rewritten in place** except by the offline repair tools in
   §6, which take an exclusive lock on the tree.

## 5. Known gaps and caveats

Read this before concluding the data is wrong.

- **Coinbase books start 2026-07-26**, not 07-19. Collection began then. There
  is no gap before that date — there is simply nothing, and never was.
- **2026-07-20 and 07-21 are missing** from `ticks` (~19 h of genuine outage,
  affecting ticks and books alike).
- **Streams begin on different dates.** See the `since` column in §3. `books\okx`,
  `trades\okx`, `perps` and `liquidations` all begin 2026-08-08.
- **One corrupt file, quarantined:**
  `books\coinbase\crypto\CAKE_USD\2026-08-08\book-05.parquet.corrupt-no-footer`
  — one hour of a thin pair, truncated mid-write by a since-removed
  read-modify-write sink. Renamed so tooling skips it; the bytes are kept in
  case anyone wants to attempt recovery. **Note:** naive readers that glob a
  whole directory rather than `*.parquet` will choke on it.
- **Duplicate rows on two trade streams:** `trades\coinbase` ~1.7% and
  `perps\hyperliquid` trades ~0.6%. They are byte-identical rows, not corrupt
  data and not loss. Hyperliquid's are reconnect replay; Coinbase's cause is
  still unidentified. De-duplicate on `(symbol, ts, trade_id)` if it matters.
- **Binance is absent by design.** Binance Global is geo-blocked here (live and
  `fstream`); Binance.US was retired for OKX after measuring 2,669 BTC
  prints/day against Kraken's 42,063. Binance history is reachable via
  `data.binance.vision` and, when back-filled, lands in a **separate** tree —
  vendor and self-collected provenance are never merged.

## 6. Replacing this drive

The archive root is **hard-coded** as `D:\tradekit-data` in
`scripts\collector_core.py` (`EXTERNAL_DATA_ROOT`). A replacement drive must
therefore satisfy two things:

1. it is assigned drive letter **`D:`**, and
2. it contains a directory named **`tradekit-data`**.

If either is untrue the watchdog **refuses to start any collector** and exits
non-zero, logging to `<repo>\data\logs\watchdog.log`. That guard is deliberate:
without it, `resolve_data_root()` silently falls back to `<repo>\data` and you
would get eight collectors writing to the C: drive with no error and an archive
split across two roots that nothing would surface for days.

**To swap in a new drive:**

```powershell
# 1. Stop collection cleanly.
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'collect_' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# 2. Swap the hardware. Assign the new disk letter D: in Disk Management,
#    or:  Set-Partition -DiskNumber <n> -PartitionNumber <n> -NewDriveLetter D
# 3. Create the root.
New-Item -ItemType Directory -Force 'D:\tradekit-data\logs'

# 4. Copy this README onto the new drive so it stays self-describing.
# 5. Start collecting again; the tree rebuilds itself from empty.
Start-ScheduledTask -TaskName 'TradeKit Collector Watchdog'

# 6. Confirm. LastTaskResult MUST be 0 — a "Ready" state means nothing.
Get-ScheduledTaskInfo -TaskName 'TradeKit Collector Watchdog' |
    Select-Object LastRunTime, LastTaskResult
```

**Each drive is a time slice.** Do not merge an old drive into a new one just
to have "everything in one place" — the day directories would interleave and
you would lose the ability to say which drive holds which period. Keep retired
drives intact and read-only, and record the date range each one covers. If you
do need a combined view, copy forward deliberately and re-run
`scripts\repartition_archive.py` afterwards to confirm the result still obeys
invariant §4.1.

**Offline repair tools** (in the repo's `scripts\`, all `--dry-run` by default,
all take an exclusive lock on the tree):

| tool | what it does |
|---|---|
| `repartition_archive.py` | re-files rows into the day/hour their own `ts` names; `--dedupe` also drops byte-identical rows |
| `downsample_book.py` | coalesces a book stream to 1 Hz; refuses `--stream trades` outright |
| `compact_archive.py` | merges closed-hour part files (also run automatically) |

Neither repair tool ever touches the current UTC day — a live collector owns
it. That is why a partition finishes the day *after* it is written.

## 7. After a reboot

The watchdog fires at logon (+2 min) and every 15 minutes thereafter. **It runs
only while `admin` is logged in** — a machine sitting at the login screen
collects nothing.

```powershell
# everything green?
Get-ScheduledTaskInfo -TaskName 'TradeKit Collector Watchdog' |
    Select-Object LastRunTime, LastTaskResult      # LastTaskResult must be 0

@(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'collect_' -and $_.CommandLine -match '\.venv' }).Count   # expect 8

Get-Content 'D:\tradekit-data\logs\watchdog.log' -Tail 5
```

Freshness is the real test — every stream should have written within a few
minutes:

```powershell
'ticks','books\coinbase','books\okx','trades\coinbase','trades\okx',
'perps\hyperliquid','liquidations\okx','equities\alpaca' | ForEach-Object {
  $f = Get-ChildItem -Recurse -File -Filter *.parquet "D:\tradekit-data\$_" |
       Sort-Object LastWriteTime -Descending | Select-Object -First 1
  "{0,-20} {1,6:N1} min ago" -f $_, ((Get-Date) - $f.LastWriteTime).TotalMinutes
}
```

`equities\alpaca` writing nothing is **correct** outside US market hours.

## 8. Where the rest lives

| what | where |
|---|---|
| collector + tool source | `C:\Users\admin\dev\tradekit\scripts\` |
| shared collector core | `scripts\collector_core.py` — read this first |
| the archive's ratified rules | `tests\ASSUMPTIONS.md` §179 (partitioning), §180 (1 Hz books) |
| architecture + venue facts | `docs\handoff\HANDOFF-2026-08-09-data-vacuum-expansion.md` |
| what broke and why | `docs\handoff\HANDOFF-2026-08-09-event-time-partitioning.md`, `docs\FRICTION.md` |
| running history | `cc-dev-log.md` |
