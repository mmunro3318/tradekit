# Test Suite Audit — 2026-07-23 (adversarial / silent-failure hunt)

Auditor: skeptical senior test-engineering pass, commissioned the night the S1
momentum-filter silence was diagnosed. Scope: 100 test files under `tests/`
(unit/contract/replay/golden), read against the project's own testing doctrine
(`~/.claude/tk-stack/references/tdd-examples.md`, itself harvested from the
2026-07-18 audit) and the "tests protect behavior, not implementation" standard.
Read-only on all source and tests. Prior audit context: 2026-07-18 graded the
suite ~85-90% protective and removed a batch of garbage — that pass was real and
several of its fixes are visible in the current tree. This pass asks a narrower,
harsher question: **does a green suite of this shape catch the class of bug that
actually shipped?** It does not.

---

## (A) Verdict — what "1000+ passing" is actually worth

Blunt: the count is real but it measures the wrong thing. The suite is genuinely
strong at *intra-module* behavior — indicator math, policy arithmetic, broker
adapter conformance, ledger invariants — and that strength is not in dispute. But
the bug that made the flagship S1 scan **structurally incapable of firing a single
trade for its entire life** lived in a *seam between two modules*
(`hud/_build.py` speaks `"bullish"`; `mae/_scanner.py` accepts only
`"bullish_cross"`), and the suite's dominant design choice — monkeypatch every
cross-module seam, test each side in isolation against its own vocabulary — makes
that entire bug-class invisible by construction. Worse than "no test covered it":
one existing test (`test_scan_markets_verb.py:490`) **codifies the silent-drop as
correct behavior** and would have to be deleted to fix the bug. "1000+ passing" is
a strong statement about the pieces and a near-empty statement about the machine
they form. Treat the number as coverage of units, not of the product.

---

## (B) Systemic weaknesses (evidence)

### B1. Every cross-module seam is mocked on both sides — the wiring is never tested

`hud/build_state` has four sanctioned seams: `scan_setup`, `sizing_info`,
`evaluate_policy`, `open_position_symbols` (`hud/_build.py:142-145`). **Every**
`build_state` test monkeypatches the ones it exercises:
`tests/unit/hud/test_build_state.py:144,166,195,247,328,361,371,396,426,454`;
same pattern in `test_serve.py:112`, `test_hud_cli.py:97,128`,
`test_render_ack_buttons.py:84`. The production defaults —
`_default_scan_setup` (`_build.py:124-136`), `_default_sizing_info`
(`_build.py:106-121`), `_default_open_position_symbols` (`_build.py:81-103`) —
have **zero test coverage**. `_default_scan_setup` is the exact function that
carries the fatal `_SETUP_FILTERS` constant into the real scanner, and nothing
ever calls it. The seam pattern is defensible for determinism, but the *default
factory that runs in production* must have at least one test that actually
executes it. It has none.

### B2. `_SETUP_FILTERS` — the production config — is asserted nowhere

`grep` for `_SETUP_FILTERS` / `SETUP_FILTER` across `tests/` returns **zero
hits**. `hud/_build.py:31` (`{"macd_signal": "bullish", "volume_spike": 1.5}`) is
a load-bearing production constant — it decides whether any trade can ever fire —
and no test reads it, let alone validates its values against what the scanner
accepts. A production constant with this much authority and zero assertions is a
latent S1-class outage waiting for the next value typo.

### B3. Input filter vocabulary has no shared source of truth

The project got this right for *output* tags: `tradekit/strategies.py` is the
single registry and `test_strategies_registry.py:50-61` pins by identity that
`_scanner._TAG_STRATEGY is strategies.TAGS`. But that registry governs
`macd_bullish -> momentum` (the tag the scanner *emits*). The *input* filter
values the scanner *accepts* (`"bullish_cross"`/`"bearish_cross"`,
`_scanner.py:251,255`) are bare magic strings with no registry, no enum, and no
test binding the producer (`_build.py`) to the consumer (`_scanner.py`). The
identity-pin discipline that exists for output tags simply does not exist for the
input vocabulary — which is precisely where S1 broke.

### B4. Silent-swallow paths codified as spec, not surfaced as failure

