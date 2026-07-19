# cc-dev-log

Chronological dev log. Newest entry first. One entry per working session; keep entries terse — decisions and deltas, not narration.

## 2026-07-19 (Fable, day 3) — hud-orderbook shipped T1-T4 (design a85053c -> green fa0d3e4)

- **Pivot executed**: post-UIA-grade-C, built the advisory HUD per handoff.
  Design/spec/tasks committed (static HTML render target chosen over
  FastAPI/Textual); AC-1..10; T1-T5.
- **Batch 1 (contracts + render + build_state)**: red 2525531, green e9805da,
  CTO fix round d9ef3f8 REJECTED implementer's NotImplementedError-as-success
  sentinel + hardcoded proposal fixture (fabricated advisory numbers = money
  hazard) -> real BarSeries fixtures, third sanctioned seam size_qty with
  LOUD default (ASSUMPTIONS 158). Review round 10 ACCEPT w/ fixes (be70f94):
  tab-count assertion, exception-path test, interim-provenance warning on
  tickets, gate-reason fidelity.
- **Batch 2 (tk hud CLI)**: red 8c6ef7d, green fa0d3e4. Implementer correctly
  STOPPED on pytest basename collision (test_cli.py x2) instead of hacking
  import mode; CTO renamed to test_hud_cli.py. Atomic temp+replace write,
  exit 4, clock via mae._runtime only.
- **Known intended limitation**: production `tk hud` fails loud until T5
  (real sizing/funnel wiring) — no fabricated quantities on the surface Mike
  transcribes into the prop account. T5 is next session's first batch, then
  the one compliant inactivity-clock trade.
- Gate green at a4e2d6d (890+ tests). Collector confirmed live (hour-14
  parquet growing).

## 2026-07-19 (Fable, night 2) — P5-PROP batch A shipped (red 4343b0b -> green 1c4cb14)

- **ASSUMPTIONS round-26 (143-153)**: all four sprint-flagged ambiguities
  ratified + red/review pins: balance-snapshot MDL, equality=breach
  anti-permissive (documented asymmetry vs R-017/R-018 allow-at-boundary),
  static MDD, funding at 4h UTC marks exclusive-both-ends, cent
  HALF_EVEN per application, independent parametric draws, zero-edge
  log-space envelope 0.3936, risk ladder + monthly ruin normalization,
  scripted-granularity limitation, 2bps basis placeholder, horizon
  guard, exclusive 00:30 boundary.
- **Shipped**: contracts._prop (spec/result/trade-model union),
  prop.simulate_evaluation (scripted Decimal ledger + parametric numpy
  MC), policy prop dial block + prop_account_walls (0.021/0.036).
  35 new tests incl. cent-exact goldens (CTO re-derived independently:
  5036.80/5035.84/4974.46 confirmed pre-freeze). 793 green.
- **Review round (money-path, pre-registered focus boundary/reset)**:
  FIX-FIRST — 2 MED (horizon-span leak -> ValueError; 00:30-equality
  docstring/impl mismatch -> pinned exclusive + golden), 4 LOW (floors
  now compared unquantized; tie->mdl pinned; fee-kernel lift deferred
  to batch B; walls hygiene fixed). Grades: implementer A-, test suite A-.
- **Friction x2**: commit_gate.py lacked the (red) exemption (fixed);
  read-dedupe hook false-positives on subagent first-reads (NOT SOLVED).
- Open into batch B: R-017/R-018 PolicyContext wiring for prop:*
  accounts; EmpiricalTradeModel pin; fee kernel -> CostModel single canon.

## 2026-07-19 (Fable, late) — Prop recon complete; SPRINT-P5-PROP designed

- **Prop API hunt CLOSED (negative)**: Pro key sees main wallet only;
  Prop settings page has no API section (Mike-confirmed in UI); zero
  PROP pairs in public spot/futures APIs; docs/llms.txt has no Prop
  surface. Support ticket pending (API access + stop persistence).
- **Kraken Desktop recon (computer-use, read tier)**: Prop board =
  separate "XXX PROP" instrument suite (BTC/ETH/NEAR/LINK/... PROP),
  order ticket routes via Accounts selector ("Starter Eval 1");
  panel confirms $5,000 / MDL $150 / MDD $300 / target $500; ETH
  spot-vs-PROP basis ~2bps observed. Claude = read-only observer
  (harness tier + policy: never executes trades); executor = Mike or
  Codex via future execution bridge.
