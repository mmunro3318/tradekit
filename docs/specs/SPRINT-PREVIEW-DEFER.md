# SPRINT-PREVIEW-DEFER — unblock the paper funnel (2026-09-06)

CTO pins for two small batches. Context: docs/research/crypto-scope-2026-09-06.md
§4 and cc-dev-log 2026-09-06. Paper-only sprint; nothing here touches live.

## Defect (batch A)

`hud._build.build_state` runs a scan-time policy preview with
`thesis_id = "interim-thesis-<sym>"` (no ledgered thesis). `policy.evaluate`
then returns `RuleHit(rule_id="R-010", outcome="fail",
measured="insufficient_context:thesis_review_artifact_id")` and
`RuleHit("R-012", "fail", "insufficient_context:recorded_sizing_usd")`.
`_default_evaluate_policy` treats every `fail` hit as a deny, so
`decision.allowed` is False, no `AdvisoryTicket` is appended, and
`cadence.run_once` (entries from `state.tickets` only) can never open a
position. Round-22 already ratified the BINDING side (ASSUMPTIONS 178.2:
evaluate at `reviewed`, reject on deny) — the preview side was never fixed
because `test_run_once.py` seams `cadence.build_state` and `test_build_state.py`
seams `hud._build.evaluate_policy`, so no test ever ran the real preview.

## Batch A pins — preview deferral (hud only; `policy/` untouched)

A1. Site: `src/tradekit/hud/_build.py::_default_evaluate_policy` ONLY. No
    change to `policy/`, `contracts/`, `AdvisoryTicket`, or `build_state`'s
    control flow.
A2. Deferral set is exactly `{"R-010", "R-012"}` and applies ONLY to a hit
    with `outcome == "fail"` AND `measured` starting with
    `"insufficient_context:"`. A real R-010/R-012 `fail` (measured is a value,
    not `insufficient_context:*`) still denies at preview.
A3. Decision rule: `allowed = verdict.allow or (failing and all(_deferrable(h)
    for h in failing))` where `failing = [h for h in verdict.rule_hits if
    h.outcome == "fail"]`. Any other failing rule (R-001 halt, R-002 tier,
    R-003 balance, R-004, R-005, R-007, R-008, R-009, R-013, R-014, R-015,
    R-017, R-018) denies exactly as today, deferred hits or not.
