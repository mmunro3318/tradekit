# Agent metrics — producing-agent assessments per review round

Accumulating register: one section per review round. Defect counts are those
attributable to the agent's own scope (a test gap that fails to catch an
implementation bug counts against BOTH agents).

## Round 1 — 2026-07-12 — P0 M0.2/M0.3 (commits d446ffb, 5f93f15)

Reviewer: code-reviewer agent. Verification: `uv run pytest` (49 passed),
`uv run ruff check .` (clean), `uv run mypy` (clean, 15 files). All defects
below were confirmed by executing reproduction scripts, not by inspection alone.

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| tdd-p0 | tests/ (38 test fns), ASSUMPTIONS.md | 1 (shared) | 1 (shared) | 3 | B+ | Exemplary assumption-pinning discipline and assertion messages; but the golden-path bias let the one HIGH through — quantize tested only on power-of-ten ticks, tamper tests cover only 2 of 7 hashed columns. |
| dev-p0 | src/tradekit/{contracts,ledger} | 1 | 3 | 3 | B | Clean architecture, deep-module discipline honored, FTS/hash/retry mechanics solid; but the G2 quantize guarantee is falsified for non-power-of-ten ticks, and two silent-coercion paths (naive datetimes, Decimal payloads) violate TD-17/ASSUMPTIONS-10 quietly. |

Shared defects: D1 (quantize grid — dev wrote the bug, tdd's tick coverage
missed it); D2 (EventFilter naive-datetime — ASSUMPTIONS never pinned
awareness on filters, impl inherited the hole).

Out-of-scope carried risk noted for the M0.1 producer (prior round, ungraded):
pyproject.toml claims deep-module import enforcement but
`ban-relative-imports = "parents"` does not ban cross-module absolute imports
of `_internals` (probe-verified). DESIGN §1 requires this lint "from day one".
