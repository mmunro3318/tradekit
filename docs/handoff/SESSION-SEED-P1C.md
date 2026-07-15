# Session seed — SPRINT P1C (regime, scanner, sizing)

You are the CTO-successor session for tradekit. Your mission this session is
SPRINT-P1C (HMM+EWMA regime, market scanner, sizing verb, correlation). Do not
start any other sprint.

Bootstrap (in order, before any work):
1. Read `docs/handoff/HANDOFF-PRIMER.md` — the ten commandments are binding; §6 is
   this checklist's source of truth if anything here conflicts.
2. Read `docs/handoff/SPRINT-P1C-regime-scanner-sizing.md` (your spec) and skim
   P1A/P1B sprint docs (DONE — data layer + indicators are your upstream;
   258 tests green at commit e519719).
3. `git log --oneline -10` + newest entry of `cc-dev-log.md`.
4. `uv run pytest` — must be 258 green BEFORE you change anything.

Workflow (Mike's standing four-stage rule): dispatch a Sonnet TDD agent to write
failing tests from the sprint doc's pins → YOU review test quality (no theater
tests; context-rich assertions) → commit red → Sonnet dev agent implements to
green → commit green → Opus review agent against the sprint checklist → fix
round if FIX-FIRST → close out: dev-log entry, ROADMAP M1.4/M1.5 boxes, push.

Session-specific context you'd otherwise lack:
- **P1B's process upgrade is now the standard**: before committing red, the CTO
  session independently re-verifies any hand/agent-derived fixture numbers
  (second implementation + external reference where one exists) and FREEZES
  them (see ASSUMPTIONS 42/43 for the pattern). It caught a classic Wilder
  seed bug within hours. Do the same for HMM/EWMA fixtures — for HMM use
  pinned seeds and assert on REGIME LABELS/transitions, not float likelihoods.
- **Indicator wiring debt (ASSUMPTIONS 39)**: when `scan_markets` lands, re-point
  tests/unit/mae_indicators/ through the public verb where sensible AND add
  `tradekit.mae._indicators.*` to the TID251 ban list, same commit.
- **`mae._sizing` is pre-built and fully tested** (Kelly negative-clamp + ATR
  position math, fraction-exact golden vectors). P1C story 1 is WIRING it
  (ATR/price fetch → `size_position` verb), not rewriting it. Sizing takes NO
  P&L-history inputs (TD-11/F6) — if a task seems to need account history
  inside size_position, the task is wrong.
- **hmmlearn is NOT installed yet**; P1C adds pandas/hmmlearn (numpy landed in
  P1B). Keep all three out of `contracts`/`ledger` (stdlib-only by design).
- **yfinance macro provider was deferred from P1A** ("defer if fragile") — the
  regime work is its first consumer. Decide early: build it behind the
  MarketDataPort with stale-flag degradation (it is macro/supplementary, so
  degrade — never raise — per P1A's conformance rules), or descope regime
  inputs to crypto-native data for MVP. Flag the decision to Mike either way.
- `.env` has COINGECKO_API_KEY + Kraken read-only keys (both verified). Alpaca
  paper keys may still be absent — tests must not need them (zero-network
  autouse guard in tests/conftest.py covers the whole suite).
- Known traps that already bit someone: canonical MAE doc's example NUMBERS are
  illustrative, not golden (its Kelly example is self-inconsistent); Binance
  futures is US-geo-blocked (derivatives = Kraken Futures/Coinalyze, G6);
  `quantize` snaps to tick GRID; naive datetimes are validation errors
  everywhere, deliberately.
- Mike's context (see memory + `~\.claude\...\memory\mike-vision-answers.md`):
  terse technical docs for AI readers; at milestone END write a Mike-facing
  plain-English primer (this time: what a "regime" is, why sizing beats
  stock-picking, what correlation does to a small portfolio) + 2-3 infographic
  prompts for Microsoft 365 Copilot (see docs/primers/P1B-indicators-primer.md
  for the house pattern). His universe for examples: ETH/SOL/LINK/NEAR/TAO/EIGEN
  crypto; MU/AMD/MRVL + SPY/IWM/DIA ETFs.
- Budget discipline: Sonnet agents do the labor; reserve your tokens for review
  gates, fixture verification, and design calls. If an agent dies mid-task
  (usage cap), resume it via SendMessage with a state summary — worked cleanly
  in P1A and P1B (in P1B the fix had already landed before the cap hit;
  check `git status` + run pytest before assuming work was lost).
- End your session by writing SESSION-SEED-P2.md if P1C completes, and report
  to Mike in plain English: what got built, what the reviewer caught, what you
  need from him (likely: nothing hard-blocking; Alpaca paper keys remain
  optional-but-useful).