- **SPRINT-P5-PROP authored** (docs/handoff/SPRINT-P5-PROP.md): M5.1
  prop dials + barrier Monte Carlo (headline: recommended_max_risk_frac);
  M5.2 backtest/walk-forward engine (absorbs M1.3 box; StrategySpec in
  scanner vocabulary, experiment registry starts, Kraken data ingest);
  M5.3 execution bridge/HUD; M5.4 strategy #1. ROADMAP P5-PROP section
  added; memory updated. Open flags listed in sprint doc §ASSUMPTIONS.

## 2026-07-19 (Fable) — Prop-strategy questionnaire answered (CTO), Kraken GO verdict

- **Answered GPT 5.6 Sol's 378-question prop-strategy discovery sheet**:
  docs/research/prop-questionnaire-answers-CTO-2026-07-18.md. Anchors GPT
  to the built substrate (BUILT markers), flags MIKE-only items, defers
  venue facts to Report 1. Key calls: survival-first priority order,
  pullback-continuation+breakout first family, 4h/1h/15m MTF, LLM
  deny-only + P&L-blinded, risk ladder 0.05→0.10→0.15%, no manual trades
  in system account, "tradekit Substrate Contract" doc inserted into the
  design sequence (GPT adopted all of it).
- **Kraken Prop Report 1 verdict: GO with conditions** (Mike's deep
  research): automation explicitly permitted, WA/US eligible, MDL = 3% of
  BALANCE recalc'd daily 00:30 UTC, MDD static lifetime off starting
  balance, breach detection on real-time EQUITY. Unconfirmed →
  SUPERVISED_LIVE-gated: Prop API key scoping, stop persistence through
  disconnect, full Prop ToS text. Contingency if no API: advisory-HUD
  mode (Mike executes, app simulates from synced fills).
- Gate: green (19127d3 baseline, 758 passed).

## 2026-07-19 (Fable) — Test audit + garbage removal; tk-stack Phase 1 wiring

- **Test-quality audit** (6-agent rubric sweep, all 683 fns): Mike's garbage-test
  suspicion largely REFUTED — ~85-90% protective, zero mock-theater. Report:
  docs/reviews/test-audit-2026-07-18.md (verdict + gap backlog, gaps > garbage).
- **Garbage removal executed** (sonnet agent, CTO re-gated): 824→758 collected (−66,
  mostly pydantic-mechanics sweeps → one inheritance pin each). pnl_snapshot
  tautology rewritten to a real lifecycle test (exposed that projections are
  rebuild-derived, not append-applied). broker_port conformance now seeds real
  fills/positions; ManualBroker exemption documented (AdvisoryOnly by design).
  No src/ changes. Gate: green (758 passed, ruff clean, mypy clean).
- **tk-stack Phase 1 live**: tk-gate (canonical gate verdict + .tk/gate-last.json),
  tk-bootstrap (SessionStart hook: seed/dev-log/roadmap/gate-freshness/recovery
  classification), tk-friction (docs/FRICTION.md logger). Project CLAUDE.md (gate
  line, red lines, doc inventory) + AGENTS.md (Codex/Gemini) added. Global skills
  purge: 57 gstack skills archived, gstack.bak deleted; tk- suite design at
  ~/.claude/tk-stack/DESIGN.md.
- Exemplar subagent prompts + TDD examples library harvested to
  ~/.claude/tk-stack/references/ (feeds future tk-tdd/tk-implement).

## 2026-07-18 (Fable) — P4-PAPER COMPLETE: AlpacaBroker dress rehearsal + seam hardening

- Scope per Mike: "P4, paper only." Live remains structurally unreachable
  behind FOUR independent locks: live_trading_enabled dial (default false) +
  ALPACA_LIVE_KEY env absence + two-man promotion + live_path manual-resume.
