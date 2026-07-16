# Session seed — SPRINT P2 (thesis lifecycle + policy engine)

You are the CTO-successor session for tradekit. Your mission this session is
SPRINT-P2 (thesis state machine, grading wiring, rules R-001–R-016, promotion
machine). Do not start any other sprint. P2 is the anti-gaming spine — the
done-gate is ADVERSARIAL replay scenarios, not happy paths.

Bootstrap (in order, before any work):
1. Read `docs/handoff/HANDOFF-PRIMER.md` — ten commandments binding; §6 wins
   on conflict.
2. Read `docs/handoff/SPRINT-P2-thesis-policy.md` (your spec) and DESIGN §7 +
   §10 (policy engine, thesis lifecycle, VOID rules §10.4). Skim the P1C
   sprint doc's addendum for the runtime-seam pattern you'll reuse.
3. `git log --oneline -10` + newest entry of `cc-dev-log.md`.
4. `uv run pytest` — must be 338 green BEFORE you change anything.

Workflow (Mike's standing four-stage rule, now 4 sprints proven): Sonnet TDD
agent writes failing tests from the sprint doc's pins → YOU review test
quality + independently re-derive every hand-derived fixture (freeze gate,
ASSUMPTIONS 42/43/54 pattern — it has caught a defect every sprint) → commit
red → Sonnet dev implements to green → commit green → Opus review against the
sprint checklist (pre-register the money-gating logic for Opus focus: VOID
handling, promotion accounting, R-rule verdicts) → fix round (expect
FIX-FIRST; every deep-logic sprint has had one) → close out: dev-log,
agent-metrics, ROADMAP M2.x, Mike primer, SESSION-SEED-P3.md, push.

Session-specific context you'd otherwise lack:
- **`thesis._grading.evaluate_criteria` is DONE and frozen** (12 tests) —
  P2 story 2 is WIRING it into `thesis.grade()` + re-pointing tests
  (ASSUMPTIONS 23), never reimplementing. Same for `mae.compute_strategy_
  metrics` (feeds promotion decisions) and `mae.size_position` (thesis.submit
  calls it and emits the SizingComputed event — that emission is P2's job,
  pinned in ROADMAP M1.4's note).
- **Standing rules learned P1A→P1C** (all have bitten): every hand-derived
  fixture gets the CTO freeze gate before red-commit; every file-writing
  module gets a path seam (_cache_path/_models_dir precedents) and tests
  tmp-path it; verbs call internals via module attributes so dotted-path
  monkeypatching works; TDD agents FLAG schema ambiguities for CTO
  ratification instead of improvising (ASSUMPTIONS 47/51-54/57 precedents);
  mocks must mirror REAL shapes.
- **VOID is the #1 gaming vector** (§10.4, primer trap list): measurable
  invalidations auto-evaluate; structural ones need attestation + reviewer
  sign-off; R-015 caps the rate. Do not soften any leg. Same-bar priority is
  failure > invalidation > success (ASSUMPTIONS 25) — already enforced in
  _grading, keep it enforced at the lifecycle level.
- **Anti-permissive house defaults**: every ambiguity resolves AGAINST the
  agent/trade (ASSUMPTIONS 25/53/54). "neutral" regime = no-recommendation;
  scan matches are ADVISORY — the policy engine you are building is the
  enforcement point and must never treat a scan match as permission.
- ASSUMPTIONS 57(f): the strategy-tag mappings in _scanner/_regime are
  PROVISIONAL — P2's strategy_tag registry re-derives them, same commit.
- Deps: numpy/pandas/hmmlearn/scipy/yfinance live in mae/ ONLY; contracts/
  ledger/thesis/policy stay stdlib+pydantic (thesis/policy strict-mypy per
  pyproject).
- `.env`: CoinGecko + Kraken read-only + Alpaca PAPER keys (all verified
  live). Kraken + Alpaca keys were pasted in chat; Mike rotates before P3
  live use. Tests need NO keys (zero-network autouse guard).
- Mike's context (see memory): terse docs for AI readers; milestone-end
  Mike-facing primer (P2 topics: what a thesis contract is, why adversarial
  review beats vibes, how promotion gates work — house pattern in
  docs/primers/) + 2-3 M365 Copilot infographic prompts. Universe examples:
  ETH/SOL/LINK/NEAR/TAO/EIGEN, MU/AMD/MRVL, SPY/IWM/DIA. NEW (2026-07-16):
  universes are per-portfolio/per-agent with watch-only benchmark assets —
  design portfolio/policy config accordingly (memory: mike-vision-answers).
  Mike is also prop-trading-curious (vision only): keep policy rule-sets
  pluggable per account so prop-style constraint packs are a config, not a
  rewrite.
- Budget discipline: Sonnet does the labor; your tokens go to review gates,
  fixture verification, design pins. Agents dying at usage caps is NORMAL —
  check `git status` + `uv run pytest` before assuming work was lost, then
  resume via SendMessage with a state summary (3-for-3 clean recoveries).
- End of session: SESSION-SEED-P3.md, plain-English report to Mike (what got
  built, what the reviewer caught, what you need from him — likely nothing;
  P3 will want the Kraken key rotation).
