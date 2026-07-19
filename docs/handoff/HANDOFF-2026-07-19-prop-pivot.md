# HANDOFF — 2026-07-19 — Kraken Prop pivot + SPRINT-P5-PROP seed

## TL;DR

The project pivoted to a live Kraken Prop evaluation account (Starter
Eval 1: $5,000, MDL $150/day, MDD $300 lifetime, target $500) and the
API hunt concluded **negative** — Prop has no programmatic surface, so
execution is advisory-HUD/execution-bridge with Mike (or Codex, his
call) as executor. SPRINT-P5-PROP is fully designed and is the next
work: prop barrier Monte Carlo + the bar-based backtest engine, both
pure-internal and unblocked. Suite is green at 758 tests
(19127d3 baseline; note 824→758 was a deliberate garbage-test purge,
not a regression). Nothing is red; nothing was left half-committed.

## State ladder

main branch, all pushed except final commits of this session (push
pending — Mike's remote is github.com/mmunro3318/tradekit):

- `5d3fd9c` — SPRINT-P5-PROP design doc + ROADMAP P5-PROP section + dev-log
- `0e65140` — scripts/smoke_kraken_probe.py (read-only Prop visibility probe; finding: negative)
- `b267d76` — docs/research/kraken-prop-report1-2026-07-19.md (Mike's deep-research GO verdict)
- `5dedbe3` — docs/research/prop-questionnaire-answers-CTO-2026-07-18.md (BINDING design calls, 378 answers) + dev-log
- `19127d3` — test-audit garbage removal (824→758) + tk-stack wiring [prior session]
- `ad69703` — P4-paper close-out [prior session]

Key docs a fresh agent must read, in order:
1. docs/handoff/SPRINT-P5-PROP.md — THE work plan (M5.1/M5.2 batches, pins, open ASSUMPTIONS flags)
2. docs/research/prop-questionnaire-answers-CTO-2026-07-18.md — binding design decisions (cited Q.<sec>.<n>)
3. docs/research/kraken-prop-report1-2026-07-19.md — venue mechanics (MDL/MDD math §6, fees §8)
4. docs/ROADMAP.md §P5-PROP — milestone checklist

## Narrative of work

All work this session was **inline by Fable (CTO)** — no subagents
dispatched (design/research session, not an implementation sprint).

1. Answered GPT 5.6 Sol's 378-question prop discovery sheet
   (5dedbe3). GPT adopted every call including the inserted "tradekit
   Substrate Contract" doc. Key binding calls: survival-first priority,
   pullback-continuation+breakout first family, 4h/1h/15m MTF,
   LLM deny-only + P&L-blinded, risk ladder 0.05→0.10→0.15%,
   no manual trades in the system account.
2. Mike's deep research returned Report 1: **GO with conditions**
   (b267d76). Automation explicitly permitted; MDL = 3% of BALANCE
   snapshot at 00:30 UTC, breach on real-time EQUITY; MDD static.
3. API hunt, probe-driven (0e65140): Pro live key (in .env as
   KRAKEN_LIVE_API_KEY/SECRET, withdrawal-disabled) sees main wallet
   only; Derivatives API rejects it; zero PROP pairs in public
   spot/futures APIs; docs.kraken.com/llms.txt has no Prop surface;
   Prop-context settings page has no API section (Mike verified in
   UI). Support ticket submitted (Mike) asking: (a) any programmatic
   Prop access, (b) do stops persist server-side through disconnect.
   (b) is the AUTONOMOUS_LIVE gate.
4. Kraken Desktop recon via computer-use (read tier — screenshots
   only): Prop board exists with "XXX PROP" instrument suite
   (BTC/ETH/NEAR/LINK/AVAX/... PROP), order ticket routes via
   "Accounts: Starter Eval 1" selector, panel confirms
   5000/150/300/500 numbers, ETH spot-vs-PROP basis ~2bps observed.
5. Authored SPRINT-P5-PROP (5d3fd9c) + ROADMAP P5-PROP milestones +
   memory update.

## Open issues — prioritized

1. **SPRINT-P5-PROP batch A not started (prop dials + barrier sim)**
   - First try: follow docs/handoff/SPRINT-P5-PROP.md §1 exactly — pin
     breach-semantics tests first (MDL boundary-equality, balance-vs-
     equity snapshot worked example from report §6)
   - Real fix: n/a — this is the planned work, four-stage TDD, batch A
     is money-path (policy/) → review round before green commit
   - Blocks shipping: yes (everything downstream consumes it)
2. **Final commits not pushed to GitHub remote**
   - First try: `git push` (Mike's creds may be needed)
   - Real fix: Mike pushes by hand (established pattern)
   - Blocks shipping: no
3. **Kraken support ticket unanswered (API access + stop persistence)**
   - First try: Mike checks ticket; log answer verbatim into
     docs/research/ and update SPRINT-P5-PROP §M5.3 blocked-external
   - Real fix: if "no API forever" → BridgeBroker is permanent; if
     stops don't persist → AUTONOMOUS_LIVE permanently off on this venue
   - Blocks shipping: no for M5.1/M5.2; yes for M5.3 autonomy posture
4. **Historical Kraken OHLC data not acquired (M5.2 batch D dependency)**
   - First try: Kraken's downloadable historical CSVs
     (support.kraken.com "Downloadable historical OHLCVT data") —
     scripted or Mike's hands
   - Real fix: rebuild bars from Kraken Trades API pagination (slow but
     complete)
   - Blocks shipping: only batch D (batches A–C run on synthetic bars)
5. **Chat-pasted key rotations still owed (Kraken read-only, Alpaca paper)**
   - First try: Mike rotates in venue UIs, updates .env
   - Real fix: n/a
   - Blocks shipping: no (paper/live unaffected; hygiene debt)

## Primer — how to use this

```powershell
cd C:\Users\admin\dev\tradekit
python "C:/Users/admin/.claude/skills/tk-gate/scripts/gate.py"   # canonical gate; expect GATE: green, 758 passed
uv run pytest -q                                                  # tests only
uv run python scripts/smoke_kraken_probe.py                       # re-probe Prop visibility (read-only, safe)
```

Session start: run tk-bootstrap (hook usually prints orientation).
Sprint execution: read SPRINT-P5-PROP.md, then follow the standing
four-stage cycle (pin→red→green→gate→review→fix) with `(red)` commits.
Never commit green without pasting verbatim `GATE: green` output.

## Conventions and gotchas

- **Compute economy**:
  - Opus/top: judgment calls, cross-doc consistency, architecture decisions, reviews
  - Sonnet: well-specified algorithms, test-driven implementation against pinned tests
  - Haiku/scripts: mechanical work — scrapes, renames, formatting, git mechanics
- **Money-path rule**: policy/ and broker/ changes require a review
  round BEFORE commit. M5.1's dial work is money-path.
- **Claude cannot execute trades — ever.** Harness tiers trading apps
  read-only AND policy prohibits it regardless. Executor = Mike or
  Codex (Mike's authority). Design everything executor-agnostic
  (BridgeBroker contract in SPRINT-P5-PROP §next-steps).
- **No secrets in chat**: any key pasted into any chat gets rotated.
  .env only; withdrawal-disabled keys.
- **Determinism seams**: monkeypatch only `mae._runtime.get_closed_bars`
  / `_clock`; every file-writer gets a path seam; seeded RNG only in
  the simulator (no Date.now-style ambient time anywhere).
- **Anti-permissive default**: every ambiguity resolves against the
  trade; boundary equality = breach; unknown outcomes fail closed.
- **Test count context**: 824→758 was the ratified garbage-test purge
  (docs/reviews/test-audit-2026-07-18.md) — do not "restore" them.
- **ASSUMPTIONS discipline**: SPRINT-P5-PROP lists 4 open flags
  (zero-edge envelope, 2bps basis placeholder, entry-fill price
  convention, serial-correlation dial). Flag→ratify, never improvise.
- **Kraken public OHLC returns only last 720 candles** per timeframe —
  history needs the CSV downloads (open issue 4).

## Backlog

- [ ] M5.1 prop dials + barrier simulator (batch A; money-path review)
- [ ] M5.2 backtest engine batches B–D (StrategySpec, walk-forward, experiment registry, Kraken data)
- [ ] M5.3 BridgeBroker + advisory HUD (after M5.1/M5.2)
- [ ] tradekit Substrate Contract doc for GPT design sequence (CTO)
- [ ] M5.4 Strategy #1 design (pullback-continuation family)
- [ ] Start tick/trade collector (Parquet sink, 2y rolling)
- [ ] Kraken support ticket follow-up (API; stop persistence)
- [ ] Mike: rotate chat-pasted keys (Kraken read-only, Alpaca paper)
- [ ] Mike: remaining MIKE questionnaire items (hours/timezone, alert channels, budgets, eval-fee cap)
- [ ] Mike: Report 2 (intraday microstructure) → CostModel parameters
- [ ] git push of 5dedbe3..5d3fd9c
- [x] Prop questionnaire answered (378) — 5dedbe3
- [x] Report 1 GO verdict archived — b267d76
- [x] Prop API hunt concluded (negative) — 0e65140
- [x] SPRINT-P5-PROP designed + ROADMAP updated — 5d3fd9c

## Sources

- [SPRINT-P5-PROP.md](computer://C%3A%5CUsers%5Cadmin%5Cdev%5Ctradekit%5Cdocs%5Chandoff%5CSPRINT-P5-PROP.md)
- [prop-questionnaire-answers-CTO-2026-07-18.md](computer://C%3A%5CUsers%5Cadmin%5Cdev%5Ctradekit%5Cdocs%5Cresearch%5Cprop-questionnaire-answers-CTO-2026-07-18.md)
- [kraken-prop-report1-2026-07-19.md](computer://C%3A%5CUsers%5Cadmin%5Cdev%5Ctradekit%5Cdocs%5Cresearch%5Ckraken-prop-report1-2026-07-19.md)
- [ROADMAP.md](computer://C%3A%5CUsers%5Cadmin%5Cdev%5Ctradekit%5Cdocs%5CROADMAP.md)
- [smoke_kraken_probe.py](computer://C%3A%5CUsers%5Cadmin%5Cdev%5Ctradekit%5Cscripts%5Csmoke_kraken_probe.py)
- [cc-dev-log.md](computer://C%3A%5CUsers%5Cadmin%5Cdev%5Ctradekit%5Ccc-dev-log.md)
- [test-audit-2026-07-18.md](computer://C%3A%5CUsers%5Cadmin%5Cdev%5Ctradekit%5Cdocs%5Creviews%5Ctest-audit-2026-07-18.md)