`_scanner._evaluate_symbol_timeframe` ends the `macd_signal` branch with an
unconditional `else: return None` (`_scanner.py:259-260`): any unrecognized value
silently rejects the candidate. `test_scan_markets_verb.py:490-505`
(`test_macd_signal_unknown_value_matches_nothing`) feeds `"sideways"` and asserts
`result["matches"] == []` — i.e. it **enshrines** silent rejection of unknown
values as the contract. There is no test anywhere asserting that a misconfigured
filter value is surfaced loudly (warning, error, or ticket-report reason). The
scanner's `warnings` channel exists (`_scanner.py:349,359`) and is tested for
*insufficient bars* (`test_scan_markets_verb.py:~410-421`) but never for
*unrecognized filter values* — the one failure mode that actually bit.

Adjacent silent-`None` in the money path: `policy/_context.py:691-692`
(`except ValueError: return None` on an empty trade log). The docstring justifies
it, but I found no test proving the downstream policy path treats that `None` as
fail-closed rather than silently permissive — worth a targeted test (see D6).
22 `src` files contain `else: return None` / `except…: return/pass/[]` shapes
(grep, this session); B4 is the exemplar, not the only instance.

### B5. The only end-to-end scanner run uses a disjoint config

`test_p3_end_to_end.py:143-146` is the sole replay test that drives the **real**
`scan_markets`. It uses `filters={"rsi_max": 50}`, `regime_gate=False`.
Production S1 uses `{"macd_signal": "bullish", "volume_spike": 1.5}`,
`regime_gate=True` (`_build.py:31,131`). The end-to-end path exercises a filter,
a regime setting, and a vocabulary that production never uses, and never
exercises the ones it does. The E2E's green tells you the RSI plumbing works; it
says nothing about the shipped momentum path.

### B6. Count inflation (carried from 2026-07-18, still present)

The doctrine file already documents `test_event_payloads.py` re-testing pydantic
machinery (`frozen`/`extra=forbid`/required) across ~16 models × 3 sweeps ≈ ~57
green cases that prove the framework works, not our code. This still stands and
still pads the headline number. Not dangerous — just evidence the raw count
overstates protective coverage by a meaningful margin.

---

## (C) The macd-`"bullish"` bug — would any test have caught it?

**No. And the suite actively protects the bug.** Three independent reasons:

1. **The one test that touches unknown macd values asserts the bug is correct.**
   `test_scan_markets_verb.py:490` proves that an unrecognized `macd_signal`
   value yields `matches == []` *silently*. Production's `"bullish"` is exactly
   such an unrecognized value. So the scanner behaved exactly as this test
   demands — the test was green *because* S1 was broken. Fixing the bug by making
   unknown values loud would turn this test red; it is a test that has to be
   deleted to restore correctness. That is the most dangerous category there is.

2. **The producer→consumer seam is mocked in every hud test.** `build_state`'s
   `scan_setup` seam is monkeypatched to a hand-built `_PassingSetup` with
   `signal_tags = ["macd_bullish", ...]` (`test_build_state.py:69,144`). The real
   `_default_scan_setup` — which passes `_SETUP_FILTERS["macd_signal"] ==
   "bullish"` into the real scanner — is never invoked under test. The vocabulary
   mismatch lives precisely in the gap the mock spans.

3. **No end-to-end run uses the production config** (B5). The disjoint E2E can't
   catch a config-specific vocabulary error it never uses.

**Generalized bug-classes this suite systematically fails to catch:**

- **Cross-module vocabulary / contract drift** — one module emits a string
  another module doesn't accept, each unit-tested against its own dialect.
- **Silent misconfiguration** — a wrong-but-well-typed constant that routes down
  a `return None` / `return []` path; no test asserts misconfig is loud.
- **Dead production defaults** — factory functions that only run outside tests
  (all four `_default_*` seams in `_build.py`).
- **"Green because broken"** — tests written to the observed (buggy) behavior
  rather than the intended behavior, which then lock the bug in.
- **Config-path divergence** — production constants exercised by no test, with
  E2E coverage on a different config than ships.

---

## (D) Prioritized TDD action items (money-path first)

Each is phrased for the tk-implement loop: "write a test that fails when
<behavior> breaks." Ranked by risk; 1-4 are the S1-class holes.

1. **Bind `_SETUP_FILTERS` to the real scanner's accepted vocabulary.**
   Write a test that fails when any value in `hud/_build._SETUP_FILTERS` is one
   the real `mae._scanner.scan` cannot act on. Concretely: feed a fixture
   engineered to satisfy the setup, call the **real** `_default_scan_setup` (no
   `scan_setup` monkeypatch) against a monkeypatched `get_closed_bars`, and
   assert a non-empty match with the expected `signal_tags`. This test would have
   been red for S1's entire life. *Money-path, highest priority.*

