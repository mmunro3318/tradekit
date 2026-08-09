---
name: tdd-audit
description: 'Use when you need an exhaustive, behavior-first audit of a test suite, including unit, contract, replay, and golden tests; detecting low-signal tests, mock theater, duplicate coverage, seam gaps, tautologies, and silent-failure blind spots.'
argument-hint: 'Audit a test slice or the whole suite for signal, gaps, and anti-patterns.'
tools: [read, search, execute, edit]
user-invocable: true
---

# TDD Audit

Use this skill when the job is to judge the quality of tests, not to improve the implementation.

## What this skill does
- Audits tests as a product boundary, not a green-count scoreboard.
- Identifies low-signal, redundant, impl-coupled, and tautological tests.
- Checks whether tests protect behavior, contracts, seams, and negative-space failures.
- Produces audit artifacts with concrete findings and action items.

## What this skill does not do
- Never edit production code or test code.
- Never rewrite the suite in place.
- Never turn findings into patches; put remediation only in the audit report.
- Never treat passing tests as proof of quality unless the test would fail on a meaningful regression.

## When to use
- Reviewing a test suite after a green gate that still feels suspicious.
- Auditing for behavior-first coverage, contract drift, seam gaps, or silent-failure blind spots.
- Looking for tests to delete, consolidate, rewrite, or promote into higher-value seam coverage.
- Preparing a report that will drive follow-up implementation work elsewhere.

## Workflow
1. Read the repo instructions and test doctrine first: `AGENTS.md`, `CLAUDE.md`, `docs/DESIGN.md`, `docs/GLOSSARY.md`, `tests/ASSUMPTIONS.md`, prior audit reports, and `docs/reviews/agent-metrics.md`.
2. Scope the audit to a concrete slice, then map the production surface, public interfaces, and seams that slice is supposed to protect.
3. Read the full test slice and adjacent slices that share the same seam or vocabulary.
4. Classify each test by value: behavior, contract, seam, replay, golden, negative-space, or low-signal.
5. Validate only suspicious cases with the narrowest useful probe or command.
6. Record findings in the audit report with severity, exact file/test references, and the specific regression risk.
7. Keep the action items in the report artifact; do not edit source or tests.

## Review criteria
- Delete tests that assert trivia, mirror internals, or duplicate stronger coverage.
- Consolidate repeated cases when one discriminating test would do the job.
- Rewrite tests that green-light the wrong behavior or enshrine silence.
- Add tests where a real seam, contract, or failure mode has no protection.
- Prefer tests that would fail on a meaningful regression and survive behavior-preserving refactors.

## Report requirements
- Lead with findings ordered by severity.
- Include file paths and test names.
- State the behavior at risk, the class of bug it would catch or miss, and the remediation category.
- Add a scope note that names what was reviewed and what remains unreviewed.
- Put action items in the report only; do not apply code changes.

## References
- Report template: [audit-report-template.md](./references/audit-report-template.md)
- Prior audits: [docs/reviews/test-audit-2026-07-18.md](../../docs/reviews/test-audit-2026-07-18.md), [docs/reviews/test-audit-2026-07-23.md](../../docs/reviews/test-audit-2026-07-23.md)
- Metrics register: [docs/reviews/agent-metrics.md](../../docs/reviews/agent-metrics.md)
- Repo test doctrine: [AGENTS.md](../../AGENTS.md), [CLAUDE.md](../../CLAUDE.md)