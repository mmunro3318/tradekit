# Session seed — SPRINT P3 (paper trading, review, reporting)

You are the CTO-successor session for tradekit. Your mission is SPRINT-P3
(BrokerPort + PaperBroker, execute_order two-phase pipeline, adversarial
review module, reporting/memory) per docs/handoff/SPRINT-P3-P4-paper-to-live.md.
Do not start P4 (live) — that phase needs Mike's keys + funding decisions.

Bootstrap (in order, before any work):
1. docs/handoff/HANDOFF-PRIMER.md §1 (ten commandments) — binding.
2. The P3-P4 sprint doc + DESIGN §8 (broker), §12 (review), §11 (memory);
   skim the P2 addendum (docs/handoff/SPRINT-P2-thesis-policy.md) for the
   pins P3 inherits.
3. `git log --oneline -10` + newest cc-dev-log.md entry.
4. `uv run pytest` — must be 594 green BEFORE anything changes.
5. **Check whether Mike has signed off on rules/RULES.md + config.toml dials
   (P2's one open DoD item). If not, re-request in your first report.**

Workflow: the standing four-stage rule (Sonnet TDD → CTO gate w/ independent
fixture re-derivation → red commit → Sonnet dev → green commit → Opus review
with PRE-REGISTERED focus areas → fix round → close-out). Five sprints of
evidence: the freeze gate catches a defect every sprint; the pre-registered
Opus focus has caught the HIGH three sprints running.

P3 debts owed by design (all pinned in ASSUMPTIONS 58-97 — read the entries
before designing):
- review module: emits ReviewCompleted (kind="thesis_review" AND
  kind="void_signoff") — the exact payload shape void() gates on is pinned by
  tests/unit/thesis/test_void_verb.py.
- broker pipeline: FillRecorded TYPED payload + fill-time pnl attribution
  (replaces P2's grade-time convention); ThesisActivated emission on fill;
  TradeRecord real fill prices (replaces the numeraire-100 reconstruction).
- live-tier context wiring: _context.assemble currently fails closed (R-002/
  R-011 deny live) — wire promotion_state's tier + live_sequence_remaining.
- SeriesClosed event (projection completeness is log-relative until then);
  ledger.models read accessors (tk grade sweep auto-discovery);
  strategy-tag registry (re-derive _scanner._TAG_STRATEGY/_regime._STRATEGY_TAGS,
  ASSUMPTIONS 57f); out-of-band reconciliation + auto-halt (§15 rows flagged
  in ASSUMPTIONS 93); yfinance macro's first production consumer.
- Two-phase pipeline (§8.2): ActionProposed → policy.evaluate → VerdictIssued
  → broker takes a VERDICT TOKEN — the broker adapter must be unreachable
  without one (TD-19's structural non-bypassability).
- PaperBroker (TD-7): OUR multi-account simulator — named accounts, mid±spread
  +fees fills via tradekit.costs, deterministic replay. Mike says Alpaca
  allows multiple paper accounts (contradicts the P1A trap note) — re-verify,
  but TD-7 stands regardless. Keep policy rule-sets pluggable per account
  (Mike's prop-firm horizon, see memory).
- Kraken + Alpaca keys in .env were chat-pasted: Mike ROTATES BOTH before any
  live use (his commitment; remind at P3 close).
- Codex tag-team: docs/handoff/CODEX-HANDOFF-2026-07-17.md is the shift
  pattern + docs/research/codex-brief.md the management brief. If Mike runs a
  Codex shift, FIRST action next session = full gate + Opus review over their
  diff vs the anchor before building on it.
- Milestone-end Mike primer duty (P3 topics: what a broker port is, why paper
  fills are simulated pessimistically, what reconciliation catches) + M365
  Copilot infographic prompts; universe per mike-vision-answers memory.
- End of session: SESSION-SEED-P4.md + plain-English report (what got built,
  what the reviewer caught, what you need from Mike — P4 will need Alpaca
  LIVE keys + $50-100 funding + both key rotations).