- **AlpacaBroker** (real trading API, paper base): five port methods, shared
  _tokens verifier FIRST (submit-time halt seam closed for every adapter),
  no-creds = LOUD everywhere (fabricated read-verb defaults REJECTED at the
  CTO gate — the conformance harness owns its environmental setup instead),
  venue error taxonomy (404-on-order_status is the one typed venue answer;
  5xx/429/timeout/malformed RAISE VenueUnavailable — never fabricate a
  status; landed same-day off review round 7's MED, pre-live).
- **Process upgrade (Mike's note): fixtures from REALITY FIRST** — CTO
  probed the live paper API before any test authoring (docs/research/
  alpaca-paper-shapes-2026-07-18.json); zero fixture-vs-reality divergences
  all sprint (first sprint with none). Two ~$10 BTC probe/rehearsal
  positions remain in Mike's Alpaca paper account.
- **Live dress rehearsal PASSED via the real adapter**: submit→open→filled→
  activity-fill (costs-model fees)→account state, scripts/smoke_alpaca_paper.py.
- **Seam hardening**: HaltSetPayload.live_path (narrow reading — agent's
  argument beat the CTO's initial lean; procedural pin covers the residual),
  resume(confirm_live)/`tk policy resume --live-confirm`, Popen streaming
  flood-kill (proven early, not timeout), ring-3 seam scenarios (submit-time
  halt + token×demotion new-green against batch-A machinery).
- Orchestration per Mike's note: every dispatch backgrounded + wakeup
  ladder; no blocking waits; Codex fallback doc refreshed evergreen
  (CODEX-HANDOFF-CURRENT.md).
- **Review round 7 (Opus): PASS** (probes incl. secret-scan of the tracked
  tree — zero hits; flood-kill timed; mutation-reasoning on scenarios). The
  MED (HTTP taxonomy) fixed same-day with per-failure-mode proven reds.
- **Final: 824 tests green, ruff clean, mypy clean.** agent-metrics round 7.
- P4-LIVE remains Mike-gated: rotate BOTH chat-pasted key pairs, create live
  keys + fund $50-100, approve prompts/rubric-thesis-v1.md. SESSION-SEED-P4
  updated (rehearsal marked done; procedural no-agent-resume pin).

## 2026-07-17/18 (Fable) — P3 paper trading/review/reporting COMPLETE (M3.1-M3.3*)

- *Open deferrals, all Mike-paired or Mike-blocked: rubric-thesis-v1.md DRAFT
  awaits his approval; research-loop prompts (D14) = paired session; Kraken
  read-only balance tracking = his key rotation; $5k/$5k seed distribution =
  his long-term thesis content; derivatives provider stays deprioritized.
- **P2 rules sign-off closed first**: Mike confirmed with amendments → TD-24
  (per-account dial layering: percent-of-principal position/exposure dials,
  AccountConfig contract with prop-style slots, None=disabled; R-008 min
  notional stays absolute — fee-floor exception he accepted).
- **The full paper pipeline is live**: BrokerPort + conformance suite;
  PaperBroker (event-sourced accounts, deterministic mid±spread fills with
  quote snapshots, G5 through-by-tick limits, REAL ledger token verification
  with thesis binding + no-newer-deny); execute_order two-phase pipeline
  (§8.2 ordering guarantee: intent → verdict → broker, deny leaves zero
  Order* events); reconcile BOTH directions → auto-HaltSet; review module
  (LLMReviewerPort, subprocess adapters with caps, deterministic rubric,
  zero-token auto-fail short-circuits, void_signoff emission closing the P2
  debt); ManualBroker/advisory + tk fill record (never refuses, ledgers
  GateViolationDetected under lockouts — F7's teeth); memory (brief with
  hard token cap + salience truncation, search AND/phrase, wiki, lessons);
  report (memo/readiness/pnl); ledger.models accessors; SeriesClosed
  emission; strategy-tag registry (57f debt closed). TD-24 landed:
  create-paper-account, R-017/R-018 with not_configured audit hits,
  evaluate hardened to an outcome ALLOWLIST (unknown values fail closed).
- **Done-gate green**: tests/replay/test_p3_end_to_end.py — scan → thesis →
  review (fake adapter) → gates → order → paper fill → grade PASS with pnl →
  memo/brief → byte-identical projection rebuild → chain verify.
- **In-sprint catches**: dev-p3-d found a LATENT P2 bug (void() never checked
  `passed` on sign-offs — a FAILED review would have permitted a void);
  delayed-fuse macro tests (fixed dates + real clock) — new standing rule;
  report-path litter; token-verification pull-forward when the conformance
  suite proved the shape-only seam wrong. live:→PaperBroker routing is
  EXPLICITLY TEMPORARY (P4 replaces + pins).
- **Review round 6 (Opus): FIX-FIRST, zero HIGH (streak broken), 3 MED**:
  halt-bypass via resting-limit polling (order_status now halt-gated);
  token gate narrower than its pin (thesis binding + no-newer-deny landed);
  one-directional reconcile (phantom-ledger-fill direction added). Fixes
  3f207d9→425f000. agent-metrics round 6.
- **Final: 781 tests green, ruff clean, mypy clean (71 src files).**
- Next: P4 (live proof — every step pairs with Mike; needs BOTH key
  rotations + Alpaca live keys + $50-100). Seed: SESSION-SEED-P4.md.

## 2026-07-17 (Fable) — P2 thesis lifecycle + policy engine COMPLETE (M2.1, M2.2)*

- *One open DoD item: **Mike's sign-off on rules/RULES.md WHYs + config.toml dials**
  — requested, pending his reply. Everything else done.
- **The spine and the gates are live.** tradekit.thesis: draft/submit/approve/
  reject/grade/void, event-sourced, guarded (state,event)→state transitions,
  submit = validate-everything-then-append (snapshot → sizing → marker), EV
  Decimal tolerance $0.01, quantized predicate resolution. tradekit.policy:
  R-001..R-016 declarative registry + WHYs, pure byte-identical evaluate with
  deny-never-silent ledgering, dials via pydantic-settings config.toml,
  policy-version hashing, halt/resume, series accounting (per-account, 30-day
  calendar blocks), T1→T2 promotion machine with two-man confirm + demotion,
  R-016 wired to real compute_strategy_metrics. rules/RULES.md generated.
  13+ typed event payload models; theses/series/promotion_state/pnl_daily
  projections, rebuild-idempotent and log-pure.
- **Five batches, four-stage each** (addendum 23c3897): A lifecycle (0ae41bb→
  8159b2c), B grade/void (598e439→c434362), C policy (b8e0d5e→7f4c241), D
  series/promotion (101288d→f6c147b), E adversarial suite (acf478c). ~30
  flagged design calls adjudicated in ASSUMPTIONS 58-97 (highlights: pnl None
  never fabricated-zero; void sign-off = ReviewCompleted kind=void_signoff;
  read-verb-that-writes for promotion_status; edge_verdict positive-only).
- **In-sprint CTO catches**: batch-A's unguarded transition map (any stray
  ReviewCompleted could corrupt state — found by batch-B TDD, fixed batch B);
  batch-C dev's permissive fallback that let FABRICATED thesis_ids pass
  R-010/R-012 (rejected; fixture made to earn its allow; two deny pins).
- **Done-gate: 11 adversarial replay scenarios (Opus-authored), all §15 gates
  held** — VOID-farm, micro-series, cherry-pick, revenge-size, drawdown incl.
  advisory, kill switch, fabricated-id, refused-void, tamper evidence.
- **Review round (Opus, FIX-FIRST)**: HIGH — series MDD equity base pooled ALL
  accounts (winning sibling dilutes a loser's drawdown → dirty series grades
  clean → promotion opens); both derivations shared the bug so their agreement
  pin passed. Fixed with a discriminating two-account fixture (0.0788 falsely
  clean → 0.1733 dirty). MED: projection completeness now log-relative (max
  event ts, pure rebuild). 2 LOW. Fixes be4a8a8→5b547be. agent-metrics #5.
- Codex tag-team scaffolding landed mid-sprint (docs/handoff/CODEX-HANDOFF-
  2026-07-17.md + docs/research/codex-brief.md, anchor then 101288d) — unused
  this shift (Mike upgraded the plan; Fable finished the sprint), stays as the
  off-hours fallback pattern.
- **Final: 594 tests green, ruff clean, mypy clean.**
- Next: SPRINT-P3 (broker/paper trading/review/reporting). P3 owes: review
  module emits ReviewCompleted incl. void_signoff; FillRecorded typed payload
  + fill-time pnl attribution; live-tier context wiring (fail-closed till
  then); SeriesClosed event; ledger.models read accessors; strategy-tag
  registry re-derivation (ASSUMPTIONS 57f).

## 2026-07-16/17 (Fable) — P1C regime/scanner/sizing/correlation COMPLETE (M1.4, M1.5, P1 done)

- **All four remaining MAE verbs live**: size_position (wired over frozen _sizing),
  get_correlation_matrix, get_regime (HMM + EWMA override + rules fallback),
  scan_markets. Plus story 0 (Mike-approved): yfinance macro provider (never-raise
  degradation, ASSUMPTIONS 46) — closes M1.1's last box. Deps: yfinance 1.5.1,
  pandas 3.0.3, hmmlearn 0.3.3, scipy 1.18.0 — all mae/-internal.
- **The sprint's one new design**: `mae/_runtime.py` ambient data seam (verb
  signatures are pinned portless) — clock/provider-factory/cache-path indirections,
  "/" routing (Kraken vs Alpaca), and THE lookahead chokepoint: get_closed_bars
  strips the live bar so no verb can ever leak an unclosed candle downstream.
- **Three batches, four-stage each** (addendum 6e8b8a9): A = macro+runtime+sizing+
  correlation (030a520→faaa151); B = regime (a41f352→3974493); C = scanner+
  get_closed_bars+smoke (a9ea52d→5711bac). Schema ambiguities escalated by TDD
  agents and CTO-ratified in ASSUMPTIONS 47/51-54/57 (incl. "neutral" as a
  rules-only fourth regime state = anti-permissive default).
- **CTO-gate catches (pre-review)**: batch-A runtime test wrote fixture bars through
  the REAL data/cache.db (closed bars never invalidate → poisoned real scans; six
  fake rows purged, _cache_path seam added — standing rule: every file-writer gets
  a path seam); live smoke_scan crashed on Kraken pair-map gaps → Mike's universe
  (SOL/LINK/NEAR/TAO/EIGEN) mapped, result keys verified against the live endpoint.
- **Review round (Opus, verdict FIX-FIRST — the pre-registered override gate paid
  off)**: HIGH — EWMA override used the POOLED vol mean instead of the calmest
  state's emission mean (threshold ~4.8x inflated → under-fires exactly when vol
  explodes); invisible to the 0.25-spike test which cleared either threshold; fixed
  with a discriminating marginal-spike test (fails on pooled, passes on emission
  mean, proved both directions). MED: 3 uncovered scanner filter branches (now 7 new
  pinning tests). LOWs: macro degraded-path could still raise; monitor-less HMM
  defaulted to converged. Fixes e988c01→b4885a1. Round details agent-metrics #4.
