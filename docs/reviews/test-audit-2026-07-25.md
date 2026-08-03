# Test Suite Audit — 2026-07-25 (tdd-audit workflow)

## Scope
- Test slice reviewed:
  - Entire tests tree: tests/unit, tests/contract, tests/replay, tests/golden, tests/ASSUMPTIONS.md.
- Adjacent slices checked:
  - Doctrine and baselines: AGENTS.md, CLAUDE.md, docs/DESIGN.md, docs/GLOSSARY.md, docs/reviews/test-audit-2026-07-18.md, docs/reviews/test-audit-2026-07-23.md, docs/reviews/agent-metrics.md.
- Unreviewed areas:
  - None in requested scope.

## Verdict
- Overall assessment:
  - The suite is materially stronger than the 2026-07-23 seam-failure state: critical scan-vocabulary and audit-wiring regressions now have explicit contract tests and targeted replay-level pressure.
  - Remaining risk is concentrated in seam-default coverage and several weakly discriminating attrition-log assertions, not broad mock-theater.
- Green-count caveat:
  - Pass counts are still inflated by shape/inheritance contract sweeps and repeated seam-smoke checks. These tests are not useless, but they overstate behavioral protection if read as product-level confidence.

## Findings

### 1) HIGH — HUD default seam wiring is still under-protected beyond scan_setup
- Severity:
  - HIGH
- File and test name:
  - tests/unit/hud/test_build_state.py (all tests monkeypatch seams)
  - tests/unit/hud/test_hud_cli.py (all path-critical seams monkeypatched)
  - tests/unit/hud/test_serve.py (all path-critical seams monkeypatched)
  - tests/contract/test_scan_setup_vocabulary_contract.py::test_real_scanner_produces_nonempty_signal_tags_for_a_bullish_volume_confirmed_symbol
- What behavior is at risk:
  - Production defaults for sizing/policy/open-position seam wiring can drift or break while HUD tests remain green, because only scan_setup default is exercised for real.
- Why the test is low-signal or incomplete:
  - Real default_scan_setup now has one strong contract test, but equivalent real-path tests do not exist for default sizing_info, default open_position_symbols, and default evaluate_policy binding.
- Recommended action:
  - add

### 2) MEDIUM — Attrition log summary/header assertions are too weak to detect formatting regressions
- Severity:
  - MEDIUM
- File and test name:
  - tests/unit/hud/test_hud_attrition.py::test_header_contains_timestamp_and_equity_and_universe_size
  - tests/unit/hud/test_hud_attrition.py::test_summary_line_contains_per_stage_kill_counts
- What behavior is at risk:
  - Human-facing attrition telemetry can degrade (wrong universe count, missing explicit per-stage counts, malformed header) without test failure.
- Why the test is low-signal or incomplete:
  - Assertions rely on generic substrings such as “2026”, “2”, “5000”, and symbol presence rather than discriminating structured expectations tied to rendered sections.
- Recommended action:
  - rewrite

### 3) MEDIUM — Duplicate unknown-filter validation pins create maintenance noise without increasing protection
- Severity:
  - MEDIUM
- File and test name:
  - tests/unit/mae/test_scan_markets_verb.py::test_macd_signal_unknown_value_raises_value_error
  - tests/unit/mae/test_scan_vocab.py::test_unknown_macd_signal_value_raises_before_any_bar_fetch
- What behavior is at risk:
  - Rule changes to error message/value semantics can force redundant churn across two near-identical tests while adding little additional defect detection.
- Why the test is low-signal or incomplete:
  - Both tests pin same user-visible behavior (unknown macd value fails before fetch). The second file already covers message shape and pre-fetch invariant comprehensively.
- Recommended action:
  - consolidate

### 4) MEDIUM — Alpaca positions failure taxonomy lacks direct unit pressure
- Severity:
  - MEDIUM
