# SPRINT-AUDIT-BUNDLE — pins (CTO, 2026-07-24)

Batch 2: money-path fixes from docs/reviews/gating-filter-audit-2026-07-23.md
(H2, H3, M2, L1, L3) under ENGINEERING-CANON D4. Money-path: review round is
MANDATORY before commit (CLAUDE.md red line). Runs AFTER TICKET-001 closes
(disjoint from its files except none — verified: this batch touches policy/,
contracts/_execution, mae/_sizing, mae/_correlation, mae/_indicators/
volatility, hud/_build L3 line only; TICKET-001 touches hud/_build broadly —
therefore SERIALIZE: this batch's hud L3 edit rebases on TICKET-001's green).

## CTO adjudications (the two needs_human calls — decided)

**A1 (H3 shape).** `ProposedAction.kind` closes to
`Literal["submit_order", "cancel", "promote", "void"]` — exactly `_MUTATING`
(policy/_rules.py:404). Rationale: only `"submit_order"` is constructed in
production today; rules already know the other three; R-001 applies to ALL
of `_MUTATING`, so with the Literal in place every representable kind has ≥1
applicable rule and the `all([])` vacuous-allow becomes UNREACHABLE by
construction. Per canon D3 rule 6 (define errors out of existence, no guards
for impossible states) we add NO runtime guard in `evaluate_pure`; instead
ONE invariant test enforces the previously-unenforced invariant:
`for kind in get_args(ProposedActionKind): assert any(kind in r.applies_to for r in RULES)`.
The contract comment "open set until P2" is retired (P4 now).

**A2 (`policy/_context.py:685-692` narrowing).** Adopt the auditor's
recommendation now (cheap, fail-closed either way):
`except ValueError: if trade_log: raise; return None` — an empty log stays a
clean None; a compute error on real trades raises loudly. Reviewer confirmed
existing promotion tests monkeypatch to RETURN metrics, not raise — compatible.

## Pins

### P1 — H2: `mae/_sizing.py atr_position` multiplier guard
After the risk_pct check:
`if multiplier <= 0.0: raise ValueError(f"multiplier {multiplier} must be positive — a non-positive ATR multiplier flips the stop distance and sizes a wrong-way position")`.

### P2 — H3: kind Literal (per A1)
`contracts/_execution.py`: `ProposedActionKind = Literal["submit_order", "cancel", "promote", "void"]`;
`ProposedAction.kind: ProposedActionKind`. `_rules._MUTATING` derives from
`get_args(ProposedActionKind)` (one source of truth; import direction:
policy imports contracts, already true). Schema export updates
automatically via pydantic — regenerate `docs/schemas` if the export script
is part of gate/docs flow (check `tk schema export` consumers; additive enum
constraint).

### P3 — M2: correlation zero-variance → undefined, not 0.0
`mae/_correlation.py:109` area: `denom == 0` ⇒ `matrix[a][b] = matrix[b][a] = None`,
pair recorded in new frozen field `zero_variance_warnings: list[tuple[str, str]]`
on `CorrelationResult`, high-correlation check skipped for that pair.
Surface the field through `mae.get_correlation_matrix` unchanged-shape-plus-field.

### P4 — L1: `atr()` period guard
`if period < 1: raise ValueError(f"period must be >= 1, got {period}")` at top
of `atr()` (mirror of bollinger's existing guard). Check `keltner`/`_ema` for
the same hole; guard if present (audit L2's `ema()` in trend.py IS in scope —
same one-line guard).

### P5 — WITHDRAWN (CTO adjudication 2026-07-24, red-phase flag confirmed)
Audit finding L3 is a FALSE POSITIVE: `_rules._insufficient` emits
`outcome="fail"` with `measured="insufficient_context:{field}"`, so hud's
existing `outcome == "fail"` filter already surfaces the field in the
rationale. CTO verified against `_rules.py:38-49`. No change; logged in
agent-metrics as audit-quality feedback.

### ~~P5 — L3: hud denial rationale names insufficient_context~~ (withdrawn)
`hud/_build.py` `_default_evaluate_policy`:
`failing = [hit for hit in verdict.rule_hits if hit.outcome not in ("pass", "not_configured")]`
(keep the `or "policy denied action"` fallback).

### P6 — A2 narrowing in `policy/_context.py`
As adjudicated above; docstring sentence updated to state the narrowed
contract.

## ASSUMPTIONS Round-28 (draft numbers 165-167, ratify at red commit)
- 165: ProposedAction.kind is a closed Literal == _MUTATING; every legal kind
  has ≥1 applicable rule (invariant test); unknown kinds are unrepresentable
  (pydantic ValidationError at construction). Retires "open set until P2".
- 166: undefined correlation (zero-variance leg) is None + warning, never 0.0
  (mirrors insufficient-overlap precedent; R-013 consumers must treat None as
  "cannot assess", which is the existing insufficient-overlap semantic).
- 167: sizing/indicator numeric-parameter guards (multiplier, period) raise
  ValueError with the module's standard message style; no silent wrong-sign
  output survives.

## Fences
- Files: contracts/_execution.py, policy/_rules.py (the _MUTATING derivation
  only), policy/_context.py (the except narrowing only), mae/_sizing.py,
  mae/_correlation.py, mae/__init__.py (correlation surface), mae/_indicators/
  volatility.py + trend.py (guards only), hud/_build.py (P5 line only), tests.
- NO other policy rule edits; NO broker/ changes; NO R-rule test weakening —
  these pins ADD failure paths, they remove none.
- Red phase: test-writer cites ASSUMPTIONS 165-167; flags, never improvises.
