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

## Addendum — CTO design pins (session P2, 2026-07-17)

Binding on TDD/dev agents; reviewer reviews against these. Where a pin below
conflicts with DESIGN §7/§10, DESIGN wins — flag, don't improvise.

### Ambient wiring & test hygiene (P1C lessons, mandatory)

- All thesis/policy verbs reach state via `ledger.default_ledger()` (TK_DATA_DIR
  seam, default `./data`). **Batch A adds an AUTOUSE conftest fixture setting
  TK_DATA_DIR to tmp_path suite-wide** — no test may ever touch the real
  data/ledger.db (the cache-poisoning lesson, applied to the ledger).
- Dials: `uv add pydantic-settings`; `PolicyDials` loads `config.toml` (repo
  root; TK_CONFIG_PATH overrides — tests tmp-path it) with §7.2 defaults +
  `series_epoch = 2026-01-01T00:00Z` + `paper_starting_equity_usd = 500`.
  A committed config.toml carries the defaults Mike confirms at sign-off.
- Policy-version hash = sha256 over (sorted rule IDs + dial dump). First
  `evaluate()`/`status()` per process ensures a PolicyVersionLoaded event for
  the current hash; a hash different from the last recorded one additionally
  appends ConfigChanged. Verdicts carry the hash.

### Story 1 pins (thesis machine)

- State is DERIVED from events only (ThesisDrafted/Submitted/ReviewCompleted/
  Approved/Rejected/Activated/Graded/InvalidationAttested); the `theses`
  projection materializes it. `IllegalTransition(current_state, verb)` on any
  violation.
- `submit` validates EVERYTHING first, then appends in order:
  MarketSnapshotTaken → SizingComputed → ThesisSubmitted (the transition
  marker is LAST; a crash mid-sequence leaves the thesis in draft with orphan
  prep events — harmless and documented, because state = marker presence).
- Snapshot (MVP): last CLOSED daily bar for the asset via the sanctioned bar
  seam (below) + regime state; payload carries snapshot_id, symbol, ts,
  last_close, source. The canonical linkage is the EVENT (thesis_id +
  snapshot_id); the contract is immutable from draft (its market_snapshot_id
  field is the draft-supplied id; supersede = new thesis whose ThesisDrafted
  payload carries `supersedes: <old_id>`).
- Sizing at submit: `mae.size_position(symbol, account_equity_usd=...)` where
  equity = paper_starting_equity_usd + cumulative realized pnl for the
  account_ref from `pnl_daily` (Decimal). Output recorded verbatim in
  SizingComputed — R-012 compares against THIS.
- Predicate resolution at submit: every price-carrying predicate value +
  target/stop re-quantized via `contracts.quantize(value, asset.tick_size)`;
  resolved values recorded in the ThesisSubmitted payload.
- EV validation (F5): recompute ev = p_win*reward − (1−p_win)*risk in Decimal;
  reject submit when |stated − recomputed| > Decimal("0.01").
- `reviewed` is entered by a ReviewCompleted event; P2 ships NO review verb
  (tradekit.review is P3) — tests append ReviewCompleted as a harness action.
  Same for ThesisActivated (P3's broker pipeline emits it; P2 tests append it
  to reach `active` for grading).

### Story 2 pins (grade/void — Opus-gated at review)

