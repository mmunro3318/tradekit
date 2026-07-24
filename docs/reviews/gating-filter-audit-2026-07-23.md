# Gating & Filter Audit — 2026-07-23

## Method

Swarm audit hunting the **silent-failure / leaky-edge-case** family exposed by the
MACD `else: return None` bug — the defect that rejected 100% of scan candidates
silently while 1000+ tests stayed green. The pattern under the microscope: gating and
filter logic that swallows an invalid input, an unknown enum, or an undefined
computation and returns a plausible-but-wrong "no match / zero / None" instead of
failing loud.

Pipeline: **Haiku sniffer swarm → Sonnet adjudicator.** No auto-commit — this is a
**reports-only** pass. Per the project red line, money-path changes (`broker/`,
`policy/`, sizing, correlation-into-R-013) are **deferred to a reviewed batch** and are
marked `[MONEY-PATH]` below. Nothing in this audit was applied to source.

### Stats

| Metric | Count |
|---|---|
| Chunks sniffed | 58 |
| Suspects surfaced | 59 |
| Confirmed or needs-human | 12 |
| Cleared as false positive | 47 |

Confirmed breakdown by severity: **2 HIGH · 2 MEDIUM · 8 LOW** (2 of the 12 carry a
`needs_human` verdict — see callout). One HIGH is a live, actively-firing production
suppression (the MACD twin of the seed bug).

---

## CRITICAL / HIGH — money path first

### H1 — `_scanner.py:259-260` · HIGH · silent-return-none · **LIVE / actively firing**

**File:** `src/tradekit/mae/_scanner.py:259-260`
(caller: `src/tradekit/hud/_build.py:31`, `:130-131`)

**Symptom.** An unrecognized `macd_signal` enum value falls through to
`else: return None`, silently excluding 100% of symbol/timeframe combos from `matches`
with no exception and no `warnings` entry — directly contradicting the module's own
anti-permissive doctrine (docstring lines 72-78: "never a silent pass-through";
insufficient-bars raises `_InsufficientBars` + warning). **Confirmed actively firing:**
the live caller `hud/_build.py:31` defines `_SETUP_FILTERS = {"macd_signal": "bullish", ...}`
— the sprint-doc addendum string the scanner docstring (lines 45-51) explicitly rejected
in favor of canonical `"bullish_cross"` — and passes it into `mae.scan_markets` at
`_build.py:130-131`. So `want == "bullish"` hits the `else` for every candidate;
`result["matches"]` is always empty; `_default_scan_setup` always returns empty
`signal_tags`. **The HUD momentum+volume setup-confirmation stage is silently,
permanently disabled** — this matches the project's noted "ops loop live but silent,
zero tickets/grades" symptom.

**Root cause.** Two-layer bug the silent `return None` conjoins: (1) the scanner treats
an invalid enum value as "no match" (silent, per-candidate) instead of a loud
programming/config error, violating its own "never silent" invariant; (2) the HUD caller
passes the wrong string `"bullish"` instead of canonical `"bullish_cross"`. The silent
`return None` turned the caller's enum-mismatch into undetectable total suppression
rather than an immediate crash that would have surfaced on first integration run.

**Proposed fix (two edits, human-reviewed).**
(A) `_scanner.py:259-260` — replace `else: return None` with
`raise ValueError(f"unknown macd_signal value: {want!r} (expected 'bullish_cross' or 'bearish_cross')")`.
(B) `hud/_build.py:31` — change `{"macd_signal": "bullish", ...}` to
`{"macd_signal": "bullish_cross", ...}`.

**Would a test have caught it?** Not with current tests — HUD tests monkeypatch the
`scan_setup` seam (`_build.py:145`), so `_SETUP_FILTERS`'s real value string is never run
against the real scanner. Add a contract test asserting `scan_markets` raises on an
unknown `macd_signal`, plus one **un-mocked** integration test of `_default_scan_setup`
(bypassing the seam) asserting a valid setup yields non-empty `signal_tags` — together
they catch both halves.

---

### H2 — `_sizing.py:30-51` · HIGH · missing-edge-case · **[MONEY-PATH]**