2. **Make unrecognized filter values loud — and pin it.** Write a test that fails
   when `scan()` silently drops an unrecognized `macd_signal` (or any filter)
   value. It must assert the bad value surfaces — a `warnings` entry naming the
   value, or a raised error — **not** `matches == []`. This requires a src
   decision (fail-loud vs. warn) and requires **retiring/inverting**
   `test_scan_markets_verb.py:490`, which currently enshrines the opposite. Flag
   for CTO adjudication (ASSUMPTIONS) before the red commit.

3. **Single source of truth for input filter vocabulary.** Write a test that
   fails when `_build` and `_scanner` disagree on accepted `macd_signal` values —
   mirror the `test_strategies_registry.py:50-61` identity pattern, but for the
   *input* enum: one registry of accepted values, asserted from both the producer
   (`_build._SETUP_FILTERS`) and consumer (`_scanner`) sides. Kills the whole
   drift class, not just this instance.

4. **End-to-end on the production config.** Write a replay test that fails when
   `build_state` — real default seams, real scanner, `regime_gate=True`,
   `_SETUP_FILTERS` — produces zero tickets for a fixture engineered to be a valid
   momentum+volume setup. This is the missing E2E: the exact shipped path, no
   `scan_setup` mock. Complements the RSI-only `test_p3_end_to_end.py`.

5. **Cover the production default factories.** Write at least one test per
   `_default_scan_setup` / `_default_sizing_info` / `_default_open_position_symbols`
   (`_build.py:81-136`) that runs the real function end-to-end and fails when its
   wiring breaks. These four functions are what production actually executes and
   currently have zero direct coverage.

6. **Money-path silent-`None` surfacing.** Write a test that fails if
   `policy/_context.py:691-692`'s `None`-on-empty-log propagates into a
   *permissive* policy verdict rather than a fail-closed/neutral one. Then sweep
   the other 21 `src` files carrying `return None`/`except…: pass`/`return []`
   shapes and add a "failure is surfaced" test wherever a money-path branch can
   swallow silently. *Lower priority only because no live outage is tied to it —
   but it is the same bug-class as S1.*

---

## (E) Genuine strengths (credibility check — these are real and should be kept)

- **Discriminating-fixture pattern is genuinely used** where it matters:
  `test_get_regime_verb.py` derives a spike value mathematically pinned *between*
  the correct and buggy thresholds; `test_correlation_verb.py:123` holds weekend
  closes flat so a join-by-position bug breaks a planted r=1.0;
  `test_paper_fills.py` pins a fill at exactly one tick through. These kill
  adjacent-wrong implementations, which is the whole point.
- **Broker conformance suite is real, not theater** (`test_broker_port.py`): both
  adapters run honest offline code paths (respx wire, real sort). The
  ascending-order pin uses a deliberately *out-of-order* fixture
  (`:156-178,401`) so it exercises the real sort, not `sorted([])`; token-refusal
  is pinned per-adapter (`:375-392`); unknown-order maps to the `"rejected"`
  *value*, not just the type (`:413-426`). This is exactly the 2026-07-18 audit's
  garbage-removal items 3a-3d landed — the suite demonstrably self-corrects.
- **Ledger-diff invariants over mock-call assertions**: the validate-before-append
  check via ledger state diff (doctrine's `test_alpaca_broker` zero-events-on-500)
  is the right shape — asserts the durable outcome, survives refactors.
- **Adversarial replay** (`test_p2_adversarial.py` void-farm → R-015) asserts
  exact gate arithmetic AND only-the-expected-rule-fired AND the denial was
  ledgered — three independent failure modes plus a boundary positive control.
- **Mock discipline is clean**: the 2026-07-18 pass found zero `MagicMock`
  theater across 683 functions; fakes return real typed `contracts.*` objects.
  The seam philosophy is sound — the gap (B1) is that it's applied without a
  companion integration test on the *defaults*, not that the seams are wrong.

**Bottom line:** the units are well-tested; the seams are well-mocked and
badly-integrated. The fix is not "more unit tests" — it is a small number of
integration/contract tests that run the real wiring on the real production config,
plus a loud-failure discipline for misconfiguration. Items D1-D4 close the exact
hole S1 fell through.
