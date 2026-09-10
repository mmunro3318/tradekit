# scripts/register_tasks_s4u.ps1 — re-register the two tradekit scheduled
# tasks so they fire from a LOGGED-OUT desktop (S4U principal: runs as
# `admin` without a stored password, no interactive session required).
#
# Why (docs/research/data-health-2026-09-10-reboot.md): both tasks were
# `Logon Mode: Interactive only`, so a Windows Update reboot on 2026-09-09
# left the machine at the login screen for 6h25m and every collector stream
# plus seven hourly cadence runs were lost. `Set-ScheduledTask -Principal`
# needs an ELEVATED shell ("Access is denied" otherwise) — launch this file
# with:
#
#   Start-Process pwsh -Verb RunAs -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-File','C:\Users\admin\dev\tradekit\scripts\register_tasks_s4u.ps1'
#
# and click Yes on the UAC prompt. The script is idempotent; re-running it
# is harmless. It changes ONLY the principal (both tasks) and, for the
# cadence, the action to an absolute `uv.exe` path with an explicit working
# directory (a user-PATH `uv` is not guaranteed without a loaded profile —
# docs/FRICTION.md 2026-08-10). Triggers and settings are untouched.

$ErrorActionPreference = "Stop"

$uv = "C:\Users\admin\AppData\Local\hermes\bin\uv.exe"
$repo = "C:\Users\admin\dev\tradekit"
if (-not (Test-Path $uv)) { throw "uv.exe not found at $uv — update the path in this script first" }

$principal = New-ScheduledTaskPrincipal -UserId "admin" -LogonType S4U -RunLevel Limited

Set-ScheduledTask -TaskName "TradeKit Collector Watchdog" -Principal $principal | Out-Null

$action = New-ScheduledTaskAction -Execute $uv -Argument "run python scripts\run_cadence.py" -WorkingDirectory $repo
Set-ScheduledTask -TaskName "TradeKit Paper Cadence" -Principal $principal -Action $action | Out-Null

foreach ($name in "TradeKit Collector Watchdog", "TradeKit Paper Cadence") {
    $t = Get-ScheduledTask -TaskName $name
    $act = $t.Actions[0]
    "{0}: LogonType={1}  Action={2} {3}" -f $name, $t.Principal.LogonType, $act.Execute, $act.Arguments
}

"Now proving the watchdog runs under S4U (it only relaunches DEAD collectors, so this is safe):"
Start-ScheduledTask -TaskName "TradeKit Collector Watchdog"
Start-Sleep -Seconds 25
$info = Get-ScheduledTaskInfo -TaskName "TradeKit Collector Watchdog"
"Watchdog LastRunTime={0}  LastTaskResult={1}  (0 = good)" -f $info.LastRunTime, $info.LastTaskResult
"Paper Cadence: check (Get-ScheduledTaskInfo 'TradeKit Paper Cadence').LastTaskResult after the next top of the hour."
