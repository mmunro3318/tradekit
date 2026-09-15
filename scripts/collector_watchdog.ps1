# Collector watchdog (rewritten 2026-08-08): collectors die silently from time
# to time (empty logs — likely console-window/session kills, not crashes).
# Runs every 15 min via scheduled task; relaunches exactly the missing
# process(es). Per-process relaunch, never a combined .cmd — relaunching both
# when one survives would double a collector and race its parquet writes.
# Idempotent when everything is up.
#
# Adding a venue is one row in $Collectors. A script that does not exist yet is
# skipped rather than erroring, so half-built collectors can sit in the table.
#
# LAYOUT NOTE: every collector routes paths through collector_core.stream_dir,
# which honours PARTITION_BY_CLASS. Do not run this while migrating the tree.
$repo = 'C:\Users\admin\dev\tradekit'
$onD = Test-Path 'D:\tradekit-data'
$logRoot = if ($onD) { 'D:\tradekit-data\logs' } else { "$repo\data\logs" }
$procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'"
$stamp = (Get-Date).ToUniversalTime().ToString('s')

# script name -> log file stem. Order is cosmetic.
#
# Binance.US was RETIRED here on 2026-08-08 and replaced by OKX. It traded
# ~2,669 BTC prints/day (~$1.26M) against Kraken's 42,063 (~$90M), and its
# public WS trade channel published nothing at all (depth20 delivered 103
# frames in 240s on the same socket where @trade/@aggTrade delivered zero).
# Binance GLOBAL history still arrives via scripts/backfill_binance_archive.py,
# which is a separate batch job and deliberately not watchdogged.
$Collectors = @(
    @{ Script = 'collect_ticks.py';              Log = 'kraken-ticks' }
    @{ Script = 'collect_books_coinbase.py';     Log = 'coinbase-books' }
    @{ Script = 'collect_trades_coinbase.py';    Log = 'coinbase-trades' }
    @{ Script = 'collect_books_okx.py';          Log = 'okx-books' }
    @{ Script = 'collect_trades_okx.py';         Log = 'okx-trades' }
    @{ Script = 'collect_liquidations_okx.py';   Log = 'okx-liquidations' }
    @{ Script = 'collect_perps_hyperliquid.py';  Log = 'hyperliquid-perps' }
    @{ Script = 'collect_equities_alpaca.py';    Log = 'alpaca-equities' }
)

if (-not (Test-Path $logRoot)) { New-Item -ItemType Directory -Force $logRoot | Out-Null }

# REFUSE TO RUN WITHOUT THE ARCHIVE DISK. D: is a USB disk (JMicron bridge),
# and USB enumeration can lag a reboot. collector_core.resolve_data_root()
# falls back to <repo>\data when D:\tradekit-data is missing and says nothing
# about it, so a watchdog run that fires before the disk mounts would start
# all eight collectors writing to C: — no error, no warning, and an archive
# quietly split across two roots that nobody would notice for days.
#
# A gap in collection is recoverable; a split archive is not. Exiting non-zero
# is deliberate: it makes LastTaskResult non-zero, which is the one signal
# this project already knows to check.
if (-not $onD) {
    Add-Content -Path (Join-Path $logRoot 'watchdog.log') `
        -Value "$stamp D:\tradekit-data not mounted - refusing to launch collectors"
    exit 1
}

function Test-Collector([string]$script) {
    # Match the bare script name so a path-qualified launch still counts.
    $pattern = [regex]::Escape($script)
    return [bool]($procs | Where-Object { $_.CommandLine -match $pattern })
}

function Start-Collector([string]$script, [string]$log) {
    Add-Content -Path (Join-Path $logRoot 'watchdog.log') -Value "$stamp $script down - relaunching"
    # python -u: UNBUFFERED. Python block-buffers stdout when it is redirected
    # to a file, so a collector that is killed loses everything it ever
    # printed. That is why the original note here said collectors "die
    # silently from time to time (empty logs)" — the logs were empty because
    # the buffer died with the process, not because nothing was written.
    # Without -u the logs cannot diagnose anything.
    Start-Process -WindowStyle Hidden -WorkingDirectory $repo cmd.exe `
        -ArgumentList '/c', "uv run --group collector python -u scripts\$script >> `"$log`" 2>&1"
}

foreach ($c in $Collectors) {
    $path = Join-Path $repo "scripts\$($c.Script)"
    if (-not (Test-Path $path)) { continue }   # not built yet — skip quietly
    if (Test-Collector $c.Script) { continue } # already up
    Start-Collector $c.Script (Join-Path $logRoot "$($c.Log).log")
}

# Merge finished part files into one file per closed hour. Idempotent and it
# skips the current hour, so it is safe to run alongside live collectors.
# Without this the archive accumulates enormous numbers of tiny parquet files
# whose fixed per-file overhead dwarfs the data (measured 6 rows/file on the
# 232-asset perps stream).
#
# PAUSED 2026-08-23 while the sentinel below exists. The pass discovered its
# work by re-walking the whole archive, so its cost tracked archive size and
# not backlog: at 263k files, runs that merged NOTHING were taking up to 671 s
# against this 15-minute schedule, and the day's run count had slipped from 96
# to 92 — i.e. runs were starting to overrun each other. Compaction is now a
# manual, bounded, scoped job: scripts\compact_batch.py.
#
# Deferring it loses nothing. Part files are self-contained parquet, the sink
# seeds its part counter from disk so a restart never reuses an index, and
# compact_hour merges any pre-existing hourly file together with the parts.
# The cost is purely file count (~2,800 parts/hour). Since 2026-09-15 the
# daily scheduled task `TradeKit Compaction` (scriptsegister_compaction_task.ps1)
# runs a bounded compact_batch.py pass; the sentinel below stays so THIS
# unbounded pass never comes back. Do not delete it to "automate" compaction.
# A replacement drive starts without one: recreate it before the first
# watchdog run, then register the task.
$compactionPaused = Join-Path 'D:\tradekit-data' 'COMPACTION-PAUSED'
if ((-not (Test-Path $compactionPaused)) -and (-not (Test-Collector 'compact_archive.py'))) {
    $compactLog = Join-Path $logRoot 'compaction.log'
    Start-Process -WindowStyle Hidden -Wait -WorkingDirectory $repo cmd.exe `
        -ArgumentList '/c', "uv run --group collector python scripts\compact_archive.py >> `"$compactLog`" 2>&1"
}
