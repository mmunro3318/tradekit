# HANDOFF 2026-09-10 — paper-record-r007-unlocked (sprint seed)

## State (auto-captured, corrected by hand at the seam)
- branch: `feature/sizing-cap` was built in worktree `.worktrees/sizing-cap`
  and FAST-FORWARDED into `main` at the end of this session (the green
  commit sits on top of `457ac39`; `git log --oneline -3` on `main` shows
  it). The worktree can be removed (`git worktree remove .worktrees/sizing-cap`)
  once a fresh session confirms `main` carries `feat(sizing-cap)`.
- last gate: green @ 457ac39 + the green commit (1471 tests, ruff, mypy).
- The hourly task `TradeKit Paper Cadence` trades the CHECKED-OUT tree of
  `C:\Users\admin\dev\tradekit` (`main`). From the first top-of-hour after
  the merge it trades the fix. Both scheduled tasks now run as S4U (Mike,
  2026-09-10 02:44 PDT, `scripts/register_tasks_s4u.ps1`, elevated): they
  fire from a logged-out desktop. Watchdog and cadence both verified
  `LastTaskResult 0` under S4U.
- `docs/digest/DIGEST-<UTC date>.md` is appended hourly — expect it dirty in
  the main tree; commit digests at seams only.

recent commits (before the green commit):
```
457ac39 fix(scripts): backfill_ticks sees .part fragments and the partitioned layout; S4U task registration; run_cadence header
cd0f29f test(hud,thesis,cadence): one sizing basis through the real funnel — T1/T2 reproductions, dial basis, dead-account warning (red)
b882ece test(mae,policy): size_position price+max_position_usd clip, PolicyDials.paper_max_position_usd (red)
759de9e docs: TASKS-sizing-cap, ROADMAP sizing-cap + reboot follow-ups, FRICTION
77715cc docs(spec): SPEC-sizing-cap — one sizing basis (price/equity/cap)
```

## Mission
Keep the paper record flowing toward the 30-graded-trade T2 gate now that
the two structural blockers are gone: (1) the funnel's two sizing calls
disagreed (live equity + 1h price at preview vs dial equity + daily close at
submit) so R-005 denied at preview and R-012 rejected at binding almost
every candidate; (2) every scan-time preview ledgered an `ActionProposed`
that R-007 counted as a trade, so the paper account self-locked after 20
previews each UTC day with zero trades (`R-007: 21 vs 20`). Both shipped
this session (SPEC-sizing-cap, ASSUMPTIONS 182.1-12, review rounds 24/25).
Paper only. Live stays locked. Mike does not supply theses — the funnel does.

## What is now law (do not re-derive)
- ONE sizing basis (182.1): price = the ticket's `limit_price` (carried on
  the contract even for a market entry), equity = `PolicyDials.paper_
  starting_equity_usd`, cap = `PolicyDials.paper_max_position_usd`
  (`max_position_pct_paper * paper_starting_equity_usd`), scale = the
  claiming strategy's `size_scale` (S4 = 0.5). All three inputs go INTO
  `mae.size_position(..., price=, max_position_usd=, size_scale=)`; the clip
  and the scale are exact-Decimal 8dp ROUND_DOWN inside it; `hud._build`,
  `thesis._submit` pass the same values; `cadence.run_once` sizes at the dial
  and keeps the live cash+marks figure only for the digest and the
  dead-account guard (equity <= 0 -> loud warning, entries skipped).
- R-007 (182.6): `trades_today_count` = entry `OrderSubmitted` events for the
  account on the UTC day (a thesis's first `OrderSubmitted`). Previews,
  binding evaluations, refused submits and exits never count. `_check_r007`
  unchanged. Known-open: a side/position-aware exit exemption INSIDE the
  rule (r25 finding 5) — a future pin, not urgent.
- Preview deferral (181) unchanged: only R-010/R-012 `insufficient_context`
  defer at preview.
- `backfill_ticks.py` is safe to plan with again (457ac39): it was blind to
  `.part-NNNN` fragments and walked the retired flat layout — a real run
  would have duplicated every uncompacted hour. Dry run after the fix:
  BTC/USD have 783 / miss 15.

## Live facts
- `paper:alpha`: principal $500, settled cash $457.96; open position TAO/USD
  0.15765 @ 266.00 (thesis `01M1XC37T40K9WN939XR8CBA02`, s1, horizon ends
  2026-09-14 07:25 UTC). Series 8 window ends 2026-09-28. T1; 1 graded ever.
- Digest 2026-09-10 (pre-merge): NEAR denied at binding EVERY hour on R-012
  (0.046-0.053) — the shipped fix's exact target. First post-merge digests
  should show NEAR/LINK/SOL/ETH ticketing when armed.
- Archive: 6h25m blackout 2026-09-10 00:03-06:28 UTC on all 8 streams
  (Windows Update reboot, tasks were Interactive-only). Only Kraken trades
  are recoverable. Two orphaned `.tmp` fragments from 23:59 UTC 09-09 remain
  (`perps\hyperliquid\crypto\BERA-PERP\2026-09-09\ctx-23.part-0004.parquet.tmp`,
  `ticks\fx\BTC_EUR\2026-09-09\book-23.part-0005.parquet.tmp`) — harmless,
  Mike deletes or not. Report: docs/research/data-health-2026-09-10-reboot.md.
  Compaction is 18 days manual-backlogged (README says every day or two).
- Mike: the Kraken Prop account has NO idle timeout (his earlier belief was
  wrong); ~$4,963 sitting idle. Proposal on the table (his call): a new
  `paper:prop` account at $5,000 once TAO closes, dials
  `paper_starting_equity_usd=5000`, so the paper record rehearses the prop
  at true scale. The cap defect was scale-invariant — $5k is for realism,
  not actionability. Needs the prop eval's rules (max daily DD %, max total
  DD %, profit target, min days) for `AccountConfig.max_daily_drawdown` /
  `max_lifetime_drawdown` (R-017/R-018).

