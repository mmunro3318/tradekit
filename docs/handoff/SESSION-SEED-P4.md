# Session seed — SPRINT P4 (live proof — the MVP done-gate)

You are the CTO-successor session for tradekit. P4 is SMALL in code and
LARGE in ceremony: every step pairs with Mike, real dollars move, and the
finish line is the MVP done-gate. Do not start P5-anything.

Bootstrap: HANDOFF-PRIMER §1 → SPRINT-P3-P4 doc (P4 stories + both addenda)
→ git log + newest cc-dev-log entry → `uv run pytest` (must be 781 green)
→ **check the Mike-blocked preconditions below; if any is missing, your
session is a prep/hardening session, not a live session.**

MIKE-BLOCKED PRECONDITIONS (all of them, no exceptions):
1. Kraken read-only key ROTATED (chat-pasted 2026-07-14).
2. Alpaca PAPER keys ROTATED (chat-pasted 2026-07-16).
3. Alpaca LIVE keys created + $50–100 funded (keys enter .env only, never
   echoed, never committed — TD-19; if a key appears in chat, STOP and have
   him rotate immediately).
4. Mike has approved prompts/rubric-thesis-v1.md (P3 deferral).

P4 CODE DEBTS (from P3, all pinned in ASSUMPTIONS rounds 16-22):
- AlpacaBroker adapter (live) passing the SAME conformance suite; replace
  the TEMPORARY live:→PaperBroker routing + add the pinned test that live:
  no longer resolves to PaperBroker (round-19 duty).
- Alpaca PAPER dress rehearsal through the real API (story 1) — order
  lifecycle parity vs PaperBroker conformance.
- Streaming subprocess output caps (round-22 LOW deferral) if reviewer use
  scales; kraken read-only balance tracking for advisory reconcile.
- Ring-3 seam-interaction scenarios (review round 6 process note): halt ×
  polling, reconcile × advisory, token × re-promotion — the defect mass
  lives at seams now, extend the adversarial suite there.
- NO auto-resume on the live path, EVER: a live-path HaltSet clears only by
  Mike's manual `tk policy resume` (verify this is structurally true before
  the first live order; add the pin if it lives only in prose).

THE LIVE SEQUENCE (story 3-5, every step logged + paired):
readiness report → Mike's `tk promote confirm` (two-man rule) → 3 trades
max, long-only, R-004 allowlist, ≤$25 each → `tk account reconcile` green
after EACH → auto-revert to T1 (R-011) → `tk report snapshot` →
`verify_claim` with a NON-Anthropic model confirms trades/settlement/P&L vs
broker records. **Then STOP: celebrate, retro in the dev log, primer for
Mike, and the P5 conversation is his to open.**

Standing process (six sprints proven): four-stage batches, CTO freeze gate
on every fixture, pre-registered Opus review focus (P4's: the Alpaca
adapter's error taxonomy + the live halt path + key handling), ASSUMPTIONS
flag-don't-improvise, stop-and-flag before any test edit, path/clock seams
for every writer, "what happens to this test in a month" determinism check.
Codex tag-team pattern available (docs/handoff/CODEX-HANDOFF-2026-07-17.md
+ docs/research/codex-brief.md) — if a Codex shift ran, full gate + review
round over its diff BEFORE building on it.

Mike-facing duty at the end: the MVP retro primer (what the live proof
proved, what the numbers were, what P5 options exist: more strategies,
prop-style constraint packs, the research loop, universe expansion) + the
celebration he's earned. Universe + red lines per mike-vision-answers
memory (NO event markets, ever).