- Composio spike (D17): verdict NO for data/broker core, MAYBE for P3+ reporting
  side-channels — docs/research/composio-spike.md.
- Alpaca PAPER keys landed in .env (account PA3YTZDZ9SXE, verified vs live data API,
  IEX feed). Two dev agents died at usage caps mid-task; both recovered cleanly
  (work was already on disk — check git status + pytest before assuming loss).
- **Final: 338 tests green, ruff clean, mypy clean. P1 (MAE core) COMPLETE.**
  Live: smoke_scan returns 3 real matches (ETH/SOL/LINK dailies via Kraken).
- Next: SPRINT-P2 (thesis lifecycle + policy engine). Note for P2: walk-forward
  evaluator (M1.3 leftover) lands with the backtest engine; strategy-tag registry
  should re-derive _scanner._TAG_STRATEGY/_regime._STRATEGY_TAGS (ASSUMPTIONS 57f).

## 2026-07-15 (Fable) — P1B indicators + golden vectors COMPLETE (M1.2)

- **17 indicators** in `mae/_indicators/{volatility,momentum,trend,volume,structure}.py`,
  pure functions, uniform None-alignment contract, signatures/lookbacks pinned by a
  CTO addendum in the sprint doc (31efe59) BEFORE dispatch. numpy added (stays in mae/).
