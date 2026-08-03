# HANDOFF — Autonomous paper cadence (batch G2, the paper sprint's last machinery)

> Seed for a fresh session (or this thread post-compaction). Mode: tk-spec →
> tk-implement, MONEY-PATH review discipline. Written 2026-08-03 by the CTO
> session that shipped batches A-G1; zero conversation context assumed.

## State as of 2026-08-03 (all merged to main, gate green @ bad061d)
- Batches A-G1 SHIPPED (7 review rounds, 14-20, all in agent-metrics.md):
  in-kind fee physics (ASSUMPTIONS 170), wound-scale enum (171),
  scan_confluence (172), strategy registry (173), S2 pullback (174),
  S4 reversion + horizon_hours (175), hud registry walk (176).
  MTF-SCAN COMPLETE. Funnel = S1/S2/S4 walked first-match-wins with full
  attrition explainability.
- Live-market smoke (2026-08-03): walk works end-to-end; honest wait —
  S1/S2 die at confluence (no bullish setups), S4 dies at regime
  pre-filter (regime not recommending mean_reversion). WATCH-ITEM for the
  digest: if the regime model rarely recommends mean_reversion, S4 rarely
  arms — surface the per-strategy prefilter-kill counts.
- Promotion baseline: T1, 1/30 graded, current series window
  2026-07-30 → 08-29. The cadence exists to move this number honestly.
- Pending chips (follow-ups, not blockers): shared filter-vocab validator
  extraction; regime pass-through on scan_confluence (HMM economy);
  scan_confluence audit-awareness (T-AUDIT-3 — S2/S4 currently
  audit-invisible, matters for Mike's learning loop).


## Mission
The funnel becomes a self-driving loop on the PAPER account only:
scheduled scan → thesis-from-StrategyDef → policy verdict → paper submit →
exit management → grade → daily Mike digest. Mike's ratified red line
(HANDOFF seed, verbatim intent): every submitted trade passes the FULL
funnel (setup → sizing → policy PASS); zero discretionary entries; if the
funnel says wait, report the drought and wait.

## Structural guards (non-negotiable, tested)
- account_ref hardcoded/validated paper:* — the cadence module refuses any
  other ref loudly (never consults live keys; the four live locks stay
  untouched and irrelevant to this path).
- Every entry order goes through the EXISTING execute_order pipeline
  (policy.evaluate verdict inside) — no new submit path, no bypass.
- Drought is a first-class outcome: a cadence run with zero setups writes
  the digest line and exits 0.

## The pieces
1. **Thesis-from-StrategyDef builder**: replaces hud/_serve's minimal
   contract for cadence use. Wires: strategy tag, horizon_hours (S4=48,
   default 168) with VALIDATION (175.3: nonpositive → loud error —
   mandatory this batch since horizon_end = captured_at + horizon_hours
   lands here), size_scale/r_multiple_override into the sizing input,
   entry/stop/target from the setup's indicators per STRATEGY-PACK's
   per-strategy exit pins (READ the doc's S2/S4 exit/stop sections
   verbatim before spec'ing — S4 carries the 48h time-stop).
2. **Exit management**: the missing verb. Time-stop exits at horizon_end;
   stop/target exits per thesis contract. PINNED (carried from batch A /
   ASSUMPTIONS 170.2): sell qty = positions() NET qty, never entry
   filled_qty. Exits also route through the pipeline (policy sees them).
   Determinism: clock/bars via existing seams only.
3. **Scheduler**: Windows scheduled task per the collectors/watchdog
   pattern (scripts/ + registration doc), cadence aligned to 1h bar close
   (S2/S4 legs are 1h; 4h legs re-evaluate on the hour harmlessly).
   Each run: rebuild → scan via registry walk → for each claimed setup not
   already open: build thesis → submit → log. Then: manage exits for open
   positions. Then: append digest.
4. **Daily digest (Mike-facing)**: docs/digest/DIGEST-<date>.md (or
   single rolling file — decide at spec): trades entered/exited w/ P&L,
   funnel attrition counts (symbols scanned → legs passed → policy PASS →
   submitted), drought days, promotion_status() series progress toward 30,
   warnings (provider errors etc.). Plain English, his primer style.
5. **Grading hook**: closed thesis → grade verb already exists; confirm
   cadence triggers grading at exit and promotion_status() sees it.

## Open questions for finalize (ASSUMPTIONS candidates)
- Entry order type (market vs limit at last close) — read what
  execute_order/_entry_price already pins; likely market w/ limit_price
  reference per _pipeline conventions.
- One position per symbol? per strategy? (concurrent S2+S4 signals on
  different symbols fine; same symbol → first-match-wins already
  serializes at scan level, but an OPEN position on a symbol should skip
  new entries — pin it.)
- Digest cadence: per-run append vs daily file. Mike said "daily digest".
- regime_families consumption (174.5) — whatever T-MTF-4 lands.
- Cooldown after exit on same symbol? (avoid churn) — flag to Mike if no
  doc guidance; default no cooldown beyond funnel discipline.

## Review requirements
Money-path adjacent (thesis/sizing/order flow) → full review round.
The no-discretionary-entries guard and paper-only guard get dedicated
adversarial probes.
