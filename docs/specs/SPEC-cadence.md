# SPEC — autonomous paper cadence (batch G2, sprint finale)

> Branch: `feature/cadence`. MONEY-PATH (pipeline exit verb, thesis flow,
> order submission) → review round mandatory per task. Seed:
> docs/handoff/HANDOFF-2026-08-03-cadence.md. Recon: confirm-chain map
> (2026-08-03, in-session).
> Mike's ratified red line, structural: every submitted trade passes the
> FULL funnel (setup → sizing → policy PASS); zero discretionary entries;
> drought is reported, never traded around.

## Scope

Three tasks, strict order, each its own red→green→review cycle:

- **T1 strategy-aware chain**: the walk's claiming StrategyDef drives the
  ticket bracket, sizing, horizon, and thesis tag.
- **T2 exit verb**: `broker.execute_exit(thesis_id)` — the missing half of
  the round trip; sells the NET position through the gated pipeline.
- **T3 cadence runner**: `scripts/run_cadence.py` + hourly scheduled task +
  daily Mike digest; paper-only, funnel-only, drought-honest.

## Out of scope
- Any live-account path (four locks untouched; cadence refuses non-paper).
- Confluence audit-awareness, regime pass-through, vocab-validator
  extraction (ticketed chips).
- Short direction; multi-fill/partial exits (172/175 pins stand).
- Kraken-venue execution (paper broker venue-agnostic; advisory unchanged).

## T1 — strategy-aware chain

### Interface pins
```python
# mae/_strategies.py — StrategyDef gains (8th field; supersedes 173.1's
# batch-scoped 7-field ruling, per STRATEGY-PACK.md:128-130 "make it
# strategy-aware via StrategyDef"):
horizon_hours: int = 168        # S4 def sets 48; others default
# The S1/S2/S4 field-set test re-pins to 8 fields (spec-driven re-pin).

# hud/_build.py — AdvisoryTicket gains (additive, default ""):
strategy_key: str = ""
# build_state threads _SetupResult.strategy_key -> ticket.strategy_key.

# hud/_build.py — bracket + sizing become def-aware inside build_state:
#   r_mult = def.r_multiple_override if (def and def.r_multiple_override
#            is not None) else sizing.r_multiple_target
#   qty    = sizing.qty * def.size_scale   (Decimal; S4 halves)
# No def claimed (strategy_key "") -> today's behavior byte-identical.

# hud/_serve.py — _build_minimal_contract(ticket) becomes
# _build_contract(ticket, strategy_def: StrategyDef | None):
#   strategy_tag = def.key if def else "hud-ack-manual"   (manual path
#                  unchanged — Mike's clicks still say hud-ack-manual
#                  when no def claimed)
#   horizon_hours = def.horizon_hours if def else 168
#   VALIDATION (175.3 mandate): horizon_hours <= 0 -> ValueError naming
#   the value, at contract build time
#   horizon_end = clock() + timedelta(hours=horizon_hours)
#   contract["horizon_hours"] = horizon_hours
# Success/failure predicate "by" fields follow horizon_end as today.
```

### Acceptance criteria
```
T1-AC-1: S4-claimed ticket -> bracket TP at 1R (r_multiple_override),
         qty scaled 0.5; S2-claimed -> sizing's own r_multiple_target,
         qty unscaled; unclaimed -> byte-identical to today.
T1-AC-2: ticket.strategy_key == the claiming def's key ("" when manual/
         unclaimed); old ticket fixtures without the field still validate.
T1-AC-3: confirm chain with an S4 def -> ThesisContract.strategy_tag ==
         "s4_reversion", horizon_hours == 48, horizon_end == clock()+48h.
         Manual confirm (no def) -> "hud-ack-manual", 168, +7d: unchanged.
T1-AC-4: horizon_hours <= 0 at contract build -> ValueError naming value.
T1-AC-5: STRATEGIES defs: S1/S2 horizon_hours 168, S4 48 (field-set test
         re-pinned to 8 fields).
```

## T2 — exit verb (MONEY-PATH core)

### Interface pins
```python
# broker/_pipeline.py:
def execute_exit(thesis_id: str) -> OrderAck:
    """Close the thesis's open position through the SAME gated pipeline
    shape as execute_order:
    1. require_state(thesis_id, {"active"}) — exits only close live
       theses.
    2. qty = the broker's positions() NET qty for the thesis's symbol
       (ASSUMPTIONS 170.2 pin: NEVER entry filled_qty; positions() via
       broker.get(account_ref) — venue/derived truth).
       No position row (already flat) -> ExitNothingToClose (new, loud).
    3. policy.evaluate(ProposedAction(kind="submit_order", ..., order=
       <market sell OrderRequest for that qty, limit_price = last close
       per _entry_price's snapshot convention>)) -> deny raises
       PipelineDenied (exits are policy-visible, same as entries).
    4. adapter.submit with the minted VerdictToken.
    Same module-attr seams; no new determinism seams."""

# Exit TRIGGER evaluation (cadence module, pure function — not in the
# pipeline): a thesis exits when, on the last CLOSED 1h bar / clock:
#   close <= stop_price          -> reason "stop"
#   close >= target_price        -> reason "target"
#   clock() >= horizon_end       -> reason "horizon"
# (long-only per 172/175; grade() remains the arbiter of PASS/FAIL —
# the trigger only decides WHEN to flatten.)
```