## Per-feature status
| feature | state | next action | blocking? |
|---|---|---|---|
| SPEC-sizing-cap T1-T7 | SHIPPED (rounds 24 FIX-FIRST -> 25 SHIP) | watch the first post-merge digests: tickets for capped names (LINK/SOL/ETH at exactly $50), zero `entry denied by policy — R-012`, R-007 `measured` small | no |
| R-007 exit exemption inside the rule | known-open (182.6) | tk-spec when convenient; small; money-path review | no |
| DEFAULT_SYMBOLS widening (B3) | CTO decision open | decide after 2-3 days of post-fix digests; 20 pairs have Kraken mappings | no |
| Kraken trades backfill for the 09-10 blackout | script fixed 457ac39; dry-run clean | Mike says "run the Kraken backfill" -> `uv run python scripts/backfill_ticks.py` (no --dry-run) from the main tree; writes only hours with no present-form file | Mike's go |
| Compaction backlog (18 days) | manual by design | Mike says go -> follow ~/.claude/skills/tk-data-health/references/COMPACTION-RUNBOOK.md | Mike's go |
| tk-data-health tooling (health_snapshot.ps1, coverage.py, audit_tree.py) | do not exist (ROADMAP Data vacuum) | a sonnet batch from the skill's own step descriptions; read-only tools | no |
| `paper:prop` at $5k | proposed | after TAO closes (<= 09-14): `tk account create-paper` with principal 5000, config.toml `default_account_ref` + `paper_starting_equity_usd`, R-017/R-018 dials from the prop rules | Mike's rules |
| Windows Update deferral | Mike's hands | pause updates / active hours | no |
| Navigator artifact | seed unchanged: docs/handoff/HANDOFF-2026-09-08-navigator-artifact.md | Mike forks a branch; tk-brainstorm | no |
| Data thread (Binance backfill, Coinbase book backfill, Alpaca NBBO, retention re-measure) | untouched | separate sprint | no |

## Forks / parallel work in flight
- None mid-batch. All agents from this session are finished or stopped;
  the tree is committed and merged.
- Process debt worth a tk-retro line: the round-24 fix implementer burned
  ~300k tokens (reverted production code to "prove red", re-applied, then
  chased the rtk-swallowed pytest summary). Dispatch rules updated in memory
  (tests first, exit code only, budget line, stop-and-verify). Mike asked to
  analyze that transcript later:
  `C:\Users\admin\AppData\Local\Temp\claude\C--Users-admin-dev-tradekit\6ba713ea-e8f8-4917-bff9-3f4be94ea50a\tasks\ad14acf136cbb28c6.output`.
- pytest prints no `N passed` line in this repo (`addopts="-q"` + the gate's
  `-q` = `-qq`); the gate script's exit code is the verdict.

## Next actions (ordered)
1. Read the first 2-3 post-merge digest sections (`docs/digest/DIGEST-<today>.md`):
   expect capped tickets at $50.00 notional, S4 tickets at half size, no
   R-012 binding denials, R-007 measured == real entries. Anything else is
   a defect — tk-friction + a red test first.
2. When TAO exits (by 09-14): read its grade; then decide `paper:prop` with
   Mike (needs his prop rules). Commit digests at the seam.
3. B3 DEFAULT_SYMBOLS widening decision after 2-3 days of clean digests.
4. With Mike's go: Kraken trades backfill (no dry-run) and a compaction run.
5. Small money-path pin: R-007 exit exemption inside the rule (182.6).
6. Data-health tooling batch (three read-only scripts), then the data thread
   sprint.