- **Golden-vector freeze gate (the sprint's point, new process):** TDD agents derived
  vectors via independent from-spec scripts (pandas_ta rejected — its adjust=False
  seeding contradicts the pinned SMA-seed Wilder/EMA convention); CTO then verified
  every value with a SECOND independent implementation + TA-Lib 0.7.0 external
  cross-check (throwaway venv) before committing red. Exact TA-Lib matches: sma, ema,
  rsi, roc, bollinger, TR[1:], macd-line-via-EMAs, obv (modulo pinned obv[0]=0), DI/ADX
  divergences hand-reproduced as TA-Lib's 1..13-seed quirk. ASSUMPTIONS 39-43; vectors
  now FROZEN (regeneration requires redoing the gate).
- **Four-stage workflow, two batches:** tdd-p1b → dev-p1b (stories 1-3, c5e101a →
  08fcf70); tdd-p1b-2 → dev-p1b-2 (stories 4-5, 08cc8f7 → 61fb78a). All Sonnet.
  One dev defect, caught by the frozen goldens pre-commit: ADX Wilder smoother seeded
  with the SUM under the average-form recurrence (invisible at seed index — ratio of
  sums == ratio of averages — divergent after); dev-p1b initially blamed the golden,
  STOPped correctly, fixed on CTO push-back with exact arithmetic. Commandment 4's
  record intact. (Agent also died at a usage cap mid-fix; fix had already landed.)
- **Review round (Opus): verdict PASS — first zero-HIGH round in three sprints.**
  Reviewer independently recomputed 11 indicators against the goldens. 3 LOW fixed
  same-day (e519719): QFL gloss, degenerate-param guards (period<1/k<1 now ValueError),
  close-out items. Details in docs/reviews/agent-metrics.md round 3.
- CVD deferred to P3 (tick trades); CTO pins of record: supertrend initial direction
  (ASSUMPTIONS 41), ADX seed window (40), vwap UTC-day anchor + qfl same-bar crack (43).
- **Final: 258 tests green, ruff clean, mypy clean.** ROADMAP M1.2 all boxes checked.
- Next: SPRINT-P1C (regime/scanner/sizing — needs hmmlearn + the deferred yfinance
  macro provider decision). Mike's hands: still only the optional Alpaca paper keys.

## 2026-07-14/15 (Fable) — P1A data layer COMPLETE (stories 3-8 + review round)

- Keys landed: CoinGecko demo + Kraken read-only in `.env` (gitignored; CoinGecko
  verified live). Kraken key was pasted in chat — consider rotating before P3 live use.
- **Four-stage workflow, two rounds**: tdd-p1a (Sonnet) → dev-p1a (Sonnet) for stories
  3-5 (cache/Kraken/ratelimit, commits 7643c29→70121e9); tdd-p1a-2 → dev-p1a-2 (both
  Sonnet) for 6-8 (Alpaca/CoinGecko/conformance + live smoke, d051db2→e85e083).
- **Review round (Opus, verdict FIX-FIRST — third round running with HIGH catches):**
  H1 Alpaca crypto endpoint is multi-symbol (`bars` keyed by symbol) — flat-list mock
  hid a live-API crash; H2 ratelimit module was an orphan (nothing called it); M3 4xx
  mistyped as ProviderUnavailable; M4 malformed-200 bodies raised untyped; M5 cache was
  write-only whenever a live bar was in range (i.e. always, in production). Fix agent
  (Sonnet, fix-p1a; survived a usage-cap interruption mid-task and was resumed from
  transcript) landed red 48c5bdd → green 3fae4c9. ASSUMPTIONS 27-38 added across rounds.
- Ratelimit now wired: providers take injected clock/sleeper, token bucket + retry on
  every call; 4xx never retries; timeouts retry. Cache serves cached closed prefix and
  fetches only the uncovered suffix. Smoke re-run live post-wiring: 720x 1h BTC bars OK.
- **Final: 178 tests green, ruff clean, mypy clean.** M1.1 boxes checked except
  yfinance macro provider (deferred per sprint doc; revisit at P1C).
- Next: SPRINT-P1B indicators + golden vectors. Mike's hands: Alpaca PAPER keys
  (app.alpaca.markets) into .env as ALPACA_API_KEY_ID/ALPACA_API_SECRET when convenient
  (needed for Alpaca live smoke; tests don't need them).

## 2026-07-13 (Fable) — candlerl experiment: vision pattern classifier + PPO trader

- **New isolated sub-project `experiments/candlerl/`** (own uv env, py3.11, torch 2.11
  cu128 — RTX 5060 Ti/Blackwell works). Two decoupled models per the hierarchical
  master/slave plan Mike supplied: rendered 32-bar chart (128px) → CNN (11-pattern
  multi-label + 3-class 5-bar direction heads) → precomputed per-bar vision vectors +
  25 numeric indicators → SB3 PPO {flat,long,short}, reward = pos·logret − 10 bps·turnover.
- **Key finding (the expensive lesson)**: TA-Lib-style pattern labels are NOT learnable
  from images unless computed on **pixel-grid-quantized** prices — sub-pixel thresholds
  put identical-looking charts in different classes (macro-F1 0.34). After quantization +
  per-class val-calibrated thresholds: test macro-F1 0.46 — doji 0.87/engulfing 0.76-0.78
  strong, hammer family ~0.45 (relational judgments vs trailing averages), 3-candle stars
  weak (val support 9-47). Improvement paths in HANDOFF B8.
- **RL round 1 churned** (0.76 flips/bar → −38% cost drag, −21.6% mean vs +94.5% B&H on
  2024→2026 test). Round 2: training cost 25 bps (eval stays 10), ent_coef 0.001, γ 0.99.
- Rule-based detectors verified against TA-Lib C source (research agent); Stooq keyless
  daily data (22 tickers, 136.6k bars); leak-safe chrono splits with HORIZON embargo;
  43 tests green (TDD), review-agent pass fixed truncated-vs-terminated PPO bias + 6 more.
- CLI: fetch/build/train-vision/bridge/train-rl/evaluate/demo/predict (--ticker/--csv/
  --image). Paper suggestions only. README + HANDOFF.md (backlog B1–B9) for successors.

## 2026-07-12 (Fable bonus hour) — grading engine core, sizing math, cost model

- **Grading engine** (`thesis/_grading.evaluate_criteria`, P2 story-2 core, pre-built): pure arithmetic per DESIGN §10.2 with every ambiguity resolved against the agent — same-bar priority failure > invalidation > success (VOID can't erase a loss), stop-first on stop+target bars, lookahead guard inside the engine, per-predicate `by` deadlines never resurrect, time_expiry fires at deadline (an inverted-logic bug I caught pre-commit and pinned with a test). 12 tests. MVP constraint: one timeframe per thesis (ASSUMPTIONS 24).
- **Sizing math** (`mae/_sizing.py`, P1C story-1 core): Kelly with negative-edge clamp + ATR position identity (stopped out = lose exactly risk_usd). My own first golden vector was wrong by 3e-5 — re-derived by exact fractions (f* = .574 − 71/262); implementation was right. Canonical doc's 0.2102 example remains wrong.
- **Cost model** (`tradekit.costs`, P1A story-2): TD-8 shared friction tables (Alpaca equity/crypto, Kraken crypto), slippage-free under $100, unknown venues die loudly. Provisional until P4 live fills (ASSUMPTIONS 26).
- **Contracts**: Bar (OHLC-coherence validator), BarSeries (strict ascending), Friction, CriteriaOutcome, TIMEFRAME_SECONDS — P1A story-1 done. 28 schemas exported.
- ASSUMPTIONS 23–26 added (incl. the temporary internal-test exception — re-point + TID251-ban when verbs land). Sprint docs P1A/P1C/P2 updated with DONE markers. **Final: 108 tests green, ruff + mypy clean.**

## 2026-07-12 (final Fable session) — metrics core + full handoff package

- **Fairy-godmother handoff**: Fable 5 access ending; project handed to Opus/Sonnet/Haiku.
- Pulled M1.3 forward and completed it personally (the math most likely to be silently botched): `mae.compute_strategy_metrics` — pnl/win-rate/expectancy/PF, trade-level Sharpe+Sortino with pinned annualization convention (√(trades/yr) over log span), drawdown vs peak equity, Calmar, in-house Bailey–López de Prado PSR/DSR with n_trials selection penalty, G1 regime (DSR n≥30 / penalized 10–29 / descriptive <10), deterministic edge_verdict table. Conventions BINDING via `_metrics.py` docstring + 10 hand-derived golden-vector tests. `TradeRecord`/`StrategyMetrics` contracts added (24 schemas). **83 tests green, ruff+mypy clean.**
- Wrote **README.md** (setup, usage, current capability) and the **handoff package** in `docs/handoff/`: HANDOFF-PRIMER (ten working rules, model role assignments, state of world, known traps, session bootstrap checklist) + sprint docs P1A (data layer + costs), P1B (indicators + golden vectors), P1C (regime/scanner/sizing — incl. hand-derived Kelly vectors; canonical doc's example arithmetic is WRONG, ours is right), P2 (thesis/policy — Opus-required stories flagged), P3–P4 (paper→live).
- Remaining Mike's-hands: GitHub remote (URGENT — no offsite backup), CoinGecko key, Kraken read-only key (P3), Alpaca live keys (P4 only).
- Successor sessions start at HANDOFF-PRIMER §6 bootstrap checklist. Active sprint: **P1A**.

## 2026-07-12 (evening) — git init; ROADMAP; P0 COMPLETE (done-gate met)

- `git init` on main; baseline commit of doc set. `.gitignore` hardened (.env, data/, *.db never committable); `.gitattributes` normalizes line endings.
- **ROADMAP.md** written (P0–P5, milestone/story checkboxes, done-gates per phase).
- **P0 built via the four-stage workflow**: CTO pinned interfaces → TDD team (agent tdd-p0) wrote 38 failing tests + 19 ratified ASSUMPTIONS → dev team (dev-p0) implemented contracts + ledger to green → reviewer (reviewer-p0) verdict FIX-FIRST with 9 defects, all verified by execution.
- Notable review catches: **D1 quantize matched tick exponent, not grid** (0.05/0.5/5 ticks passed through un-quantized — falsified the G2 guarantee); D2 naive datetimes read as machine-local time in query bounds; D3 hash-preimage delimiter forgeable via control chars in identity fields; D5 the deep-module lint wasn't actually enforcing. All fixed by CTO same session; enforcement probe-verified. Agent metrics started at docs/reviews/agent-metrics.md (tdd-p0: B+, dev-p0: B).
- M0.4: `tk schema export` (22 schemas → docs/schemas/), `tk ledger verify|rebuild|query`, P0 replay done-gate test. **Final: 73 tests green, ruff clean, mypy clean (strict flags on contracts/ledger), real-CLI smoke `chain OK`.**
- ASSUMPTIONS.md now 22 items (20–22 added in fix round). Commits: 7f37184 → 7768e74 → d446ffb (red) → 5f93f15 (green) → c31cbf1 (fixes) → this.
- Next: P1 MAE core (data layer first — Kraken needs no key; CoinGecko demo key is Mike's remaining hands-item, plus creating the GitHub remote for first CI run).

## 2026-07-12 (later) — Adversarial review incorporated; DESIGN.md → v0.2

- Mike approved all v0.1 decisions incl. the three §18 asks (TD-10 promotion tightening, $25 live cap, advisory cooling-off). Confirmed rolling our own paper engine; futures *signals* deprioritized below stocks/crypto (we never trade futures — it's positioning data for spot theses); options = "maybe, later" → P5+ deferred list.
- Gemini adversarial review (Codex usage-capped) archived verbatim with dispositions at `docs/research/gemini-adversarial-review.md` (G1–G6).
- Accepted: G1 DSR gates only at n≥30/strategy, provisional penalized-Sharpe regime below (TD-14); G2 tick-size `quantize` at MAE boundary (new TD-23); G3 EWMA 3σ vol override on stale HMM (TD-13); G5 limit fills need trade-through ≥1 tick; G6 derivatives chain = Kraken Futures → Coinalyze → Binance, implementation → P3.
- **Partially rejected G4** (in-process write queue): wrong topology — tradekit is many short-lived CLI processes, not one threaded process. Kept: bounded retry-with-jitter on `append`; scouts write wiki files, not events. Escalation stays the Phase-2 daemon (TD-16).
- All three former Perplexity questions (Q1–Q3) resolved by the review; none open.
- Answered Gemini's closing question by specifying correlation methodology in DESIGN §9.1 (30d Pearson, daily log-returns, UTC inner-join, ≥20 overlap else `insufficient_overlap` → unmeasured ≠ pass).
- Next: ROADMAP.md, then P0 implementation. Repo still needs `git init` + GitHub remote (Mike's call to make now).

## 2026-07-12 — Pass B: DESIGN.md produced (Claude Code, Fable)

- Read all Pass-A inputs: SCOPE.md (D1–D17), Perplexity SME pass (F1–F7), canonical MAE doc.
- Wrote **docs/DESIGN.md** — full architecture doc: TD-1…TD-22 decision register, tech stack, 7 deep modules + 2 shared leaves + 2 thin shells, contracts (thesis contract + predicate DSL), event-sourced hash-chained ledger DDL, policy rules catalog R-001…R-016 with WHYs, promotion state machine (series hardened per SME F2/F3), two-phase order pipeline owned by `broker.execute_order`, own PaperBroker (TD-7), MAE port with derivatives-provider fallback chain, threat model, three-ring test strategy, build phasing P0–P5.
- Notable overrides of SCOPE (all flagged inline): promotion series locked to fixed 30-day blocks/≥10 trades/≥30 total (F2/F3); paper daily trade cap 20/day (anti-gaming); CoinMarketCap dropped.
- Key risk surfaced: **Binance fapi is US-geo-blocked (HTTP 451)** — canonical MAE's primary derivatives source; made derivatives a pluggable port, fallback question queued for Perplexity (DESIGN §18 Q1).
- Ran a cold-read consistency review via subagent: 20 defects found (2 HIGH), all fixed same-session.
- Next: Mike reviews DESIGN.md (§18 has 3 decisions for him + paste-ready Perplexity script) → adversarial review via Codex/gstack → ROADMAP.md → P0 implementation.

Blockers for Mike (from SCOPE §8, still open): CoinGecko demo key, Kraken read-only key, GitHub repo `tradekit` + `git init` (folder is not a git repo yet).