- **Sanctioned cross-module seam:** `thesis` may import `mae._runtime` and
  call `get_closed_bars` ONLY (document in _runtime's docstring + ASSUMPTIONS:
  the single permitted cross-module internal consumer; extracting a shared
  marketdata leaf is a TD-register change = Mike's sign-off, deferred). No
  other mae internal is touchable from thesis; policy touches NONE.
- `grade(thesis_id)`: state must be `active` (or `approved` with a
  time_expiry-only... NO — active only; flag if a test seems to need
  otherwise). Bars from activation ts → now at each predicate's timeframe via
  get_closed_bars; call the FROZEN `_grading.evaluate_criteria` (never
  reimplement); pnl = Σ Fill events net of fees (Decimal); append ThesisGraded
  with outcome PASS|FAIL|VOID, per-predicate measured values + bar refs,
  ambiguous_bar, pnl. Re-point _grading tests through the verb where
  verb-shaped + TID251-ban `thesis._grading` per ASSUMPTIONS 23 (the
  fraction-exact-core escape hatch from P1C applies).
- `void(thesis_id, attestation)`: ONLY for structural invalidations
  (measurable ones auto-VOID inside grade()). Sequence: verify thesis state ∈
  {approved, active}; verify invalidation.kind == "structural" (else raise);
  append InvalidationAttested(attestation); then REQUIRE an existing reviewer
  sign-off artifact event for this thesis (P3's review.verify_claim will
  produce it; P2 tests append it as harness action) — WITHOUT it, raise
  (append nothing further, attestation event may exist without void — that is
  the audit trail of a REFUSED void). With both → ThesisGraded(VOID).
- Grade pnl and all price comparisons Decimal/quantize end-to-end.

### Story 3 pins (policy)

- Public `evaluate(action)` = assemble frozen context (`_context.py`, reads
  projections; MAY do I/O) → call PURE `_evaluate(action, ctx, rules)` →
  append ActionProposed + VerdictIssued → return Verdict. The property test
  (same inputs ⇒ byte-identical verdict) targets the pure core.
- Context fields not yet fed by P3 (open positions, live balances) default to
  SAFE values (empty positions, paper-equity-derived balance) — a rule must
  never pass because data was missing: absent data that a rule needs ⇒ deny
  with `insufficient_context` in the RuleHit (anti-permissive).
- R-013 correlation inputs live IN the context snapshot (assembled via
  `mae.get_correlation_matrix` for open-position symbols; empty when no
  positions). evaluate stays pure.
- Every rule: one allow + one deny test + WHY string. RULES.md generated by
  `tk policy status --rules` into rules/RULES.md (gitignored? NO — committed,
  regenerated, never hand-edited; drift test: regenerating in CI equals the
  committed file).

### Story 4 pins (series/promotion — Opus-gated at review)

- series_index = floor((grade_ts − series_epoch) / 30 days) — pure UTC
  arithmetic, pinned by a test that constructs boundary timestamps (grade at
  epoch+30d lands in series 1, not 0).
- Series accounting per account_ref. complete = window closed AND ≥10 graded
  non-void. clean = zero GateViolationDetected in-window AND expectancy>0 net
  of fees AND intra-series MDD < 15% (equity base = paper_starting_equity +
  realized pnl entering the window).
- T1→T2 exactly per §7.3/F3; R-016 calls mae.compute_strategy_metrics with
  the registry's real n_trials (P2 MVP: n_trials from a dial defaulting to 1
  + a TODO to wire the experiment registry in P3 — flag in ASSUMPTIONS).
- promotion_state + series + theses + pnl_daily are PROJECTIONS in
  _projections.py; extend test_rebuild.py idempotence to all four.
- `confirm_promotion()` refuses unless a PromotionGranted event exists and is
  unconsumed; appends PromotionConfirmed with live_sequence_remaining=3.

### Batch plan (four-stage per batch; freeze gate on every hand-derived fixture)

- **Batch A:** typed event payload contracts + four projections + story 1
  (thesis machine) + the TK_DATA_DIR autouse fixture.
- **Batch B:** story 2 (grade wiring + VOID path).
- **Batch C:** story 3 (dials, rules R-001..R-016, evaluate, RULES.md, CLI
  verbs incl. `tk thesis|grade|policy|promote`).
- **Batch D:** story 4 (series + promotion machine).
- **Batch E:** story 5 adversarial replay suite (Opus authors the scenarios)
  + Mike's rules/dials sign-off + close-out.

### Mike-facing gate (Definition of done)

RULES.md WHYs + config.toml dials go to Mike for explicit confirmation before
the sprint closes (he signs off in chat; log it in the dev-log).
