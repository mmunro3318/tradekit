# Collector watchdog (2026-07-26): collectors die silently from time to
# time (empty logs — likely console-window/session kills, not crashes).
# Runs every 15 min via scheduled task; relaunches exactly the missing
# process(es). Per-process relaunch, never the combined Startup .cmd —
# relaunching both when one survives would double a collector and race
# its parquet read-concat-write flushes. Idempotent when everything is up.
$repo = 'C:\Users\admin\dev\tradekit'
$startup = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
$onD = Test-Path 'D:\tradekit-data'
$logRoot = if ($onD) { 'D:\tradekit-data' } else { "$repo\data" }
$procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'"
$stamp = (Get-Date).ToUniversalTime().ToString('s')

function Test-Collector([string]$pattern) {
    return [bool]($procs | Where-Object { $_.CommandLine -match $pattern })
}

function Start-Collector([string]$script, [string]$log) {
    $dir = Split-Path $log
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
    Add-Content -Path (Join-Path $logRoot 'watchdog.log') -Value "$stamp $script down - relaunching"
    Start-Process -WindowStyle Hidden -WorkingDirectory $repo cmd.exe `
        -ArgumentList '/c', "uv run python scripts\$script >> `"$log`" 2>&1"
}

if (-not (Test-Collector 'collect_ticks')) {
    # Tick collector keeps its original launcher (single-process .cmd).
    Add-Content -Path (Join-Path $logRoot 'watchdog.log') -Value "$stamp collect_ticks.py down - relaunching"
    & "$startup\tradekit-tick-collector.cmd"
}
$booksLog = if ($onD) { 'D:\tradekit-data\books' } else { "$repo\data\books" }
if (-not (Test-Collector 'collect_books_binance')) {
    Start-Collector 'collect_books_binance.py' "$booksLog\binance-collector.log"
}
if (-not (Test-Collector 'collect_books_coinbase')) {
    Start-Collector 'collect_books_coinbase.py' "$booksLog\coinbase-collector.log"
}