- File and test name:
  - tests/contract/test_broker_port.py::test_positions_returns_a_list_with_real_element_shape_when_seeded
  - tests/unit/broker/test_alpaca_broker.py (no direct positions error-path tests)
- What behavior is at risk:
  - A malformed or transiently failing venue positions response could regress to silent coercion, opaque exceptions, or wrong typed projection while conformance remains green.
- Why the test is low-signal or incomplete:
  - Current coverage exercises happy-path shape for Alpaca positions via conformance, but does not directly pin VenueUnavailable/VenueRejected taxonomy and malformed-200 handling for positions specifically.
- Recommended action:
  - add

### 5) LOW — Contract-model sweep density still pads confidence metrics
- Severity:
  - LOW
- File and test name:
  - tests/unit/contracts/test_event_payloads.py (broad model construction/inheritance matrix)
  - tests/unit/contracts/test_broker_accounts.py (base-class/inheritance checks)
- What behavior is at risk:
  - Minimal regression risk; this is primarily a signal-to-noise and maintenance-cost issue.
- Why the test is low-signal or incomplete:
  - Many assertions retest framework-level invariants (class inheritance, frozen base behavior) after prior consolidation already removed the worst duplication.
- Recommended action:
  - consolidate

## Coverage gaps
- Missing seam coverage:
  - No real-path default seam test for hud default sizing_info wiring.
  - No real-path default seam test for hud default open_position_symbols behavior.
  - No real-path default seam test ensuring build_state invokes policy through default evaluate_policy binding (without seam replacement).
- Missing negative-space coverage:
  - No direct Alpaca positions negative-path unit tests for malformed JSON body, 5xx, and taxonomy mapping.
- Missing loud-failure coverage:
  - Attrition render tests do not loudly fail on subtle summary/header schema drift because assertions are substring-loose.

## Low-signal inventory
- Tests to delete:
  - None recommended for immediate deletion.
- Tests to consolidate:
  - tests/unit/mae/test_scan_markets_verb.py::test_macd_signal_unknown_value_raises_value_error
  - tests/unit/mae/test_scan_vocab.py::test_unknown_macd_signal_value_raises_before_any_bar_fetch
  - tests/unit/contracts/test_event_payloads.py (selected construction/inheritance repetitions)
- Tests to rewrite:
  - tests/unit/hud/test_hud_attrition.py::test_header_contains_timestamp_and_equity_and_universe_size
  - tests/unit/hud/test_hud_attrition.py::test_summary_line_contains_per_stage_kill_counts

## Action items
1. Add a HUD integration-style unit test that calls build_state with default seams intact except deterministic runtime bars/clock, and asserts default sizing and policy bindings produce a policy-guarded ticket path.
2. Add focused Alpaca positions taxonomy tests in tests/unit/broker/test_alpaca_broker.py for malformed-200, 5xx, and venue-rejection mapping.
3. Rewrite attrition-render tests to assert section-scoped lines with explicit count/value expectations, not generic substring presence.
4. Consolidate duplicate unknown-filter tests by keeping the more discriminating scan_vocab version and trimming overlap in scan_markets_verb.
5. Continue contract-sweep deflation by replacing repeated per-model shape checks with narrower behavior-critical examples where feasible.

## Notes
- Validation performed:
  - Static inventory and pattern probes across full tests tree.
  - Targeted pytest probes run successfully:
    - uv run pytest -q tests/unit/cli/test_cli_memory_report.py tests/unit/report/test_report.py tests/contract/test_scan_setup_vocabulary_contract.py tests/replay/test_p3_end_to_end.py
  - Additional coverage probes for seam-default usage and gap confirmation were performed with focused ripgrep searches.
- Open questions:
  - Should HUD default evaluate_policy binding be tested as an explicit integration seam contract, or remain covered only via lower-level policy and CLI behavior tests?
  - Should attrition renderer output adopt a parseable mini-schema to reduce substring-fragility and make telemetry assertions stricter?

## Explicit non-edit statement
- No production code or test code was modified. This audit only produced report artifacts.
