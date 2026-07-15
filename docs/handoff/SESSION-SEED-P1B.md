# Session seed — SPRINT P1B (indicators + golden vectors)

Paste the block below as the first message of a fresh Claude Code session in
`C:\Users\admin\dev\tradekit`. Written by Fable 2026-07-15 after closing P1A.

---

You are the CTO-successor session for tradekit. Your mission this session is
SPRINT-P1B (indicator library + golden vectors). Do not start any other sprint.

Bootstrap (in order, before any work):
1. Read `docs/handoff/HANDOFF-PRIMER.md` — the ten commandments are binding; §6 is
   this checklist's source of truth if anything here conflicts.
2. Read `docs/handoff/SPRINT-P1B-indicators.md` (your spec) and skim
   `docs/handoff/SPRINT-P1A-data-layer.md` (DONE — its providers/cache are your
   upstream; 178 tests green at commit 61f798d).
3. `git log --oneline -10` + newest entry of `cc-dev-log.md`.
4. `uv run pytest` — must be 178 green BEFORE you change anything.

Workflow (Mike's standing four-stage rule): dispatch a Sonnet TDD agent to write
failing tests from the sprint doc's pins → YOU review test quality (no theater
tests; context-rich assertions) → commit red → Sonnet dev agent implements to
green → commit green → Opus review agent against the sprint checklist → fix
round if FIX-FIRST (expect it; every round so far found HIGH defects) → close
out: dev-log entry, ROADMAP M1.2 boxes, push.

Session-specific context you'd otherwise lack:
- P1A review lessons that generalize: mocks must mirror REAL API shapes (Alpaca
  crypto bug); a module that passes tests but is wired to nothing is a HIGH
  defect (orphaned ratelimit); 4xx/5xx error taxonomy matters.
- Golden vectors are the entire point of P1B: hand-derive them or cross-check
  once against a reference implementation, then FREEZE (see M1.3's precedent in
  `mae/_metrics.py`). Never trust an LLM's mental arithmetic — show the math.
- The yfinance macro provider was deferred from P1A; ignore it unless P1B's
  spec needs it (it shouldn't).
- `.env` has COINGECKO_API_KEY + Kraken read-only keys. Alpaca paper keys may
  be absent — tests must not need them (zero-network guard is already enforced
  suite-wide in tests/conftest.py).
- Mike's context (see memory + `~\.claude\...\memory\mike-vision-answers.md`):
  terse technical docs for AI readers; at milestone END write a Mike-facing
  plain-English primer (what indicators are, what an "edge" is, swing vs day
  trading) + 2-3 infographic prompts he can paste into Microsoft 365 Copilot.
  His universe for any example assets: ETH/SOL/LINK/NEAR/TAO/EIGEN crypto;
  MU/AMD/MRVL + SPY/IWM/DIA ETFs.
- Budget discipline: you are likely Opus or Sonnet, on a capped plan. Sonnet
  agents do the labor; reserve your own tokens for review gates and design
  calls. If a fix agent dies mid-task (usage cap), resume it via SendMessage
  with a state summary — that worked cleanly in P1A.
- End your session by updating this file's replacement (SESSION-SEED-P1C.md)
  if P1B completes, and report to Mike in plain English: what got built, what
  the reviewer caught, what you need from him (likely nothing but Alpaca paper
  keys, still optional).
