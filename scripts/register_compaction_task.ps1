# scripts/register_compaction_task.ps1 — register the daily archive
# compaction as a Windows scheduled task, `TradeKit Compaction`.
#
# Why: compaction came off the 15-minute watchdog on 2026-08-23 because that
# pass re-walked the whole archive to find work (up to 671 s merging nothing
# and overrunning its own schedule). `scripts\compact_batch.py` replaced it —
# bounded, scoped, resumable — but as a MANUAL job, which by 2026-09-15 meant
# a multi-week backlog whenever nobody remembered. This task runs the exact
# bounded pass the compaction runbook recommends, once a day:
#
#   compact_batch.py --days 3 --execute --max-seconds 1800
#
# `--days 3` keeps discovery cheap and covers anything a missed run left;
# `--max-seconds 1800` guarantees it cannot overrun. A run that stops early
# resumes next day (the work list is rediscovered from disk). A reboot
# mid-run leaves a lock the next run recognises as dead and takes over.
# `D:\tradekit-data\COMPACTION-PAUSED` stays: it gates only the watchdog's
# legacy unbounded pass, not this command.
#
# S4U principal (fires from a logged-out desktop, no stored password) needs an
# ELEVATED shell — launch this file with:
#
#   Start-Process pwsh -Verb RunAs -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-File','C:\Users\admin\dev\tradekit\scripts\register_compaction_task.ps1'
#
# and click Yes on the UAC prompt. Idempotent (-Force re-registers in place).
# The proof run at the end is a REAL bounded pass; if a manual catch-up loop
# is still running it reports LastTaskResult=3 (lock held by a live run) —
# that is correct behaviour, re-run the proof once the loop finishes.

$ErrorActionPreference = "Stop"

$uv = "C:\Users\admin\AppData\Local\hermes\bin\uv.exe"
$repo = "C:\Users\admin\dev\tradekit"
$log = "D:\tradekit-data\logs\compaction.log"
$taskName = "TradeKit Compaction"
if (-not (Test-Path $uv)) { throw "uv.exe not found at $uv — update the path in this script first" }
if (-not (Test-Path (Split-Path $log))) { throw "log directory for $log does not exist — is D: mounted?" }

# cmd.exe carries the redirect: a scheduled action has no stdout of its own.
$cmdLine = "`"$uv`" run --group collector python scripts\compact_batch.py --days 3 --execute --max-seconds 1800 >> `"$log`" 2>&1"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $cmdLine" -WorkingDirectory $repo

# 02:30 local: the cadence fires at the top of every hour and finishes in
# seconds, the watchdog every 15 min; neither contends for the archive.
$trigger = New-ScheduledTaskTrigger -Daily -At 02:30
$principal = New-ScheduledTaskPrincipal -UserId "admin" -LogonType S4U -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

$t = Get-ScheduledTask -TaskName $taskName
"{0}: State={1} LogonType={2}" -f $taskName, $t.State, $t.Principal.LogonType
"  action: {0} {1}" -f $t.Actions[0].Execute, $t.Actions[0].Arguments
"  trigger: daily at {0}  StartWhenAvailable={1}  limit={2}" -f `
    $t.Triggers[0].StartBoundary, $t.Settings.StartWhenAvailable, $t.Settings.ExecutionTimeLimit

"Now proving it runs under S4U (a real bounded pass; safe alongside live collectors):"
Start-ScheduledTask -TaskName $taskName
Start-Sleep -Seconds 45
$info = Get-ScheduledTaskInfo -TaskName $taskName
"LastRunTime={0}  LastTaskResult={1}  (0 = good; 267009 = still running; 3 = lock held by another run)" -f `
    $info.LastRunTime, $info.LastTaskResult
"log tail ($log):"
Get-Content $log -Tail 4
