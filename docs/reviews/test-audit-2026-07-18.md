# Test-Suite Quality Audit — 2026-07-18

**Trigger:** Mike's suspicion of "green-count theater" — hundreds of passing tests
that don't protect behavior.
**Method:** six parallel auditor agents, one per domain slice, grading all 683 test
functions (79 files) against the tk-tdd rubric (behavior/contract/golden/seam vs
impl-coupled/mock-theater/trivial/duplicate/framework/tautology), reading source
alongside tests. Exemplars harvested to `~/.claude/tk-stack/references/tdd-examples.md`.

## Verdict

**The suspicion is largely refuted.** The suite is ~85-90% genuinely protective:
golden vectors carry independent provenance, mocks sit at true external boundaries
(respx at the HTTP wire, clock/bars seams) with real logic executing underneath,
and classic mock-theater ("assert the mock was called") is **absent from all 683
tests**. The adversarial replay suite, ledger tamper matrix, paper-fill boundary
tests, and policy gate tests would catch the regressions that matter for a system
that moves money.

Two honest caveats:

1. **The headline test count is inflated.** ~90 executed cases in
   `test_event_payloads.py` + `test_broker_accounts.py` re-test pydantic machinery
   (frozen/extra-forbid/required-field parametrize sweeps). The perception of
   "hundreds of tests" partly comes from these. They aren't harmful, just padding.
2. **The real risk is gaps, not garbage.** Several safety-relevant paths have zero
   coverage (below). A green gate today does not attest to those behaviors.

## Per-slice grades

| Slice | Grade | Garbage est. | Standouts | Weak spots |
|---|---|---|---|---|
| broker + cli | A- | <15% | paper_fills G5 boundaries, pipeline event-ordering, reconcile phantom-fill | cli_memory_report duplicates, constants tautology |
| mae_data + indicators | A | ~0-5% | golden vectors w/ provenance, cache partial-hit, decimal-precision trap | 2 internals-coupled tests |
| thesis + review + memory | A- | <10% | grade ambiguous-bar, end-to-end void loop, subprocess kill test | **test_report.py pnl tautology**, memory search breadth |
| policy | A- | <10% | R-015 void farm, live-halt stands-after-refusal, series MDD regression | trivial dial one-liners |
| mae core | A | <5% | discriminating fixtures (regime threshold, weekend join) | 1 duplicate, costs side tautology |
| contracts + ledger + replay | B+ | ~20% by case count | quantize goldens, 6-column tamper matrix, p2 adversarial | **pydantic sweeps (~90 cases), empty-fixture conformance tests** |

## Fix backlog — garbage removal (low effort, honest count)

- [ ] `tests/unit/contracts/test_event_payloads.py`, `test_broker_accounts.py`:
      collapse frozen/extra/required sweeps to one `StrictFrozenModel` inheritance
      pin each (~-85 green cases, zero protection lost).
- [ ] `tests/unit/report/test_report.py::test_pnl_snapshot_...`: rewrite to seed a
      graded thesis with `account_ref` and assert the seeded pnl value appears
      (currently a tautology — worst test in the suite).
- [ ] `tests/contract/test_broker_port.py`: seed real fills/positions so the
      ascending-order and list-shape pins are under pressure; assert the
      404→"rejected" mapping it registers a route for; add `ManualBroker` to
      `CASE_BUILDERS` or correct the docstring's "every adapter" claim.
- [ ] `tests/unit/cli/test_cli_memory_report.py`: collapse 4 stub-smoke duplicates to 1.
- [ ] Delete/park: alpaca pinned-constants tautology, `test_costs.py::test_symmetric_sides`
      (until `side` is read), scan_markets duplicate, stale "RED" docstrings in
      `test_strategies_registry.py`.

## Fix backlog — coverage gaps (the actual risk, ordered by stakes)

**Money-path / safety:**
- [ ] `AlpacaBroker.positions()` — zero coverage anywhere (one of five BrokerPort methods).
- [ ] Live-routing fail-closed conjunction: mixed corners untested (dial-true/keys-absent,
      dial-false/keys-present). `_alpaca.py` docstring claims "full routing-matrix
      coverage" — false; fix tests AND the docstring.
- [ ] `httpx.HTTPError` transport branch in `_get`/`_post` (connection error ≠ status code).
- [ ] `evaluate_pure` anti-permissive allowlist: no test proves an unknown RuleHit
      outcome fails CLOSED.
- [ ] R-016 "promote" wiring end-to-end through `policy.evaluate()` → `_context.assemble()`
      (currently only unit-tested against hand-built dicts).
- [ ] R-017/R-018 ledger-derived drawdown resolution through `_context.assemble()`.
- [ ] `policy.status()` — public verb, zero direct tests.
- [ ] Demotion triggers: 2 of 3 unimplemented (ASSUMPTIONS 92 confirmed).
- [ ] Ledger tamper matrix covers UPDATE only — row DELETE and mid-chain INSERT undetected-untested.
- [ ] `fills(since)` boundary inclusivity (>= vs >) never pinned with data.
- [ ] `ManualBroker.account()/.positions()` projection arithmetic (no golden analog
      to test_paper_account_state.py).

**Correctness / robustness:**
- [ ] Review pipeline failure modes: `run_review`/`verify_claim` never tested to
      catch ReviewTimeout / OutputTooLarge / malformed JSON and set `failure_mode`
      instead of crashing (adapters raise them; pipeline handling unproven).
- [ ] `costs.price_friction` slippage-active branch (notional > $100) — zero coverage.
- [ ] `memory/_search.py` wiki-merge half (wiki results, cross-source ordering) — zero coverage.
- [ ] `memory/_brief.py` whole-section drop fallback.
- [ ] `daily_memo` file-write side effect never verified on disk.
- [ ] mae: `get_regime` public delegate, per-timeframe scan match correctness,
      adx `total==0` branch, macro `timeframe!="1d"` guard, alpaca/coingecko
      rate-limit wiring (only kraken proves blocking), cache zero-length window,
      `_asset_class_for_symbol` equity branch, retry-then-succeed + pagination.
- [ ] CLI: `tk thesis approve/reject/void`, `tk grade show`, `tk ledger query --since/--until`.

## Process note

Audit performed by 6 sonnet agents with per-slice rubric prompts; findings
spot-checked against source by the CTO thread. Grep-count "mock" flags proved to be
`monkeypatch` seam calls, not `Mock` objects, in both flagged files — future audits
should grep `Mock\b|MagicMock` before suspecting a file.
