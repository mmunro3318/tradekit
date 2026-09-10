"""scripts/run_cadence.py — SPEC-cadence.md T3's hourly paper-cadence entry
point: a thin `main()` over the testable `tradekit.cadence.run_once()`.

Mike's structural red line (SPEC-cadence.md, header): every submitted trade
passes the FULL funnel; the cadence REFUSES to exist off-paper. That guard
lives in `run_once` itself (`CadenceAccountRefused`) — this script's only
job is to run it once and turn a refusal into a loud, script-friendly
failure (print + exit 2) instead of a raw traceback, per T3's interface pin.

Scheduler registration (T3 interface pin — NOT executed by this script or
by any test; Mike runs this by hand once, on the machine that should host
the hourly job):

    schtasks /create /tn "TradeKit Paper Cadence" /sc hourly ^
        /tr "cmd /c \"cd /d C:\\Users\\admin\\dev\\tradekit && ^
             uv run python scripts\\run_cadence.py\"" ^
        /st 00:00

(F8, review round 22: `schtasks`'s own `/tr` runs with an undefined working
directory — `uv run --project` alone left `uv` unable to resolve the
project's own relative paths under Task Scheduler; wrapping in `cmd /c "cd
/d ... && ..."` pins the working directory explicitly before `uv run` ever
starts, the same watchdog pattern the book harvesters already use for
their own scheduled relaunch.)

(watchdog pattern — same per-process-relaunch convention as the book
harvesters; `schtasks` re-launches this script every hour regardless of
whether the previous run exited 0, 1, or 2.)

2026-09-10 (post-reboot audit, docs/research/data-health-2026-09-10-reboot.md):
the registration above yields `Logon Mode: Interactive only`, so the task
cannot fire while the machine sits at the login screen — a Windows Update
reboot cost seven hourly runs and 6h25m of every collector stream. The
durable form is an S4U principal (runs logged-out, no stored password) with
the ABSOLUTE `uv` path, because a user-PATH `uv` is not guaranteed without
a loaded profile (docs/FRICTION.md 2026-08-10). Mike's hands, PowerShell:

    $p = New-ScheduledTaskPrincipal -UserId "admin" -LogonType S4U -RunLevel Limited
    $a = New-ScheduledTaskAction `
        -Execute "C:\\Users\\admin\\AppData\\Local\\hermes\\bin\\uv.exe" `
        -Argument "run python scripts\\run_cadence.py" `
        -WorkingDirectory "C:\\Users\\admin\\dev\\tradekit"
    Set-ScheduledTask -TaskName "TradeKit Paper Cadence" -Principal $p -Action $a

Verify after the next top of the hour: `(Get-ScheduledTaskInfo "TradeKit
Paper Cadence").LastTaskResult` is 0. A "Ready" state proves nothing.
"""

from __future__ import annotations

import sys
import traceback

from tradekit.cadence import CadenceAccountRefused, run_once


def main() -> int:
    """Exit 2: `CadenceAccountRefused` (the structural paper-only guard) —
    a loud, script-friendly refusal message, no traceback. Exit 1 (F8,
    review round 22): any OTHER unexpected exception — `run_once` itself
    already logged it into the digest (cadence's own F1) before re-raising,
    so this handler's only job is to keep the traceback visible on stderr
    for whoever's watching the scheduled task's own log, and to distinguish
    "refused" from "crashed" via a different exit code. Exit 0: a clean run
    (including an ordinary drought)."""
    try:
        run_once()
    except CadenceAccountRefused as exc:
        print(f"tradekit cadence refused: {exc}")
        return 2
    except Exception:
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
