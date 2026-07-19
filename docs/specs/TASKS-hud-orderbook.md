# TASKS — hud-orderbook

Input: docs/specs/SPEC-hud-orderbook.md. Red-line note: `build_state`
consumes policy verdicts read-only — no policy/ or broker/ files are
touched by any task here (no money-path review round required; verify at
gate that the diff honors this).

### T1: HUD contracts
satisfies: AC-4 (shapes), CONTRACT plan row
files: src/tradekit/contracts/_hud.py, src/tradekit/contracts/__init__.py, tests/unit/contracts/test_hud_contracts.py
done: contract tests green via tk-gate

### T2: render — tabbed OSO-mirror ticket book + scan report HTML
satisfies: AC-1, AC-2, AC-3, AC-10
files: src/tradekit/hud/_render.py, tests/unit/hud/test_render.py
done: AC-1/2/3/10 tests green via tk-gate

### T3: build_state — funnel walk, grade rule, ticket arithmetic
satisfies: AC-4, AC-5, AC-6, AC-7, AC-8
files: src/tradekit/hud/_build.py, tests/unit/hud/test_build_state.py
done: AC-4..8 tests green via tk-gate (AC-4 worked example independently derived pre-freeze)

### T4: hud package verbs + tk hud CLI
satisfies: AC-9
files: src/tradekit/hud/__init__.py, src/tradekit/cli/main.py, tests/unit/hud/test_cli.py
done: AC-9 tests green via tk-gate

## Order / parallelism

T1 first (interface producer). T2 ∥ T3 (disjoint files; both consume T1
contracts; T3 carries the risky unknowns — funnel wiring — so dispatch it
first in the batch). T4 last (consumes T2+T3 via `hud/__init__`).

Batch 1 = T1+T2+T3 (red together, green together); batch 2 = T4.

### T5: wire real funnel into build_state (post-MVP gate for live use)
satisfies: AC-4 (real derivation path; SPEC Unknowns "RESOLVED by reference")
files: src/tradekit/hud/_build.py, tests/unit/hud/test_build_state.py
done: size_qty default = real mae.size_position wiring; scan/regime/metric gates in report; tk-gate green
