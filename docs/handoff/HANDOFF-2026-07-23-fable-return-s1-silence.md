# HANDOFF 2026-07-23 — fable-return-s1-silence (sprint seed)

> Written by Fable (retained at half-usage past 7/20 — back as CTO). Supersedes
> HANDOFF-2026-07-20-ops-ready.md as the active seed; that doc's red lines,
> sanctioned seams, and working-style sections REMAIN BINDING — read it too.

## State (auto-captured)
- branch: `main`  anchor: `f4ec577`
- last gate: green @ 16a2cea (2026-07-23T17:22:07.126737+00:00); f4ec577 is docs-only on top
- dirty tree: clean (GitNexus CLAUDE/AGENTS blocks + docs/hud/hud.html committed at f4ec577)

recent commits:
```
f4ec577 docs: GitNexus sections (CLAUDE/AGENTS) + docs/hud/hud.html artifact
16a2cea docs+experiments: MTF-SCAN + STRATEGY-PACK designs (delegation-ready), PAXG basis probe (artifact-audited), dev-log
715beca provider pagination green: alpaca page_token loop; kraken retention-truth error
a7d6be2 provider pagination pins: alpaca page loop + kraken retention truth (red)
6cf80a3 docs: OPERATIONS playbook + STRATEGY-BACKLOG (S1-S4, MS-PAXG-1) + ops-ready handoff + dev-log
```

## Mission

**Break the silence with evidence, not enthusiasm.** The ops loop is complete,
rehearsed, and green (1000+ tests) but has produced ZERO output: ledger has no
AdvisoryTicketAcked and no ThesisGraded events — S1 momentum+volume has never
fired a ticket since ops went live (~7/19-20). Tick collector is healthy (Mike
confirmed 7/23). This sprint: (1) instrument WHY S1 is silent, (2) deploy the
designed remedy (MTF-SCAN + S2), (3) honor the day-5 inactivity rule if it
lapses meanwhile.

## Per-feature status

| Feature | State | Next action | Blocking? |
|---|---|---|---|
| Ops loop (hud→ticket→confirm→fill) | DONE, rehearsed, ZERO real use | operate per OPERATIONS.md; day-5 clock running since ~7/19-20 (verify start date in OPERATIONS/dev-log before acting) | no |
| S1 momentum+volume | LIVE but structurally silent — root cause unmeasured | **Scan-attrition telemetry** (new, small): per scan, log per-filter kill counts per pair (a `ScanAttrition` note or event) so we can SEE which filter kills all candidates. Spec via tk-spec; it's a read-side addition, no policy surface | YES — decides tune-vs-replace |
| MTF-SCAN (docs/design/MTF-SCAN.md) | Design delegation-ready, zero open questions (T-MTF-1..4) | tk-tasks → tk-implement batches | after/with telemetry |
| STRATEGY-PACK S2 pullback (docs/design/STRATEGY-PACK.md) | Design delegation-ready | implement after MTF-SCAN (S2 needs the cross-timeframe tag joins) | needs MTF-SCAN |
| T-PAGE-1 pagination | DONE 7/19 (Alpaca real page_token; Kraken = retention-truth error, ASSUMPTIONS 161) — 7/20 handoff's queue item 3 is stale | none | — |
| M5.2 backtest engine | queued (carries DSR-dispersion fix, ASSUMPTIONS 156a) | after S2 | no |
| MS-PAXG-1 research | queued, grunt-tier data first | flag XAU-reference-feed decision to Mike | no |
| Explainer debts to Mike | open (parquet explainer; "50-100 trades" sample-size answer vs mae._metrics gates) | Haiku/Sonnet can draft; CTO verifies | no |
| ROADMAP hygiene | "GitHub remote" box unchecked but remote EXISTS and is pushed (github.com/mmunro3318/tradekit) | check the box | trivial |

## Forks / parallel work in flight

None. No subagent batches mid-flight; tree clean at f4ec577.

## Next actions (ordered)

1. **Verify day-5 clock**: read docs/OPERATIONS.md inactivity rule + dev-log for
   ops-live date. If day ≥5: CTO executes the minimal trade through the FULL
   funnel (scan→thesis→review→approve→ticket→Mike fills) per the rule — this is
   a process-health trade, not an edge claim. Do NOT soften the funnel for it.
2. **Scan-attrition telemetry** (tk-spec → tk-implement, one small batch):
   every scan records, per pair, candidate count surviving each S1 filter in
   order. Output lands in the scan report + a ledger note. Acceptance: after 2
   scan days we can name the killer filter with numbers. This is diagnosis, not
   tuning — no threshold changes without the numbers + CTO sign-off (R-rule
   discipline applies to strategy dials too).
3. **MTF-SCAN implementation** (T-MTF-1..4 per docs/design/MTF-SCAN.md) via the
   four-stage batch cycle. Retention pins live in limits.py per the design.
4. **S2 pullback-continuation** per STRATEGY-PACK.md — only after telemetry
   confirms S1's silence is regime/structure (not a mis-set threshold), and
   after MTF-SCAN lands. If telemetry instead shows one mis-calibrated filter,
   fix THAT first and give S1 a fair window.
5. Explainer debts + ROADMAP checkbox — batch into any session's cooldown.

## Traps for the next session

- 4h-candle cadence means ≤2 meaningful scans/day — don't judge S2 (or a
  re-tuned S1) on <3 days of scans; silence ≠ broken.
- Kraken OHLC retains only 720 candles/interval (ASSUMPTIONS 161) — no deep
  history backfills; the interval ladder in the error message is the truth.
- The 7/20 handoff's queue is PARTIALLY STALE (item 3 done); this doc is the
  live queue. Its red lines/seams sections are still binding.
- Zero-activity ledger means projections/promotion series have never seen real
  flow — first real fills may surface latent projection bugs; run
  `scripts/rehearse_hud_ack.py` and `tk ledger verify` after the first live day.
