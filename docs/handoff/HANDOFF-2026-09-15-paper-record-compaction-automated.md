# HANDOFF 2026-09-15 — paper-record-compaction-automated (sprint seed)

Supersedes `HANDOFF-2026-09-10-paper-record-r007-unlocked.md` (its "what is
now law" section still holds; do not re-derive ASSUMPTIONS 181/182).

## State (auto-captured, corrected by hand at the seam)
- branch: `main`  anchor: `877b011`  (pushed to origin; tree clean except
  `docs/FRICTION.md` addendum committed with this seed and the hourly digests)
- last gate: green @ 7cebda3 + 9600399 (1474 tests, ruff, mypy)
- Both scheduled tasks S4U; a second Windows Update reboot on 2026-09-15
  recovered unattended in 12 min (Mike confirmed). Mike is researching a real
  update-deferral fix; not ours.
- `.worktrees/sizing-cap` can be removed (`git worktree remove .worktrees/sizing-cap`);
  `main` carries `feat(sizing-cap)` d8bd297.

recent commits:
```
877b011 chore(scripts): repair a backslash the heredoc edit turned into a carriage return
66c29cf chore(scripts): restore LF line endings in collector_watchdog.ps1
ef184e6 docs(digest): hourly paper-cadence digests 2026-09-10..15
9600399 feat(compaction): daily scheduled task + dead-holder lock takeover (GATE: green)
7cebda3 test(compact_batch): a lock left by a dead process is taken over (red)
```

## Mission
Keep the paper record flowing toward the 30-graded-trade T2 gate on the
now-verified funnel, and keep the archive healthy without Mike remembering
maintenance. Paper only. Live stays locked. Mike does not supply theses — the
funnel does.

## What the post-merge tape proved (digests 09-11..09-15)
- The sizing-cap fix works: 10 entries in four days (EIGEN, SOL, ETH, LINK,
  AKT, XRP, AVAX, NEAR, RENDER, TAO — s1_momentum and s2_pullback), zero
  `R-012` binding denials, zero R-007 self-locks (previews no longer count).
- 3 stop exits, each ~-$5 (TAO -5.13 on 09-11 00:00, LINK -4.99, RENDER -5.07
  on 09-11 11:00) = 1% of the $500 dial, as designed. Graded 1 -> 3.
- Open positions as of 09-15 08:00 UTC: SOL, ETH, LINK, AKT, XRP, AVAX, NEAR,
  RENDER, TAO (all s1/s2, entered 09-11..09-14). Only PAXG is prefilter-killed.
- Drought lines ("zero entries, zero exits") on hours with no signal are
  normal, not a defect.

## Compaction (Mike's decision 2, done this session)
- `scripts/compact_batch.py`: `archive_lock` recognises a lock whose holder pid
  is dead (ctypes `OpenProcess`/`GetExitCodeProcess` on Windows; never
  `os.kill(pid, 0)` there — it is `TerminateProcess`) and takes it over; a live
  or unreadable holder still raises `LockHeld` (exit 3). Banner timestamped.
- `scripts/register_compaction_task.ps1` registers `TradeKit Compaction`:
  S4U, daily 02:30 local, StartWhenAvailable, 2h limit, action
  `cmd.exe /c uv.exe run --group collector python scripts\compact_batch.py
  --days 3 --execute --max-seconds 1800 >> D:\tradekit-data\logs\compaction.log`.
  **MIKE runs it elevated** (command in the file header; UAC yes). Its proof
  run reports 3 if the catch-up loop below is still running — expected.
- `D:\tradekit-data\COMPACTION-PAUSED` STAYS. Watchdog comment, archive README
  (repo + D: copy), `~/.claude/skills/tk-data-health` SKILL + runbook all say so.
- Catch-up loop launched detached 08:42 UTC (pid 32416, scratchpad
  `compaction_catchup.ps1`, per-day passes 08-20..09-15 then a bounded sweep,
  appending to `logs\compaction.log`). Days through 09-05 had nothing
  outstanding; 09-06 onward is real work at ~5 hours/s (~1 h per backlog day,
  so ~9-10 h total). Verify when done: dry run reports ~0 hours; `file` count
  drops; rows unchanged. If the loop died (reboot), just re-run
  `compact_batch.py --execute --max-seconds 3600` until it reports 0.

## Per-feature status
| feature | state | next action | blocking? |
|---|---|---|---|
| SPEC-sizing-cap | SHIPPED + verified on tape | nothing; watch grades as the 9 open positions close | no |
| Compaction automation | code shipped (9600399); task NOT yet registered | Mike: run `scripts\register_compaction_task.ps1` elevated; then check `Get-ScheduledTaskInfo 'TradeKit Compaction'` result 0 after 02:30 local | Mike's hands |
| Compaction backlog catch-up | RUNNING (pid 32416) | read `logs\compaction.log` tail; expect "CATCH-UP LOOP done" | no |
| `paper:prop` at $5k (decision 1) | Mike's reply was "asd" — treated as undecided | ask again; TAO closed 09-11 so the account is free, but 9 positions are now open — switching accounts mid-series needs a plan (let them close, or run both accounts) | Mike |
| R-007 exit exemption inside the rule (182.6) | known-open | tk-spec when convenient; money-path review | no |
| DEFAULT_SYMBOLS widening (B3) | CTO decision | 4 clean days of digests now exist; decide next session | no |
| Kraken trades backfill for the 09-10 blackout | dry-run clean (457ac39) | Mike says "run the Kraken backfill" | Mike's go |
| tk-data-health tooling (health_snapshot.ps1, coverage.py, audit_tree.py) | do not exist | sonnet batch, read-only tools | no |
| Windows Update deferral | Mike researching | none | no |
| Navigator artifact | seed unchanged: HANDOFF-2026-09-08-navigator-artifact.md | Mike forks a branch; tk-brainstorm | no |
| Data thread (Binance, Coinbase book backfill, Alpaca NBBO, retention) | untouched | separate sprint | no |

## Forks / parallel work in flight
- Compaction catch-up loop (detached pwsh, pid 32416) — the only thing running.
  No agents mid-batch. Tree committed and pushed.
- Tooling lesson from this session (memory `bash-heredoc-unescapes-backslashes`):
  the Bash tool turns `\n`/`\r`/`\t` inside heredoc text into real bytes — use
  Edit/Write for anything with a backslash. Two pre-existing `D:<TAB>radekit-data`
  typos (ROADMAP ~289, ARCHIVE-README header) are the same defect, left as found.

## Next actions (ordered)
1. Confirm the catch-up finished (`logs\compaction.log` "CATCH-UP LOOP done";
   dry run ~0 hours). Then Mike registers the task; check its first 02:30 run.
2. Read the newest digests: grades as the 9 open positions close; any denial
   line is a defect (tk-friction + red test first).
3. Get decision 1 properly: `paper:prop` at $5k and the prop eval's DD %/target
   for R-017/R-018 — or explicitly park it.
4. B3 DEFAULT_SYMBOLS widening decision (4 clean days in hand).
5. With Mike's go: Kraken trades backfill (no dry-run).
6. R-007 exit exemption pin (182.6); data-health tooling batch; data thread.