### Acceptance criteria
```
T2-AC-1: active thesis + open paper position -> execute_exit submits a
         market sell for EXACTLY the positions() net qty; account flat
         after fill; OrderAck returned; exit fill carries the thesis_id.
T2-AC-2: execute_exit on non-active thesis -> require_state error
         (existing taxonomy); on active-but-flat -> ExitNothingToClose.
T2-AC-3: policy deny at exit -> PipelineDenied, no broker call (halted
         account still gets its exit BLOCKED — R-rules see everything;
         document in ASSUMPTIONS: a halt therefore freezes positions
         until resume, ratified deliberate).
T2-AC-4: trigger function: close==stop -> "stop" (touch inclusive);
         close==target -> "target"; both same bar -> "stop" wins
         (conservative, mirrors grading's ambiguous-bar stop-first);
         clock exactly horizon_end -> "horizon"; none -> None.
T2-AC-5: after exit fill, grade(thesis_id) computes pnl off the two
         fills (net-qty golden already pins the arithmetic — regression).
```

## T3 — cadence runner + digest

### Interface pins
```python
# scripts/run_cadence.py (script, argparse-none, exit 0 always unless
# the paper guard trips):
# 1. GUARD: account_ref = PolicyDials.load().default_account_ref;
#    if not account_ref.startswith("paper:"): print + exit 2 — the
#    cadence REFUSES to exist off-paper (Mike red line, structural).
# 2. ENTRIES: state = hud.build_state(greenlist, captured_at=clock(),
#    equity_usd=<paper account equity>). For each ticket whose symbol has
#    no open position and no active thesis: run the strategy-aware
#    confirm chain (T1) -> execute_order. Both policy evaluations stand
#    (confirm-time binding + execute-time) — recon R12 ratified: the
#    two-phase check is deliberate.
# 3. EXITS: for each ACTIVE thesis: evaluate the T2 trigger; on trigger
#    execute_exit -> grade.
# 4. DIGEST: append to docs/digest/DIGEST-<UTC date>.md (one file/day):
#    run timestamp; entries taken (symbol, strategy_key, qty, bracket);
#    exits (symbol, reason, pnl from grade); funnel attrition per symbol
#    (the walk's stage names — 176.6); per-strategy prefilter-kill
#    counts (the S4-never-arms watch-item); promotion_status() summary
#    (tier, graded count toward 30, criteria bools); warnings.
#    A zero-entry zero-exit run appends the drought line — ALWAYS writes.
# 5. Scheduler: schtasks /create /tn "TradeKit Paper Cadence" /sc hourly
#    (registration command documented in the script header, watchdog
#    pattern; NOT auto-registered by tests).
# Determinism: clock/bars via existing seams; the script body is a thin
# main() over a testable run_once(...) function living in
# src/tradekit/cadence/__init__.py (new module — NOT under broker/;
# it composes public verbs only).
```

### Acceptance criteria
```
T3-AC-1: non-paper default_account_ref -> run_once refuses loudly
         (exit-2 path), NOTHING evaluated, no orders.
T3-AC-2: funnel-only: run_once submits ONLY symbols carried by tickets
         from build_state (policy-passed); a run with zero tickets
         submits zero orders and STILL writes the digest (drought line).
T3-AC-3: open-position/active-thesis symbols are skipped for new entries
         (one position per symbol).
T3-AC-4: full paper round trip through run_once across two runs (entry
         run, then trigger-satisfying bars -> exit run): thesis graded,
         promotion_status() graded count increments.
T3-AC-5: digest file per UTC day, append-per-run, contains the pinned
         sections; drought run writes attrition + prefilter-kill counts.
```

## Unknowns register
- U1: paper account equity source for build_state's equity_usd (account()
  settled cash + positions value vs a dial) — finalize at T3 red against
  PaperBroker.account()'s actual shape; flag if ambiguous.
- U2: greenlist source for the runner (hud's own symbol list — reuse its
  constant/source, never a new list).

## Test-plan sketch
T1: unit/hud + unit/mae (re-pins + new ACs). T2: unit/broker/test_pipeline
(+ paper broker fixtures; golden regression T2-AC-5). T3: unit/cadence
(new dir), digest via tmp_path redirection seam if needed (flag seam
design at red). Money-path review rounds after T1+T2 jointly and after T3.
