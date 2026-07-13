# SPRINT P2 — Thesis lifecycle, grading, policy engine, promotion ladder

> **This is the correctness-critical sprint — the gates that stand between an LLM and money.** Executor: Sonnet for mechanics; **Opus MUST write or review: the grading engine, the VOID path, series accounting, and the promotion state machine.** Mike signs off on the rules catalog before merge (each rule's WHY is displayed to him). Prereqs: P1 complete. References: DESIGN §5.2, §7, §10; TD-5/9/10; SME F1/F7; the §15 threat table (each row here becomes a test).

## Mission

`tradekit.thesis` (draft/submit/approve/reject/grade/void) and `tradekit.policy` (evaluate/status/promotion_status/confirm_promotion/halt/resume) per the §4.2 interface pins. Everything event-sourced through the existing ledger.

## Ground rules specific to this sprint

- Every state change is an event append; NO state lives outside the ledger + projections. If you find yourself adding a mutable module-level variable, stop.
- Typed event payload models now land for the events these modules produce (ThesisDrafted…ThesisGraded, ActionProposed/VerdictIssued, Series/Promotion/Halt events) — extend `contracts`, honoring ASSUMPTIONS 10's ratified pattern (envelope stays dict; producers validate through the typed model then `model_dump()`).
- New projections: `theses`, `series`, `promotion_state`, `pnl_daily` — added to `_projections.py` rebuild, covered by extending `tests/unit/ledger/test_rebuild.py` idempotence to them.

## Stories

### 1. Thesis state machine (`tradekit.thesis`)
draft → submitted → reviewed → approved → active → PASS/FAIL (terminal) | rejected | VOID, exactly per DESIGN §10.1. Illegal transitions raise `IllegalTransition` naming current state. `submit` does four things atomically: MarketSnapshotTaken event, `SizingComputed` event (calls `mae.size_position`, records output — R-012 compares against THIS later), predicate resolution (quantize every price via `contracts.quantize` with the asset's tick), EV validation (numeric, complete — F5). Post-submit the contract is immutable (supersede = new thesis linked by event).

### 2. Grading engine (Opus)

> **UPDATE 2026-07-12: the arithmetic core is DONE** — `thesis/_grading.evaluate_criteria` implements every rule below (same-bar priorities, lookahead guard, predicate deadlines, time_expiry), pinned by 12 tests in `tests/unit/thesis/test_grading_engine.py`. Remaining work in this story: `grade(thesis_id)` fetches bars (P1A) + thesis state (story 1), calls the core, computes pnl from Fills, emits ThesisGraded — then re-point the core's tests through the public verb and ban `_grading` in TID251 (ASSUMPTIONS 23). Do NOT reimplement the rules; if one seems wrong, that's a Mike conversation.
`grade(thesis_id)` evaluates predicates against bars from activation→now at each predicate's timeframe, in bar order:
- `price_touch gte v`: bar.high ≥ v (long-target semantics); `lte v`: bar.low ≤ v.
- `price_close`: compare bar.close only.
- First-triggered predicate wins. **Stop and target in the SAME bar → stop wins (conservative), `ambiguous_bar=True`** (§10.2). Write this test FIRST; it is the subtlest rule in the sprint.
- Horizon expiry with nothing triggered → FAIL (time_expiry predicate or horizon_end).
- Measurable invalidation triggered → VOID. Structural invalidation → requires `InvalidationAttested` event + a review sign-off artifact; without BOTH, `void()` refuses.
- Grade event carries every predicate's measured value + bar refs (auditability) and pnl net of fees from Fill events.
- All price comparisons through `quantize` (tick-grid) — float-noise grade flips are the bug class TD-23 exists for.

### 3. Rules catalog + `evaluate` (`tradekit.policy`)
- R-001…R-016 exactly per DESIGN §7.2 (IDs are stable forever; dials from `config.toml` via pydantic-settings; every dial change → ConfigChanged event).
- `_context.py` assembles a frozen context snapshot from projections; `evaluate(action)` is pure given (action, context, rules) — property test: same inputs ⇒ byte-identical Verdict.
- Verdict ledgered BEFORE any caller proceeds (the two-phase pipeline lands in P3, but VerdictIssued events start here).
- Every rule gets: one allow test, one deny test, and its WHY string (Mike-facing). `tk policy status --rules` regenerates `rules/RULES.md` — generated file, never hand-edited.

### 4. Series accounting + promotion machine (Opus)
- Series = fixed calendar-aligned 30-day blocks from a configured epoch (dial: `series_epoch`, default 2026-01-01T00:00Z). A thesis belongs to the series containing its GRADE timestamp. Complete = window closed AND ≥10 graded non-void. Clean = zero GateViolationDetected in-window AND expectancy>0 net of fees AND intra-series MDD <15%.
- T1→T2: 3 of last 4 complete series clean ∧ most recent clean ∧ ≥30 non-void across them ∧ per-strategy metric gates (R-016, calls `mae.compute_strategy_metrics` with the registry's real n_trials). All machine-evaluated → PromotionGranted event; `confirm_promotion()` (Mike-only verb) → PromotionConfirmed with `live_sequence_remaining=3` (R-011). Demotion events per §7.3 triggers.
- CLI: `tk thesis draft|submit|show|approve|reject|void`, `tk grade sweep|show`, `tk policy status|halt|resume`, `tk promote status|confirm` — thin dispatch only.

### 5. Adversarial replay suite (the sprint's done-gate; Opus writes the scenarios)
Ring-3 tests in `tests/replay/`, one per §15 gaming vector:
- VOID-farm: agent voids 3 of 10 losers → R-015 blocks the 4th submission.
- Micro-series: 10 × $2 theses → R-008 denies each (min notional).
- Window cherry-pick: impossible by construction — test asserts series assignment is purely timestamp-arithmetic.
- Revenge-size: submitted order ≠ SizingComputed record → R-012 denies.
- Drawdown breach mid-series → R-009 lockout until graded review; advisory account included (F7).
- Kill switch: HaltSet denies everything mutating; resume restores.

## Definition of done

Adversarial suite green + full suite green + `rules/RULES.md` generated + Mike has read the WHYs and confirmed dials + ROADMAP P2 boxes + dev-log.

## Traps

- Grading with the unclosed live bar = lookahead. Only bars with close-time ≤ now.
- Series windows are UTC calendar arithmetic — no "last 30 trades" drift, no timezone-local boundaries.
- `promotion_state` is a projection; `tk ledger rebuild` must reproduce it exactly from events (extend the idempotence test — if promotion state survives only in memory or a side table, that's the D15/TD-4 violation).
- Do not let policy import broker or mae internals; it consumes projections + verb outputs only (check TID251 additions for the new modules).