**File:** `src/tradekit/mae/_sizing.py:30-51`
(caller: `src/tradekit/mae/__init__.py:134`, propagates to `:160`, `:162`)

**Symptom.** `atr_position` validates `atr`, `price`, `equity`, and `risk_pct` with
explicit `ValueError`s but leaves `multiplier` **unchecked**. A negative `multiplier`
makes `stop_distance = atr * multiplier` negative, so `units = risk_usd / stop_distance`
is negative and `size_usd = units * price` is negative — a **wrong-way / negative
position size returned silently** with no raise (`stop_pct` also negative).
`multiplier == 0` raises `decimal.DivisionByZero`, an opaque error rather than the
module's clean "must be positive" message.

**Root cause.** The module's doctrine is fail-loud on nonsensical inputs (cf. the `atr`
guard "zero ATR sizes an infinite position"; the `risk_pct` guard "5%/trade is already
reckless"). `multiplier` is the one numeric input that escaped that doctrine.
`size_position` (`__init__.py:134`) forwards `atr_multiplier` (default 2.0, but
caller-overridable) directly in without validation, so a misconfigured/negative value
propagates a negative ATR size into `recommended_size_usd` via `min()` (line 160) and
into `recommended_units` (line 162), corrupting the recommendation with no error.

**Proposed fix.** After the `risk_pct` check, before computing `stop_distance`:
```python
if multiplier <= 0.0:
    raise ValueError(f"multiplier {multiplier} must be positive — a non-positive ATR multiplier flips the stop distance and sizes a wrong-way position")
```
Single choke point; no caller change needed. **Money-path — route through a human review
round before commit per the red line. Report only; do not apply.**

**Would a test have caught it?** Yes. A parametrized guard test asserting
`atr_position(..., multiplier=-1.0)` raises `ValueError` (and `multiplier=0` likewise)
closes the gap and pins the fail-loud contract. Existing tests cover the other four
guards but have no negative/zero multiplier case.

---

### H3 — `policy/_rules.py:603-607` · HIGH · fail-open-on-unknown-enum · **[MONEY-PATH]**

**File:** `src/tradekit/policy/_rules.py:603-607`
(aggregation: `src/tradekit/policy/_evaluate.py:58-64`; contract:
`contracts/_execution.py:47`)

**Symptom.** An action whose `kind` is not a recognized action type (a typo like
`"submit_ordr"`, or a future kind added without registering rules) matches no rule in
`applicable()`, yielding an empty tuple. In `evaluate_pure` this becomes `hits=[]` and
`allow = all([]) == True`, so **the policy gate returns `allow=True` with ZERO rules
consulted** and emits no `GateViolationDetected`. A malformed `submit_order` silently
bypasses all 16 money-path rules (live-lock R-001, drawdown R-017/018, sizing, etc.).

**Root cause.** `ProposedAction.kind` is an open `str` (`contracts/_execution.py:47`,
commented "open set until P2") with no closed domain and no recognized-kind registry.
`applicable()` cannot distinguish a legitimately rule-less recognized kind
(cancel/void — correctly allowed) from an unrecognized/typo kind (should be rejected).
`all(...)` over an empty list is vacuously `True`, so unknown kinds **fail OPEN** —
directly contradicting the anti-permissive convention the same file enforces for unknown
`outcome` values at `_evaluate.py:60-64` (which fail CLOSED). The "open set until P2"
closure was deferred and never completed (project now at P4).

**Proposed fix.** Close the kind domain at the contract boundary: change
`ProposedAction.kind` from `str` to a
`Literal["submit_order", "cancel", "promote", "void", ...]`, so an unknown/typo kind is
rejected loudly at construction (pydantic `ValidationError`) before it reaches the gate.
This keeps recognized rule-less kinds (cancel/void stay in the `Literal`, still get
`allow=True` on empty applicable) while making silent bypass impossible. If closing the
contract is too broad for one change, add a fail-closed guard in `evaluate_pure`: derive
`KNOWN_KINDS` from the rules' `applies_to` plus an explicit rule-less-but-recognized
allowlist, and deny when `action.kind` is unrecognized. **Do NOT use a bare
"empty applicable → deny"** — that wrongly breaks cancel/void. **Money-path — human
review round before commit.**