A4. When allowed by deferral: `verdict_id = verdict.verdict_id` (the ledgered
    deny verdict's id — a real event id, never fabricated, never None) and
    `rationale = "allow (deferred at preview: R-010, R-012 — re-evaluated at
    binding)"` listing the deferred rule ids in ascending order, only those
    that actually deferred. Substring pins for tests: `"deferred at preview"`
    and each deferred rule id.
A5. When `verdict.allow` is True: unchanged (`rationale="allow"`).
A6. When denied: unchanged rationale format (`"R-xxx: measured vs limit; ..."`)
    and it MUST still include the deferred hits' text if any non-deferrable
    hit also failed (the audit line stays complete).
A7. The binding chain (`hud._serve._make_binding_proposal` +
    `evaluate_policy_binding`, and `cadence._run_entries`) is NOT touched:
    R-010/R-012 are evaluated for real there against the ledgered thesis.
A8. Ticket `warnings` already carries "interim provenance: thesis id not yet
    backed by a ledgered thesis" — no new warning string.

### Batch A tests (RED) — behavior, real path

Seams allowed: `mae._runtime.get_closed_bars`, `mae._runtime.clock`, and the
four sanctioned hud seams (`scan_setup`, `sizing_info`,
`open_position_symbols`; `evaluate_policy` stays at its DEFAULT for these
tests — that is the point). Ledger: `TK_DATA_DIR` -> `tmp_path` (see
`tests/unit/cadence/test_run_once.py` for the real-verb harness: flat
ATR(10) price=100 bars, `broker.create_paper_account` for
`PolicyDials.load().default_account_ref`, equity = the
`paper_starting_equity_usd` dial). Tests live in a NEW file
`tests/unit/hud/test_build_state_preview_policy.py`.

T-A1 (the defect): fresh paper account, passing setup seam, sizing seam
     -> `build_state(...)` yields exactly one ticket for the symbol; its
     `policy_verdict` GateResult has `passed=True` and rationale containing
     `"deferred at preview"`, `"R-010"`, `"R-012"`; ticket `verdict_id` is
     a non-empty string equal to the `verdict_id` of the most recent
     `VerdictIssued` event in the ledger for that thesis_id.
T-A2 (deferral is not a bypass): same harness + `policy.halt("test")` (real
     verb, R-001) -> zero tickets; the `policy_verdict` gate `passed=False`
     and rationale contains `"R-001"`.
T-A3 (non-deferrable deny still wins alongside deferrals): drive a real
     R-005 breach — sizing seam returns qty such that notional >
     `max_position_pct_paper * equity` -> zero tickets, rationale contains
     `"R-005"` AND `"R-010"` (audit line complete, A6).
T-A4 (unit, the rule itself): `_default_evaluate_policy` with the real
     `policy.evaluate` on a proposal for an account that exists — a
     deny-with-only-R-010/R-012-insufficient verdict returns `allowed=True`;
     this is T-A1 at the function boundary, keep it if it costs < 20 lines,
     drop it if it needs a policy mock (no tradekit-internal mocks).
T-A5 (regression guard for the cadence seam blind spot): one test in
     `tests/unit/cadence/test_run_once.py`'s style that runs `run_once` with
     `cadence.build_state` LEFT REAL and only the hud/mae seams patched ->
     one paper position opens (the round-trip T3-AC-4 already proves the
     rest). If the harness cost exceeds ~60 lines, flag it as ASSUMPTIONS
     and ship T-A1..A3 without it.

### Batch A ASSUMPTIONS (to ratify, next free number)

- Preview deferral of R-010/R-012 `insufficient_context` at scan time is
  sanctioned because the binding chain re-evaluates both against the
  ledgered thesis (178.2). Any rule other than those two never defers.

## Batch B pins — Kraken pair mappings (mae/_data only)

B1. Add to `_SYMBOL_TO_KRAKEN_PAIR` and `_KRAKEN_RESULT_KEY` in
    `src/tradekit/mae/_data/kraken.py`, verified against the LIVE
    `/0/public/OHLC` endpoint on 2026-09-06 (721 rows each at interval=60):

    | symbol | request pair | result key |
    |---|---|---|
    | ZEC/USD | ZECUSD | XZECZUSD (legacy X/Z) |
    | TIA/USD | TIAUSD | TIAUSD |
    | DOT/USD | DOTUSD | DOTUSD |
    | ADA/USD | ADAUSD | ADAUSD |
    | SUI/USD | SUIUSD | SUIUSD |
    | FIL/USD | FILUSD | FILUSD |
    | ALGO/USD | ALGOUSD | ALGOUSD |
    | HBAR/USD | HBARUSD | HBARUSD |
    | POL/USD | POLUSD | POLUSD |

B2. Tests: extend the existing kraken provider test file's mapping
    parametrization (find it under `tests/unit/mae_data/`) so each new symbol
    resolves to its request pair AND the response parser accepts its result
    key (ZEC's legacy key is the one that can silently break — pin it with a
    respx fixture whose `result` dict is keyed `XZECZUSD`). No live calls in
    tests.
B3. `hud.DEFAULT_SYMBOLS` is NOT changed in this batch (the 11-pair
    greenlist is a separate CTO decision).

## Files-touched sets

- A: `src/tradekit/hud/_build.py`, `tests/unit/hud/test_build_state_preview_policy.py`,
  (optional) `tests/unit/cadence/test_run_once.py`, `tests/ASSUMPTIONS.md`.
- B: `src/tradekit/mae/_data/kraken.py`, `tests/unit/mae_data/test_kraken*.py`.
Disjoint -> may run in parallel.

## Open tensions found by the first live cadence run (2026-09-07, unpinned)

- T1 R-005 vs min-ATR sizing: `size = equity * risk_pct / stop_pct`; when
  `2*ATR14 < 10%` of price the size exceeds `max_position_pct_paper` and the
  preview denies (LINK $50.73 vs $50.00; SOL $53.78; ETH ~$65). Only names
  with stop_pct >= 10% can enter. Candidate pin: clip inside
  `mae.size_position` to `max_position_pct * equity` (keeps R-012 purity).
- T2 R-012 notional drift: sizing uses the daily close, the ticket the 1h
  close; AKT drifted 3.39% vs the 1% tolerance and was rejected at binding.
  Candidate pin: size at the ticket's limit price, or a ratified tolerance.
- T3 cadence silence on `equity <= 0` / missing account: two digests
  reported `killed_by=sizing` with no warning. Pin: a loud digest warning.
