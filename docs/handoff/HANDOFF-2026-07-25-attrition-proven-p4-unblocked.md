# HANDOFF 2026-07-25 — attrition telemetry PROVEN LIVE; P4 unblocked; MTF-SCAN started

> Written by Fable pre-compaction. SUPERSEDES HANDOFF-2026-07-23-evening.
> Red-lines/seams from prior seeds remain binding.

## State
- branch `main` @ `f1b10bd` (gate green). Two audit batches SHIPPED today:
  TICKET-001 (2aecdb2) + SPRINT-AUDIT-BUNDLE (f1b10bd). Canon ratified fa2a5a9.
- Prop account: FLAT, $4963.57. Day-5 inactivity clock RESET by the 7/23 NEAR
  trade — no forcing function for a trade right now.

## THE headline: S1 silence is HONEST, proven with numbers
First real attrition log: `data/scans/2026-07-25/scan-020850.log`.
```
SUMMARY scanned=11 tickets=0
  killer filter: macd_signal (11/11)
```
All 11 pairs have NEGATIVE 4h MACD histogram (ETH -7.68 … AKT -0.004) — the
whole universe is bearish, so S1 (momentum-LONG) correctly fires nothing. The
scanner now genuinely evaluates macd with the correct `bullish_cross` vocab
(TICKET-001 fix confirmed working live). "Broken vs correctly-quiet" is
DEFINITIVELY answered: correctly quiet. A ticket can fire the moment any pair's
histogram crosses positive. **To find the log: `data/scans/<UTC-date>/scan-<HHMMSS>.log`.**

## P4 IS NOW UNBLOCKED (big state change — ROADMAP not yet updated)
Mike (this session): rotated both chat-pasted API key pairs, funded $50 live,
and ANSWERED the open questions in `prompts/rubric-thesis-v1.md` (tagged
`[MIKE]`). That clears 3 of the 4 P4 "Mike's hands" blockers (ROADMAP:154).
NEEDS CTO ACTION next session:
1. **Adjudicate the [MIKE] rubric answers into `prompts/rubric-thesis-v1.md`**
   (finalize the doc; it was a DRAFT awaiting him). Three answers:
   - keep core portfolio & prop/AI account on SEPARATE theses (his 10yr
     blockchain-as-AI-infra thesis stays his; engine trades market/stat laws).
   - ADOPT the wound scale (minor/major/fatal) into the review workflow — he
     likes it; wire into the rubric scoring.
   - **unresolved_attack_threshold → 2** (two unresolved categories = fatal),
     WITH a fallback: if no other theses stand, do a resolve-pass on the
     unresolved ones. ⚠ This is a POLICY DIAL (config.toml, changes the policy
     hash) — money-path discipline: proper batch + review round, NOT a quick
     edit. The fallback ("extra analysis pass on unresolved when nothing else
     stands") is a NEW behavior needing its own spec.
2. Then P4 proper: promotion flow (readiness → `tk promote confirm` → R-011
   3-trade budget) → 3 live trades → reconcile → verify_claim. This is the
   MVP done-gate. Live is still structurally fail-closed (dial + live-key env
   + two-man); enabling it is a deliberate CTO+Mike step.

## In flight
- **MTF-SCAN T-MTF-1 MERGED to main** (`mae/_data/limits.py` retention-pin
  table {"15m":6,"1h":25,"4h":90,"1d":365}) — CTO-reviewed, gate green @ 87cc30e,
  worktree removed. NEXT: T-MTF-2 (`scan_confluence` verb — reuses
  `_evaluate_symbol_timeframe`, AND-composes legs) → T-MTF-3 (strategy registry
  + S1 migrated, behavior-identical, regression-pinned by existing hud tests) →
  T-MTF-4 (hud scan_setup → registry walk). Strict order; only T-MTF-4 touches
  hud; none touch money-path. Authority: docs/design/MTF-SCAN.md (zero open Qs).
  Note: T-MTF-2 should rewire scanner's `_SCAN_LOOKBACK_DAYS=90` (mae/_scanner.py)
  to consume the new table (T-MTF-1 deliberately left it in place).
- **keltner/_ema period guard** — Mike running the task-chip fix in his own
  worktree (audit bundle's one deferred LOW). Don't double-work it.

## Live-trade counsel given this session
No valid S1 setup exists tonight (universe all-bearish, log above). Forcing a
trade = manufacturing the edge-claim the funnel refuses; day-5 clock already
reset. Recommendation: DON'T force one — let the scanner watch. `tk hud
--equity <live-equity>` is zero-risk (read-only, never places orders) and now
writes the attrition log every run.

## Open items carried forward
- Visibility standard (Mike request): wants dev-time console output + saved
  reviewable logs as a REPO-WIDE standard (console vs file vs ledger split,
  levels, retention). Proposed as ENGINEERING-CANON **D8** — spec it next.
  Attrition log is the first instance of the pattern.
- Derived-log narrowing (P6/ASSUMPTIONS A2): ACCEPTED — the ValueError swallow
  set provably == the insufficient-context case today; a real compute error on
  a real non-empty derived log now raises loud. Aligns with Mike's "no silent
  failures" rule (it CLOSES a silent-swallow hole).
- Prior seeds' still-open: advisory:kraken has no balance feed (loop settles on
  paper:alpha $500 dial); HUD Confirm/Failed silent+non-idempotent (bundle with
  tests/flows M-F2); OPERATIONS.md step 3 wrong (Prop = mobile-only, no
  bracket, manual exits); R-017/R-018 prop-wall PolicyContext wiring (M5.1 gap).
- GitNexus index desynced (db v42 vs build v40) — FTS broken, spams every Bash;
  needs reanalyze/upgrade (FRICTION.md).

## Suggested next-session order
1. Review+merge MTF-SCAN T-MTF-1 (worktree), continue T-MTF-2..4. OR
2. Adjudicate rubric [MIKE] answers + spec the unresolved_attack_threshold
   dial change (unblocks P4). OR
3. tests/flows M-F1/M-F2 + Confirm-button fix (canon D5 rollout).
Mike leans: MTF-SCAN parallel is already moving; P4 is the higher-value pivot
now that it's unblocked. CTO call next session.
```