**Would a test have caught it?** Yes. No test asserts behavior for an unrecognized kind.
Add both: a contract test asserting `ProposedAction(kind="garbage", ...)` raises
`ValidationError`, and a policy test asserting `evaluate_pure` on an unknown kind denies
(guards the `all([])` edge independent of the contract).

---

## MEDIUM / LOW

### M1 — `_scanner.py:275-277` · MEDIUM · unvalidated-enum

**Symptom.** An unrecognized `bb_position` filter value (typo like `"below"`, or
canonical §3's `"None"`) never equals the computed position (always one of
`below_lower`/`above_upper`/`inside`), so line 275 returns `None` for every
symbol/timeframe — zero matches, no warning, indistinguishable from a genuine
no-setups result. Same class as the H1 MACD `else: return None`.

**Root cause.** `scan()` validates only `symbols is None`; filter **values** are never
validated.

**Proposed fix.** Add filter-value validation at the top of `scan()`, after the
`symbols`-is-None `ValueError` (line 346) and before the loop, mirroring that precedent
(validate before any bar fetch): raise `ValueError` naming the offending key/value for
both `bb_position` (`{below_lower, above_upper, inside}`) and `macd_signal`
(`{bullish_cross, bearish_cross}`) — this also closes the H1 twin. **Money-path/red-line
review round before applying.** Weaker alternative: warnings entry + skip, matching the
insufficient-bars pattern.

**Would a test have caught it?** Yes — a contract test with
`filters={"bb_position": "below"}` asserting `ValueError` (or an explicit warnings entry)
would fail today. No such input-validation test exists.

---

### M2 — `_correlation.py:109` · MEDIUM · silent-masking

**Symptom.** When either joined log-return series has zero variance (`denom == 0`),
Pearson r is undefined (0/0), but the code silently returns `r = 0.0` — reporting a
degenerate pair as "perfectly uncorrelated / diversifying" with no warning. Because
`r = 0.0`, `high_correlation_warnings` never triggers, so the caller
(`get_correlation_matrix` → §9.1/R-013 risk consumers) cannot distinguish a genuinely
uncorrelated pair from a degenerate constant-return pair (flat/halted equity, pegged
stablecoin over the window).

**Root cause.** The guard `... if denom != 0 else 0.0` treats an undefined correlation as
a computed zero — contradicting the module's own invariant (`CorrelationResult`
docstring lines 51-53: "never a silently-computed number ... on too little data, R-013"),
which already models the analogous insufficient-overlap case as `matrix[a][b]=None` plus
a warning.

**Proposed fix.** Treat `denom == 0` as undefined, mirroring the insufficient-overlap
path: set `matrix[a][b] = matrix[b][a] = None`, record the pair in a new
`zero_variance_warnings: list[tuple[str, str]]` field on the frozen `CorrelationResult`,
`continue` (skip the high-corr check), and surface it in the `get_correlation_matrix`
wrapper (`mae/__init__.py`). Update both docstrings. **Feeds R-013 — route through the
money-adjacent review round before commit.**

**Would a test have caught it?** Yes. A unit test feeding one symbol a constant-value
(zero-variance) series against a normal series with ≥ `min_overlap` shared dates,
asserting `matrix[a][b] is None` (not 0.0) and the pair appears in a zero-variance
warning, would fail today. No such test exists.

---

### L1 — `_indicators/volatility.py:83-87` · LOW · missing-input-validation · **[MONEY-PATH]**

`atr()` does not validate `period >= 1`. With `period < 0` the guard `if n < period` is
False, so it proceeds: `tr[:period]` slices the wrong window, `sum(...)/period` divides
by a negative, `out[period-1]` writes a negative index, `range(period, n)` iterates from
negative — a **silently wrong ATR** with no error. `period == 0` raises a cryptic
`ZeroDivisionError`. The sibling `bollinger()` (lines 106-107) guards
`if period < 1: raise ValueError(...)`; `atr()` omits the identical guard.
**Fix:** add `if period < 1: raise ValueError(f"period must be >= 1, got {period}")` at
the top of `atr()` (line 83), mirror in `keltner()`/`_ema()` if uncovered. Parametrized
`pytest.raises(ValueError)` test for `period in {0, -1}` would have caught it.
ATR feeds sizing — money-adjacent; review before commit.

### L2 — `_indicators/trend.py:60-83` · LOW · unvalidated-input

`ema()` has no period guard, unlike `sma()` directly above it. Negative `period` →
`n < period` False → truncated slice / negative divisor / negative index / negative-start
`range` → silently corrupt output; `period == 0` → `ZeroDivisionError`. `ema` seeds
`momentum.macd` and `volatility.keltner`, so a negative period from config propagates
silently downstream. **Fix:** add the same
`if period < 1: raise ValueError(f"period must be >= 1, got {period}")` at the top of
`ema()` before `n = len(values)`. Parametrized validation test for `period in {0, -1, -5}`
would have caught it. Not money-path.

### L3 — `hud/_build.py:74-78` · LOW · silent-failure-observability · **[MONEY-PATH]**

A denied policy verdict caused **solely** by `insufficient_context` hits produces an
empty `failing` list, so the rationale collapses to the generic fallback
"policy denied action" instead of naming the offending rule/field — the HUD
`policy_verdict` gate rationale hides the real denial reason. **Root cause:** the filter
matches only `outcome == "fail"`. **Fix:** broaden to
`failing = [hit for hit in verdict.rule_hits if hit.outcome not in ("pass", "not_configured")]`;
`insufficient_context` hits already carry `measured="insufficient_context:{field}"`, so
the existing join renders a meaningful reason. Keep `or "policy denied action"` as
last-resort. Test: a verdict denied purely by `insufficient_context` asserting the
rationale names the field. Under `hud/` but reports a policy decision — treat as
money-adjacent.

### L4 — `_regime.py:527-530` · LOW · missing-edge-case

`compute_regime` raises an uncaught `KeyError`/`IndexError`/`TypeError` when a loaded
sidecar is valid JSON but schema-malformed (missing `feature_means`, list shorter than 2,
non-numeric) instead of degrading to a refit; same risk one line up at 524
(`sidecar["fit_date_utc"]`). Contradicts the module invariant (docstring lines 67-72:
"A stale or missing/unreadable artifact triggers a refit"). `_load_artifact`
(lines 347-351) only catches decode/IO errors. Note `n_states` is defended with `.get()`
at 525 but `fit_date_utc`/`feature_means` are not — internal inconsistency. Realistic
trigger: a sidecar predating the `feature_means` key. **Fix (cohesive):** validate the
sidecar schema in `_load_artifact` after `json.loads` — require `fit_date_utc` a parseable
str, `n_states` an int, `feature_means` a sequence of len ≥ 2 of float-coercibles; on any
failure return `None` (drives a clean refit); broaden the `except` at line 350 to also
catch `(KeyError, IndexError, TypeError, ValueError)`. Test: persist a schema-malformed
sidecar with a fresh fit_date and assert `compute_regime` refits (or does not raise).
Not money-path.

### L5 — `_regime.py:543-545` · LOW · swallowed-error

Every exception from `_fit_hmm` (real fit failure, `ImportError` if hmmlearn absent,
numpy errors, latent bugs) is caught and collapsed into `fitted=None`/`converged=False`,
then routed to `_rules_fallback(reason="hmm_non_convergence")` with **no log line, no
distinct reason, no telemetry** — an env/code failure is indistinguishable from genuine
non-convergence and would silently persist across every call. The fail-closed *direction*
is intentional and correct (lines 538-541, ASSUMPTIONS 25 spirit); the bare
`except Exception:` is broader than that rationale and discards the `warnings` local.
Masks a persistent breakage as routine — the exact "live but silent" pain. **Fix (signal
only, behavior unchanged):** add a module logger and `_log.exception(...)` in the except;
pass `reason="hmm_fit_error"` when an exception occurred, reserving
`"hmm_non_convergence"` for fitted-but-not-converged; optionally let `ImportError`
propagate. Test: make `_fit_hmm` raise, assert a log record and/or
`reason == "hmm_fit_error"`. Not money-path.

---

## needs_human callout

Two findings hinge on a product/spec decision the CTO must adjudicate — do not resolve
unilaterally:

- **H3-adjacent / `policy/_evaluate.py:58-64` (needs_human, HIGH, [MONEY-PATH]).** The
  empty-applicable `all([]) → allow=True` fail-open. Today it is masked by an *unenforced*
  invariant: every money-mutating kind happens to be in `_MUTATING` and thus caught by
  R-001's kill switch — but nothing forces a *new* mutating kind to be wired in. The
  correct behavior for genuinely non-mutating/advisory kinds (read queries with no rules)
  is `allow`, so the fix hinges on **whether the kind taxonomy is meant to be closed and
  which kinds are money-mutating** — an R-rule decision. Recommended shape if closed:
  deny on empty-applicable unless `kind` is in an explicit non-mutating allowlist, emitting
  a synthetic auditable `RuleHit` (e.g. `rule_id="R-000"`, `outcome="fail"`) so the deny is
  never silent (DESIGN §7.2). **CTO call: close the taxonomy or ratify the allowlist.**

- **`policy/_context.py:685-692` (needs_human, LOW, [MONEY-PATH]).** Broad
  `except ValueError: return None` around `mae.compute_strategy_metrics` catches *any*
  `ValueError`, not just the documented empty-log case — a genuine compute bug on a
  non-empty trade log would be silently converted to `None`, which R-016 reads as
  `insufficient_context`. **Not a live wrong-behavior defect** (current reachable inputs
  only hit the empty-log path; failure direction is fail-closed — worst case a promotion
  *wrongly denied*, never approved on bad data). The correctness relies on implicit
  couplings (the builder's `exit_ts <= entry_ts: continue` filter; pydantic can't fail on
  already-built records) that a future edit could break. Recommended narrowing: keep the
  unconditional call, then `except ValueError: if trade_log: raise; return None`. **CTO
  call: whether to tighten a fail-closed, documented catch in money-path code now vs.
  defer.** Reviewer must confirm no test monkeypatches the seam to raise `ValueError` on a
  non-empty log expecting `None` (inspected tests at `test_promotion.py:215/315/359`
  monkeypatch to *return* `StrategyMetrics`, not raise — fix appears compatible).

---

## Closing — systemic pattern & recommended TDD batch order

**The systemic pattern is one defect class wearing many masks: "undefined / unrecognized
input coerced into a plausible benign value instead of failing loud."** It recurs as
`else: return None` on an unknown enum (H1, M1), `all([]) → allow` on an unknown action
kind (H3), `0/0 → 0.0` on zero variance (M2), a missing `period` guard that a sibling
function already has (L1, L2), and a broad `except` that buckets env/compute failures into
a routine fallback with no signal (L5, `_context.py`). Every instance shares two traits:
it violates a fail-loud invariant the *same module already documents and enforces
elsewhere*, and it survives the current suite because tests exercise only valid inputs or
monkeypatch past the real code path (H1's seam, L5's `_fit_hmm` stub). The remedy is
uniform — **validate at the choke point and raise the module's standard message; add one
un-mocked negative-path test per gate.**

**Recommended TDD batch order (money-path first, red→green per gate):**

1. **H1 (`_scanner` MACD + `hud/_build` value string)** — live production suppression; the
   ops-loop-silent symptom. Ship first (add the un-mocked `_default_scan_setup` integration
   test). Non-money but highest live impact.
2. **Money-path R-rule batch (one reviewed round):** **H3** (close `ProposedAction.kind`
   or fail-closed guard) → **H2** (`_sizing` multiplier guard) → **M2** (`_correlation`
   zero-variance → None) → **L1** (`atr` period guard) → **L3** (`hud` insufficient_context
   rationale). Bundle behind a single human review per the red line.
3. **needs_human adjudication:** resolve the H3-adjacent empty-applicable taxonomy call and
   the `_context.py` narrowing decision *before* coding item 2's H3 — they gate the fix
   shape.
4. **Non-money hardening:** **M1** (`bb_position` validation, folds in with H1's scanner
   fix), **L2** (`ema` period guard), **L4** (`_regime` sidecar schema guard), **L5**
   (`_regime` HMM-fit observability). Parallelizable; no review round required.
