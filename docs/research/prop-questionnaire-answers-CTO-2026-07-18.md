# Prop-strategy questionnaire — CTO answers (2026-07-18)

Answers to GPT 5.6 Sol's ~378-question discovery sheet for the Kraken-prop
strategy program. Answered by the tradekit CTO (Claude). Conventions:
**MIKE** = personal/product question only Mike can answer; **R1..R10** =
deferred to the corresponding Deep Research report; **BUILT** = tradekit
already implements this and the design must adopt it, not re-derive it.

## Framing note for GPT (read first)

tradekit (github.com/mmunro3318/tradekit, 824 tests green) already has,
adversarially reviewed and frozen: a deterministic risk kernel
(ATR-risk ∧ quarter-Kelly sizing, negative-Kelly→0), a policy engine
(R-001..R-018, percent-of-principal dials, fail-closed on unknown
outcomes), thesis contracts (falsifiable machine-checkable predicates,
immutable post-submit), an event-sourced hash-chained ledger with exact
replay, bidirectional reconcile→auto-halt, halt-first verdict-token
gating, two-man live promotion, and an algorithmic edge definition
(Deflated Sharpe Ratio gate per Bailey–López de Prado, n≥30; penalized
Sharpe 10–29; PF≥1.3 ∧ expectancy>0 for "positive" verdict). Your design
docs should specify strategy content and prop-specific mechanics ON TOP
of this substrate. Where a question below duplicates an implemented
decision I answer BUILT and describe the existing behavior — treat those
as constraints, not open questions.

The single biggest blocker is Report 1 (Kraken Props API + rules).
Questions R.337 (is automation permitted at all) and R.359–361
(multi-account / identical-strategy / discretionary-disqualification
terms) are GO/NO-GO — they must be answered from official sources before
any prop-specific engineering.

---

## A. System objective and success criteria

1. One policy, two dial-sets. The engine and rules are identical; only
   per-account dials differ (BUILT: TD-24 AccountConfig layering exists
   exactly for this).
2. Yes — evaluation mode slightly more conservative than funded (the
   eval fee is cheap; the funded account is the asset worth protecting,
   but blowing evals serially is a process failure signal).
3. Priority order: account survival > positive expectancy > low variance
   > payout frequency > evaluation completion speed > capital growth.
   Speed is deliberately second-to-last: Kraken has no deadline, so time
   is the one free resource — spending it buys survival probability.
4. Soft target 90 days; no hard cap. If we're not at +10% in 90 days,
   that's a review trigger, not a reason to raise risk.
5. Yes — risk tapers as a function of remaining distance to target AND
   remaining drawdown buffer (a ratchet: at +8% with target +10%, risk
   what's needed, not the standard unit).
6. Yes. Hit target → flatten, halt, human confirms progression. Never
   "one more trade" past the objective.
7. Success = remain funded indefinitely + regular payouts, achieved by
   minimizing probability of account failure. Monthly-return targets are
   explicitly NOT an objective (target-chasing is how prop accounts die).
8. Recommendation: ≤2% / month, ≤8% / 6 months, ≤15% / year probability
   of account failure, validated by Monte Carlo (M.241–243). MIKE may
   tighten.
9. Stricter internal survival limits, always (BUILT house rule: every
   ambiguity resolves against the trade; R-017/R-018 already model
   internal daily/lifetime drawdown gates independent of the venue).
10. Yes, absolutely. Inactivity for days/weeks when no qualified edge
    exists is a feature. This is Mike's standing no-gambling red line:
    no edge → no position.

## B. Human authority and autonomy

11. V1 = executes entries after approval (SUPERVISED_LIVE), graduating
    to fully-executes-and-manages after the supervised record supports
    it. BUILT: verdict-token gate + two-man promotion is exactly this
    ladder.
12. Yes — every live entry initially (matches tradekit's P4-live plan:
    first trades are individually human-confirmed).
13. Protective exits ALWAYS execute automatically, no approval ever.
    Human approval on exits is a survival bug, not a control.
14. Yes — Mike may always close a system trade. System records it as an
    external close and reconciles.
15. No. Manual trading in the system's account destroys attribution and
    poisons the trade log the edge statistics depend on. Separate
    account for discretionary trades.
16. Halt + reconcile, then supervised mode until human confirms (BUILT:
    bidirectional reconcile→auto-halt is the existing behavior).
17. No — a strategy rejection stands. Human can log disagreement for
    offline review.
18. Never (agree with your recommendation). The risk kernel is the one
    component with no override path, by design (BUILT).
19. Yes — any manual intervention requires a written reason in the
    journal.
20. Yes — adopt the mode list, mapped onto tradekit's existing lifecycle
    (paper/live tiers, halt states). HALTED must be reachable from every
    mode; AUTONOMOUS_LIVE is a later phase, not v1.
21. Mode promotion: Mike only, with CTO co-sign (BUILT: two-man confirm
    is the existing promotion mechanism). Demotion/halt: anyone and
    anything — the system itself, watchdog, or human, instantly.
22. Yes — formal checklist + signed configuration hash per deployment.
    (tradekit already treats config dials as versioned data; hash-sign
    them.)

## C. Trading schedule and attention constraints

23. MIKE (UPS shift hours).
24. V1 supervised: trade only when Mike is available to approve, by
    definition. Post-supervision: no — the system trades on its own
    schedule within its rules; that's the point of the safety
    architecture.
25. MIKE — but if entries need approval in v1, the answer during the
    shift is effectively "no new entries; protective exits run."
26. Human-facing: Mike's local timezone. MIKE to confirm which.
27. Yes, UTC internally, everywhere, always (BUILT — this is already
    tradekit law; delayed-fuse clock bugs taught us the hard way).
28. Crypto trades 7 days, so yes — but see 29.
29. Weekends allowed with stricter liquidity/spread gates (thinner
    books, weekend gap risk into Monday flows). Data-driven thresholds
    from Report 2.
30. Yes — per-asset blackout of empirically poor-liquidity hours,
    derived from data (R2), not hardcoded folklore.
31. Yes.
32. Flat ≥30 minutes before Kraken's daily reset as the default dial;
    exact reset mechanics pending R1 — if the reset snapshot uses
    equity, being flat at the snapshot is the only safe posture.
33. Absolute. A profitable open position near the cutoff is still
    exposure against a rule boundary; flat means flat.
34. Both: per-strategy max hold (part of each strategy spec) plus a
    global backstop the risk kernel enforces.
35. Yes — setup-window expiry closes the position (BUILT: thesis
    time_expiry predicates + horizon-expiry-equals-FAIL grading already
    encode "your window passed, you were wrong about timing").

## D. Asset universe

36. Yes — BTC and ETH only at first. Add SOL (Mike holds it) as the
    third once the first strategy validates on the majors.
37. Scanner monitors 5–10 initially.
38. Eventually eligible: ~20–30 ceiling. Beyond that, governance cost
    exceeds edge contribution for an account this size.
39. Fixed per-account universe, updated only at scheduled reviews
    (BUILT: per-portfolio/per-agent universes with watch-only
    benchmarks is already the designed shape).
40. Monthly review; emergency suspension anytime.
41. MIKE (fundamental acceptability is a values call — his stated
    universe leans infrastructure/compute: ETH/SOL/LINK/NEAR/TAO).
42. For policy purposes: no cash-flow/utility thesis + narrative-driven
    valuation + concentrated social-media-correlated flows. Precise
    scoring → R9.
43. Yes, continuum — a meme-ness score feeding eligibility, not a
    binary. Binary labels invite boundary-gaming.
44. Yes — hype/manipulation suspension for otherwise-legit assets
    (metrics from R9: volume anomalies vs. history, funding extremes,
    social spike proxies).
45. Yes special treatment: stablecoin pairs excluded from directional
    strategies; wrapped/LST assets inherit underlying's classification
    plus depeg/bridge risk flags; exchange tokens carry issuer risk
    flags. Details → R9.
46. No privacy coins (regulatory tail risk, delisting risk). Cheap to
    exclude, expensive to be wrong about.
47. Yes — major regulatory uncertainty excludes (same logic as 46).
48. Yes — suspend around large unlocks (threshold: unlock >1% of
    circulating supply within 7 days; refine in R9).
49. Yes for extreme concentration; scored not binary (R9).
50. ≥2 years trading history default; ≥1 year acceptable only with
    top-decile liquidity. Younger = regime sample too thin to validate
    anything.
51. R2 for real numbers. Placeholder gates: median spread ≤5bps on the
    entry timeframe, 24h volume ≥$100M, depth such that our order is
    ≤5% of top-of-book (see I.141).
52. Yes — eligibility is per (asset, strategy) pair, exactly as your
    example describes.
53. Yes — crypto correlations approach 1 in stress; correlation-adjusted
    exposure is mandatory the moment max_open_positions > 1.
54. Yes — all nine fields. This is the asset dossier; it also feeds the
    LLM context (K.191).
55. Offline agents may RECOMMEND both additions and removals, but
    removals from the blacklist (i.e., re-enabling an asset) require
    Mike's explicit sign-off. Asymmetry is the point: easy to restrict,
    hard to permit (BUILT house principle: anti-permissive defaults).

## E. Strategy philosophy

56. Recommendation: pullback-continuation within trend, with breakout /
    volatility-expansion as the closely-related sibling. Rationale:
    (a) matches the regime machinery we have (trend states are what the
    HMM detects best); (b) mean-reversion in crypto intraday is a
    fee-and-tail-risk grinder for small accounts; (c) order-flow needs
    tick/book data we don't yet have. Validate against R3's evidence.
57. One family, 2–3 tightly related setups sharing risk logic and most
    parameters. Not one lone setup (too little signal flow), not
    multiple families (attribution mush).
58. Max 2 active validated strategies per account in v1.
59. Yes — compete for the single slot.
60. Deterministic weighted rank on expected value per unit time,
    penalized by risk and cost share; LLM may VETO the winner but never
    promote a loser. Deny-only LLM authority is the standing pattern
    (BUILT: no-newer-deny token semantics).
61. Yes — every strategy declares prohibited regimes in its spec (the
    asset-registry "prohibited regimes" field mirrors this).
62. Yes — unrecognized/neutral regime = PASS. BUILT: ASSUMPTIONS 53
    already pins neutral = no-recommendation; extend the same rule here.
63. Per-asset parameters only where evidence demands it;
64. — default is globally shared parameters. Every per-asset parameter
    multiplies the overfitting surface and the n_trials penalty we
    charge ourselves in DSR.
65. Transparent rules + interpretable statistical models for live v1.
    Gradient-boosted models permitted as offline trade FILTERS
    (meta-labeling) once validated. Neural models: research tier only
    for now. (candlerl remains a sandboxed experiment.)
66. Yes — every live strategy needs a plausible market-mechanism story
    (who is on the other side and why they're systematically paying us).
67. For LIVE: no — mechanism required. A durable-but-unexplained edge
    may run in paper/shadow indefinitely and earn promotion
    consideration only with an extended record; unexplained edges decay
    without warning because you can't monitor a mechanism you can't
    name.
68. Both: probabilistic internally (calibrated probabilities), mapped to
    deterministic execution decisions at declared thresholds.
69. V1: direction + probability(target before stop) + expected holding
    time. Expected MAE is a fast-follow (it improves stop placement).
    Full return distribution: research tier.
70. Candle close only in v1. Intrabar triggers are a live/backtest
    parity nightmare; earn them later.
71. Only with the "knowable time" modeled exactly (BUILT: fractal swing
    points already carry a k-bar confirmation delay handled this way;
    F.89 formalizes it).
72. Defer the FORGE-style pattern engine. Pattern logic multiplies
    hypothesis count (n_trials!) faster than it adds edge for an
    account this size.
73. Indicators as regime classification + confirmation + risk
    adjustment. Not standalone primary signals — the setup logic is
    primary.
74. Allowed in v1: funding rates, open interest, liquidations (they're
    venue-native, point-in-time-safe, mechanism-relevant). Macro events:
    calendar-blackout only (don't trade INTO known events), not as
    signal. News/sentiment/on-chain: offline research only for now.
75. Live external sources v1: Kraken-native data + a static economic
    calendar. Everything else is research-tier.
76. Yes — external context failure degrades to the no-context behavior,
    never blocks protective operations (BUILT pattern: fail-safe seams).
77. Nonessential missing → reduce confidence (which may itself gate to
    PASS at threshold). Essential missing → reject the trade. Each
    strategy spec must label its inputs essential/nonessential.

## F. Timeframes and data resolution

78. Primary decision timeframe: 1-hour for trend context, 15-minute for
    execution decisions. 1m/5m are noise-dominated relative to our cost
    model at this account size.
79. Yes — multi-timeframe context.
80. Dominant trend: 4-hour.
81. Entry trigger: 15-minute.
82. Minimum history: 2 years at 1h/4h; 1 year at 15m. Must span at
    least one full bull/bear transition.
83. Yes — start collecting Kraken trade (tick) data NOW even though no
    v1 strategy uses it. It's cheap, and it unlocks CVD/order-flow
    research and execution validation later. (Standing gap: CVD needs
    tick trades.)
84. Order-book data: execution validation only in v1, not required for
    the first strategy.
85. Recalculate on bar close of the relevant timeframe.
86. Candle-close evaluation only (consistent with 70).
87. Strict point-in-time semantics: bars carry version + knowable time;
    late/revised candles create a new version, never mutate history;
    duplicates deduped on (symbol, timeframe, open_time); gaps flagged
    and strategies must declare gap tolerance (BUILT: the cache layer +
    insufficient-bars-skip-with-warning behavior already lean this way).
88. Yes — event time and receipt time on everything.
89. Yes — third "knowable time" for confirmation-delayed constructs
    (BUILT precedent: swing-point k=2 delay).
90. Trust Kraken's candles in v1; continuously spot-check them against
    bars rebuilt from our own tick collection (83) and alert on
    divergence.

## G. Regime detection

91. Adopt the richer taxonomy as the TARGET vocabulary, but v1 maps onto
    what's built and validated: tradekit's 3-state HMM
    (low_vol_trend / high_vol_chop / breakdown) + neutral, with
    directional split of trend (TREND_UP/TREND_DOWN) as the first
    extension. ILLIQUID and EVENT_SHOCK enter as orthogonal FLAGS, not
    HMM states (see 92). Don't fragment into 9 states before we have
    trades to validate 4.
92. Primary regime mutually exclusive; orthogonal boolean overlays
    (illiquid, event_shock) that any regime can carry. Overlapping
    primary labels make the routing table untestable.
93. A deterministic rules fallback is mandatory (BUILT: vol-percentile →
    ADX grid exists);
94. — and yes, the ML classifier (HMM) may sit on top (BUILT). Rules
    fallback answers when the model can't.
95. Yes — regime confidence required; low confidence collapses to
    neutral, and neutral = no recommendation (E.62).
96. Regime transition → no NEW entries for N bars (dial, default 2 bars
    of the decision timeframe); open positions keep their
    strategy-defined management. Transitions are where classifiers are
    most wrong.
97. Per-asset regime models, yes.
98. Yes — a market-wide crypto regime from BTC (BTC is the market's
    risk factor; an alt "uptrend" against a BTC breakdown is noise).
99. Yes — BTC context constrains alt trades (alt entries require BTC
    regime not-breakdown).
100. Yes — halt alt entries when BTC realized vol exceeds a percentile
     threshold (dial; calibrate in R6).

## H. Risk model

101. Confirmed: 0.15% of equity normal risk per trade. Note tradekit's
     sizing kernel (min of ATR-risk and quarter-Kelly) applies UNDER
     this cap — the dial is a ceiling, not the formula (BUILT).
102. Confirmed 0.25% as the exceptional ceiling — but see 107: unused in
     v1.
103. Lesser of starting balance and current equity. Most conservative
     denominator, and it matches how trailing-drawdown venues actually
     compute pain.
104. Yes — risk steps down automatically in drawdown (tiered, see 106).
105. NO automatic risk increase after profits. This is a red line:
     tradekit's TD-11 exists precisely so P&L history can never inflate
     size. Step-ups happen only via scheduled human review of a
     longer record.
106. Fixed tiers, not a continuous formula. Tiers are auditable,
     testable, and legible in the journal. Example ladder (validate in
     R5): normal 0.15% → after −2% from high-water 0.10% → after −4%
     0.05% → at internal soft limit, halt.
107. Exceptional tier: defined but DISABLED in v1 (dial None). If ever
     enabled: pre-registered A+ criteria, never discretionary.
108. Yes — first 30 live trades at 0.05%, next 30 at 0.10%, then 0.15%.
     Cheap insurance against live/paper divergence.
109. Yes (agree): strategy owns the stop, risk kernel owns the size.
     BUILT — this is exactly the existing separation.
110. Yes — broker-side protective stop must exist immediately after
     entry; if stop placement fails, emergency-close the position
     (P.301–302).
111. Yes, time stops allowed (and encouraged — C.35).
112. Yes — invalidation exits before the price stop are core to the
     thesis contract (BUILT: falsifiable predicates ARE the
     invalidation).
113. Never widen stops (agree). No exceptions, no override path.
114. Tightening allowed,
115. — but only by strategy-defined rules, never ad hoc.
116. Trailing stops allowed if strategy-defined and backtested as part
     of the strategy spec.
117. Break-even rules allowed but NOT a default — moving to break-even
     "because it feels safe" measurably hurts many trend strategies;
     it must earn its place in backtest.
118. Partial profit-taking: not in v1 (couples with I.155–156; one
     position, one exit plan keeps the trade log clean for edge stats).
119. Yes — minimum reward-to-risk 1.5 as a sanity floor,
120. — AND EV-based ranking on top. The floor catches cost-model errors;
     EV does the real work.
121. Max complete-trade loss including costs and slippage: 0.30% of
     equity (2× planned risk = gap allowance). A realized loss beyond
     this triggers the slippage-anomaly halt (129).
122. Soft daily stop: 50% of Kraken's daily limit consumed → no new
     entries today.
123. Hard internal daily stop: 70% of Kraken's daily limit → flatten and
     halt. (Expressed as fractions of the venue limit so they survive
     rule changes; absolute numbers land after R1.)
124. Consecutive losses: 3 → cooldown (no entries for 4 hours);
     4 → risk tier down one step for the day; 5 → done for the day.
     Strategy SUSPENSION is never triggered by raw streaks — that's
     statistical (N.260).
125. Both, with different jobs: streaks drive same-day operational
     brakes (cheap, dumb, safe); statistically unusual loss patterns
     drive strategy-level decisions.
126. No hard stop on daily profit in funded mode, but risk tapers after
     a strong day (128). In EVALUATION mode near the target: yes, stop
     — A.5/A.6.
127. Yes — after a day reaches +1%, ratchet: give back at most half of
     that day's gain, then flat for the day.
128. Yes — modest de-risk after an abnormal winning streak (a hot
     streak is more often regime luck than skill; it also often means
     vol expanded).
129. Yes — slippage beyond model bounds (121) = immediate halt +
     reconcile.
130. Daily-loss buffer: ≥30% of Kraken's daily allowance must remain
     unused at all times (i.e., our hard stop at 70%, per 123).
131. Total-drawdown buffer: ≥40% of the max-drawdown allowance unused;
     crossing it puts the account in reduced-risk mode pending review.
132. No — open profit never sizes new trades (103's lesser-of rule
     makes this structural).
133. All three (gross, net directional, correlation-adjusted) once
     multiple positions are enabled; v1 single-slot only needs gross.
134. Yes — a jump/gap risk estimate per asset (fat-tail multiple on
     stop distance; calibrate in R5/R2). It feeds 121's gap allowance.
135. Yes — liquidation price must sit ≥3× stop distance beyond the
     stop, always. If leverage puts liquidation closer, cut leverage.
136. Yes (agree): leverage is an OUTPUT of sizing, never a target.

## I. Costs and execution quality

137. Expected costs ≤15% of planned risk, else reject.
138. Stressed costs ≤30% of planned risk, else reject.
139. Yes — narrow-stop rejection is the same gate as 137 seen from the
     other side; both live in the risk kernel.
140. Yes — per-asset spread/slippage model (R2 supplies the initial
     parameters).
141. Yes — order ≤5% of visible depth at intended price level
     (placeholder; refine with R2).
142. Progressively richer, in order: fixed bps (v1) → volatility-scaled
     → historical replay → live depth. Don't build stage 4 to justify
     stage 1 trades.
143. Prefer passive limit entries where the setup allows (pullback
     entries are naturally passive); breakout entries use marketable
     limits (148).
144. Limit entry lifetime = the setup window, never longer.
145. No chasing after a missed entry. Missed = missed; journal it as a
     counterfactual (O.273).
146. Max 2 repricing attempts within the original signal's validity.
147. No unrestricted market orders for entries, ever.
148. Yes — marketable limit (crossing the spread with a price cap) is
     the urgent-entry default.
149. Yes — protective stops are stop-market. Exit certainty beats exit
     price when the stop is the survival mechanism.
150. Yes — take-profits as resting reduce-only limits.
151. Partial fills: position becomes active with whatever filled;
     protective stop covers the filled quantity immediately.
152. ≥50% filled within the entry window = treat as a full trade for
     management; <50% = manage but flag "underfilled" in the journal
     (its stats are noisier).
153. Yes — cancel the remainder after a timeout (default: 2 bars of the
     entry timeframe).
154. Yes — stop/target quantities auto-update on every fill event
     (BUILT: the order pipeline's fill events already flow through the
     ledger; this is a consumer of them).
155. Agree — no scaling in for v1.
156. Scaling out: v2, together with 118.
157. Yes — reconcile fees and funding against broker records after
     every trade (BUILT: reconcile-after-each is already the live
     protocol).
158. Any unexplained cash discrepancy >$0.01 halts (BUILT: this is the
     existing reconcile standard — EV blocks validate to the cent).
159. Model funding exactly; avoid holding through funding only when the
     funding cost flips the trade's EV. Categorical avoidance distorts
     exits for no reason.
160. Yes — expected holding time is already in the ranking (E.60:
     EV per unit time).

## J. Order and position management

161. V1 order types: limit, marketable limit, stop-market (protective),
     reduce-only limit (TP). Nothing else.
162. Yes — every entry creates linked protective exits atomically; an
     entry whose protection can't be placed gets closed (P.302).
163. R1. Assume emulation is required and design the engine to emulate
     bracket/OCO; native support becomes an optimization.
164. R1 — and this is a hard requirement, not a preference: broker-side
     protection MUST survive our disconnection, or the venue is unfit
     for autonomous operation (supervised-only until proven).
165. Yes — cancel working entries the moment the originating signal
     invalidates.
166. Yes — working entry orders count toward max_open_positions.
167. Yes — separate max_pending_entries (v1: 1).
168. Yes — holding one position while monitoring candidates is fine;
     they queue against the slot.
169. Expire and re-evaluate fresh. Queued-stale candidates execute
     yesterday's opinion at today's prices.
170. Agree: close → flat → independently reconsider. No direct
     reversals.
171. Yes — reduce-only wherever the venue supports it (all exits should
     be reduce-only).
172. Isolated margin per position where configurable (bounds the blast
     radius; matches 135).
173. Yes — global max duration backstop (C.34).
174. Yes — stale positions tighten progressively (time-decay of the
     thesis: if it hasn't worked, it's increasingly likely wrong).
175. Agree: halt and reconcile (BUILT — this is the existing
     state-disagreement behavior, verbatim).

## K. LLM and agent responsibilities

(This section is tradekit's core architecture. The standing law:
**LLMs author theses and can only ever deny; deterministic code computes
every number.**)

176. Live authority: (a) author thesis candidates within the schema,
     (b) veto deterministically-approved candidates. That's the whole
     surface.
177. Yes — beyond thesis authoring, it chooses only among precomputed
     actions.
178. Confidence is set at thesis submission and immutable after (BUILT:
     theses are immutable post-submit). No live confidence edits.
179. Veto: yes — deny-only authority is the pattern (BUILT: no-newer-
     deny token semantics).
180. Ranking: advisory only; the deterministic rank (E.60) is
     authoritative.
181. Strategy selection: only via strategy_tag on the thesis, and the
     regime gate + policy still apply after (BUILT).
182. Agree: never. Entry, stop, target, size are kernel outputs.
183. Yes — strict JSON schema (BUILT: pydantic thesis contract,
     validated to the cent).
184. Yes — every rationale must cite the deterministic inputs used
     (feeds O.282's "did the LLM add value" review).
185. Structured features + prepared summaries. Never raw market data —
     LLMs doing arithmetic on raw ticks is how numbers get invented.
186. Yes — recent journal context (its own recent decisions and
     outcomes).
187. Bounded window: last ~20 decisions + current asset dossier +
     regime state. Not the full history.
188. NO running P&L,
189. — precisely because P&L awareness is the revenge-trading /
     fear-trading vector,
190. — yes: blind the trading agent to account P&L entirely; the risk
     kernel (which sees everything) handles all P&L-dependent behavior.
     This extends tradekit's TD-11 (sizing purity) to the agent layer.
191. Yes — asset dossiers (D.54).
192. News summaries: not in the live loop v1 (prompt-injection surface +
     unvalidated signal). Offline research reads news freely.
193. No unbounded recursion; fixed tool budget per decision (v1: ≤5
     calls, no self-spawning).
194. Latency budget: 60s per decision — trivially fine for 15m bars,
     and it forces us never to build latency-sensitive LLM logic.
195. Agree: timeout → PASS (or WAIT if the window allows re-evaluation).
     Never execute on timeout.
196. Invalid JSON → one retry with the validation error; second failure
     → PASS + logged.
197. Two agents disagree → no trade. Deny always wins (BUILT
     principle).
198. One live agent in v1. Multi-agent adds failure modes faster than
     judgment at this stage.
199. Yes — adversarial review is offline (BUILT: that's the existing
     review/rubric machinery, e.g. rubric-thesis-v1).
200. Yes — archive all prompts, tool I/O, model versions, outputs
     (BUILT: event-sourced journal; extend it to agent I/O).
201. Yes — a model version change is a strategy-version change (N.268):
     revalidate in shadow before live.
202. Agree: no online self-modification, ever.
203. Yes — the agent proposes changes as written recommendations for
     offline human+CTO review.
204. Hosted API (Claude) for v1. Local models: research tier.
205. MIKE. Suggested cap: $50–150/month for live inference; alert at
     80%.

## L. Research and machine learning

206. Known strategy families first. Novel-edge search is the research
     program's LATER output, and every candidate it produces pays the
     n_trials selection penalty in our DSR gate (BUILT — the penalty
     mechanism exists; the experiment registry that feeds it honestly is
     open work and becomes MANDATORY the day we start searching).
207. Yes — benchmark all five baselines, and treat "random entry with
     the same exit model" as the single most important one: it isolates
     whether the ENTRY carries any information beyond the exit/risk
     machinery.
208. Trade filtering (meta-labeling) first — highest value per unit
     risk: deterministic signals generate, ML only vetoes. Regime
     classification second (we have the HMM to improve). Signal
     GENERATION by ML: last.
209. Filter only, for live (follows from 208). ML-generated signals stay
     in research.
210. Live models must be interpretable (feature attributions reviewable
     in the journal). Research models: anything.
211. Initially: logistic regression + gradient boosting. That's it.
212. Yes — every probabilistic model must be calibrated (Platt/isotonic)
     and its calibration monitored in production.
213. Brier score + calibration error + net EV among executed candidates.
     (Log loss acceptable as a training objective; it's not the
     qualification metric. Precision alone is banned — it ignores
     costs.)
214. Labels = strategy-specific outcomes,
215. — i.e., barrier outcomes (target/stop/time-expiry = the triple
     barrier), which is exactly what tradekit thesis grading already
     produces (BUILT: graded theses ARE labeled events; stop-wins-on-
     ambiguous-bar, horizon-expiry=FAIL).
216. Purged + embargoed cross-validation (López de Prado) — R4 codifies
     the exact procedure.
217. Class imbalance: class weights in training; decisions threshold on
     calibrated EV, never on accuracy.
218. Train pooled/hierarchically across assets first; per-asset models
     only when pooled residuals prove asset-specific structure.
219. Asset identity as a feature: yes, in pooled models (that IS the
     hierarchy's cheap form).
220. Regime identity as a feature: yes.
221. Retraining: monthly at most, on a fixed calendar (never
     event-triggered by a losing streak — that's laundering revenge
     trading through a pipeline).
222. Yes — model promotion is manual, two-man (BUILT promotion
     mechanism).
223. Minimum sample: ≥500 labeled events for a filter model; ≥30 live
     trades before its live effect is even evaluated (matching the DSR
     n≥30 regime).
224. Cold start: heuristic (rules-only) mode trades; ML runs in shadow
     alongside, logging what it WOULD have vetoed.
225. Yes — heuristic vs. learned mode is an explicit, journaled flag on
     every decision.
226. Evidence to touch live orders: shadow record showing the filter
     improves net expectancy over ≥30 consecutive trades, evaluated
     through the same edge_verdict machinery as strategies (BUILT — a
     filter is just a strategy modifier and pays the same tolls).
227. Include ALL graded trades — wins and losses — in training data.
     Voided trades excluded (consistent with BUILT ASSUMPTIONS 71:
     None-pnl never fabricated into data).
228. Yes — counterfactual outcomes for rejected candidates (O.273); it's
     the only unbiased view of what the filter costs us.
229. Research agents generate hypotheses AND code,
230. — and generated code goes through the exact pipeline human code
     does: four-stage TDD, frozen tests, CTO review, ASSUMPTIONS
     ratification (BUILT process — no second-class review track for
     machine-written code).

## M. Backtesting and validation

231. Study 2019→present (captures 2020 crash, 2021 mania, 2022 bear,
     2023–24 recovery, 2025–26 current). Minimum acceptable: 2021→
     present.
232. At least 4 distinct regimes represented, and
233. — yes: bull, bear, sideways, crash, low-vol must all appear in the
     evaluation data. A strategy unexamined in a crash is unvalidated.
234. Independent OOS = time-later, embargoed (gap between train and
     test), ≥6 months, spanning ≥2 regimes.
235. Anchored walk-forward as the primary protocol; nested time-series
     CV for ML model selection inside training windows only.
236. All tuning inside walk-forward training windows; the test segments
     are touched once per candidate, and every candidate increments
     n_trials (BUILT: the DSR penalty is where data-snooping gets
     charged).
237. Yes — one final untouched holdout, used exactly once, immediately
     before live promotion. Using it twice = it's training data now.
238. ≥100 backtest trades minimum (the live DSR floor is n≥30; backtests
     are cheaper and get a higher bar).
239. ≥30 trades per (asset, regime) cell before that cell's behavior is
     treated as known; thinner cells are flagged "descriptive only"
     (mirrors the BUILT G1 small-sample regime).
240. All listed metrics computed (most are BUILT in StrategyMetrics).
     Decision weight concentrates on: expectancy net of costs, profit
     factor, max drawdown, time under water, tail loss, DSR — plus the
     two prop-specific ones below.
241. Yes — simulated P(pass evaluation before failure) is the primary
     prop-specific metric,
242. — and funded-account survival is simulated separately (different
     absorbing barriers, different horizon).
243. ≥10,000 Monte Carlo paths.
244. Yes — resample trade order with block bootstrap (blocks preserve
     the serial correlation that kills naive resampling).
245. Yes — randomize slippage, missed fills, delays, outages.
246. Yes — parameter perturbation (±20% on every parameter; the edge
     must survive the neighborhood, not the point).
247. Yes — 1-bar entry delay as a standard stress. If a strategy dies
     from one bar of delay, it's a latency artifact, not an edge.
248. Yes — stress stop fills beyond observed data (gap multipliers from
     H.134).
249. Yes — exact Kraken fee schedule (R1),
250. — and exact daily-reset/equity-loss mechanics (R1). Approximating
     the barrier you're being evaluated against is self-sabotage.
251. Yes — position limits and leverage modeled.
252. Kraken's own data mandatory for FINAL validation;
253. — other exchanges fine for research and early development,
254. — with the basis/microstructure gap handled by requiring the final
     anchored walk-forward + holdout pass to run on Kraken data only.
255. Yes — synthetic scenario tests for conditions history lacks
     (flash crash mid-position, stale feed, exchange outage at stop
     price). BUILT precedent: the seam-scenario suite does exactly this
     at the execution layer; extend the idea to strategy behavior.
256. Minimum robustness: survives 1-bar delay, 2× modeled slippage,
     ±20% parameter perturbation, block-bootstrap p5 path still passes
     the account simulation, and every regime cell with n≥30 has
     expectancy ≥ 0 after costs.
257. Disqualifiers for an apparently profitable strategy: profits
     concentrated in <5 trades or a single regime; PF>3 without an
     unusually convincing mechanism (BUILT: overfit_risk_pf warning
     exists at exactly this threshold); edge monotonically shrinking
     across walk-forward segments; failure of any 256 stress; no
     mechanism story (E.66); or cost share breaching I.137 in live
     conditions.

## N. Strategy lifecycle and edge decay

258. Lifecycle: RESEARCH → BACKTEST → SHADOW → PAPER → SUPERVISED_LIVE
     → LIVE, with PROBATION / SUSPENDED / RETIRED as exit states —
     mapped onto tradekit's existing T1/T2 promotion machinery rather
     than a parallel system (BUILT: promotion gates R-016, two-man
     confirm).
259. Probation triggers: rolling expectancy below the backtest's
     Monte Carlo p10 band; calibration drift beyond threshold;
     execution-cost share drifting above I.137.
260. Auto-suspension: statistical breach (SPRT/CUSUM crossing the
     predefined boundary), or MDD breach, or repeated execution
     anomalies. Never raw loss streaks (H.124).
261. All three (losses, calibration drift, execution degradation) —
     each with its own detector; any one suffices.
262. Bad luck vs. decay: pre-compute the luck envelope from the
     backtest's Monte Carlo (243) at validation time; live performance
     inside the envelope = luck, sustained excursion below p5 = decay.
     The boundary is set BEFORE going live, so the decision is never
     made while bleeding.
263. Rolling windows: last 20 trades, last 50 trades, last 30 calendar
     days — all three monitored (trade-count windows for statistics,
     calendar for regime drift).
264. Yes — SPRT for "is expectancy still positive," change-point
     detection (CUSUM) for "did the distribution shift." R4 specifies
     parameters.
265. Yes — suspended strategies keep running in shadow. Shadow is free
     information.
266. Restoration: shadow record back inside the luck envelope over ≥30
     trades + human review + two-man re-promotion. Same gate as initial
     promotion — suspension resets trust to zero.
267. No live parameter updates;
268. — every parameter set is a new strategy version with its own
     shadow→live ladder and its own n_trials increment (BUILT: this is
     what makes the DSR penalty honest).
269. Full strategy review: monthly.
270. Yes — strategies expire quarterly and require reapproval; approval
     is a perishable, not a title.

## O. Journal and explainability

271. Journal every observed setup, not just gate-passers. Rejected
     setups are the denominator of every honest statistic.
272. Yes — WAIT and PASS tracked as first-class decisions.
273. Yes — counterfactual follow-up on rejects (feeds L.228).
274. Counterfactual tracking runs to the setup's own horizon (the same
     time_expiry the thesis would have carried), then closes with a
     virtual outcome. Default cap: 2× the strategy's max hold.
275. Yes — all nine fields.
276. Yes — machine rationale (deterministic inputs, reason codes) and
     LLM narrative are separate fields; the machine record is
     authoritative, the narrative is commentary.
277. Yes — machine-readable reason codes on every decision (BUILT
     precedent: policy audit hits like not_configured are exactly this
     pattern).
278. No image storage — store the data identifiers and render charts on
     demand (279 makes this free). Images are bulk without
     information.
279. Yes — full input reproducibility from stored identifiers (BUILT:
     point-in-time cache + event-sourced decisions).
280. Yes — exact decision replay (BUILT: the ledger's replay/rebuild
     idempotence is the foundation; REPLAY mode in B.20 is its UI).
281. Yes — daily reports include missed opportunities (from 272/273).
282. Yes — weekly review of whether the LLM's vetoes added net value
     vs. pure deterministic operation (K.184 makes this measurable).
283. Machine rationale: at decision time, immediately. LLM narrative:
     after close (writing narratives mid-trade invites the narrator to
     become a participant).
284. Yes — immutable, append-only, corrections as new linked entries
     (BUILT: hash-chained ledger is exactly this).
285. MIKE.
286. Yes — if Mike intervenes manually, the intervention record should
     include his state/reason (B.19 already requires the reason;
     emotional context is cheap and valuable in postmortems). MIKE to
     confirm comfort.
287. Yes — all seven panels. Build order: prop-rule compliance +
     account buffer first (survival), the rest after.

## P. Failure handling and safety

288. HALT triggers: reconcile mismatch (BUILT), stop-placement failure,
     slippage anomaly (H.129), clock drift (293), venue-unavailable
     bursts, stale systemic data (289), config-hash mismatch, watchdog
     ping loss, human command. Halt-first is standing law (BUILT: halts
     block everything including resting-order polling paths).
289. Stale data on one asset → suspend that asset's entries; stale data
     systemically (multiple assets / heartbeat loss) → account-level
     halt of new entries. Protective exits attempt regardless.
290. Yes — broker API failure halts all new entries (broker-side stops
     are why open positions survive this, J.164).
291. Yes — database failure halts execution (can't journal = can't
     trade; an unjournaled trade doesn't exist).
292. LLM failure → agent-gated strategies go to PASS; deterministic
     protective operations continue untouched. LLM is never in the
     protective path, so its death can't matter there (K-section
     architecture guarantees this).
293. Yes — clock drift >250ms warns, >1s halts new entries (time is an
     input to everything; BUILT: UTC/clock seams exist everywhere for
     this reason).
294. Duplicate orders: client-generated idempotency keys on every order,
     dedup on venue order-id at reconcile (BUILT pattern in the
     pipeline).
295. Restart recovery: reload from event log, then full reconcile
     BEFORE any new action;
296. — yes, all six items (balance, equity, positions, open orders,
     recent fills, current loss-limit state) (BUILT: startup reconcile
     is the existing protocol).
297. Disagreement → halt + human (BUILT, verbatim).
298. Never auto-close unrecognized positions —
299. — halt and request human intervention. An unrecognized position
     means our model of reality is wrong; acting on a wrong model makes
     it wronger (BUILT: this exact case is a pinned deny).
300. Yes — protective exits broker-side whenever possible (J.164).
301. Stop order rejected → immediate retry once → emergency-close the
     position → halt.
302. Agree: fill-without-stop = immediate emergency close. No naked
     positions, not for one bar.
303. Partial fill exposed → protective stop on the filled quantity
     within seconds (I.151); if that placement fails → 302.
304. Yes — connectivity loss alerts Mike's phone.
305. Alert channels: push notification + email minimum; SMS for
     HALT-class events. MIKE to confirm preferences.
306. Yes — a kill switch reachable from Mike's phone that flattens and
     halts. (Kraken's own app serves as the v1 manual fallback; a
     first-party button is v1.5.)
307. Yes — risk limits duplicated in an independent watchdog process,
308. — with independent credentials and the authority to flatten
     without the primary system. Required BEFORE autonomous mode;
     supervised v1 may launch without it (Mike is the watchdog).
309. Yes — config frozen while any position or working order is open.
310. Yes — every deployment defaults to execution-disabled (BUILT:
     live_trading_enabled=false is the shipped default; keep this
     invariant forever).

## Q. Infrastructure and deployment

311. Research/backtest: Mike's desktop (status quo). Live: a small VPS
     (crypto trades while Windows updates reboot). Watchdog on a
     separate cheap host when 307 lands.
312. For supervised v1: no. For autonomous crypto: yes, 24/7, which is
     what forces the VPS.
313. Linux for the live deployment; development stays on Windows (the
     codebase is already OS-agnostic with path seams).
314. Yes — Python stays (BUILT: 824 tests of leverage say so).
315. Dashboard in JS/TS is fine — it's a read-only consumer of the
     journal/ledger; keep ALL trading logic in Python.
316. Yes — modular monolith (BUILT: that is tradekit's shape; no
     services until something measurable demands it).
317. Operational state: the existing event-sourced SQLite ledger is
     correct for v1 single-account (BUILT — it's hash-chained, replay-
     idempotent, and tested; do not rebuild it on a new database to
     satisfy a stack preference).
318. PostgreSQL/Supabase: when multi-account or remote dashboards
     demand it — as a projection/replication target of the ledger, not
     a replacement for it.
319. Yes — Parquet + DuckDB for research data.
320. Tens of GB is fine (candles are small; ticks dominate).
321. Tick/order-book retention: 2 years rolling, then downsample.
322. No message queue in v1.
323. Docker: yes, for the VPS deployment.
324. Yes — reproducible deployment (compose file + pinned images at
     minimum; full IaC when there's more than one host).
325. Secrets: .env locally (never in chat, never committed — standing
     rule with a scar); OS keyring/secret store on the VPS. Any key
     that appears in a chat gets rotated, period.
326. Yes — withdrawal-disabled, IP-allowlisted API keys wherever the
     venue supports it.
327. Yes — separate credentials AND separate databases per environment
     (BUILT: paper/live separation already works this way).
328. Yes — separate config-signing keys per environment (B.22).
329. All six; logs + metrics + alerts + audit are v1, traces when
     latency ever matters (it shouldn't — K.194).
330. Decision records and journals: retained indefinitely (they're
     tiny and they're the asset). Debug logs: 1 year.
331. Yes — automated backups of ledger + config + journal, offsite.
332. Restore test: quarterly, actually executed, not assumed.
333. Uptime: best-effort for supervised v1; 99%+ once autonomous
     (broker-side stops carry the gap either way).
334. Recovery time: ≤5 minutes to reconciled-and-halted state.
     Positions are protected broker-side regardless of our uptime —
     that's the real availability requirement (J.164).

## R. Kraken-specific research questions

335–368: ALL research needed — this is Report 1, verbatim, and it
blocks everything prop-specific. CTO priority ordering within it:

- **GO/NO-GO first**: 337 (automation explicitly permitted?), 359–361
  (multi-account/copy-trading/identical-strategy restrictions +
  discretionary disqualification). If automation is prohibited or
  gray, the whole program changes shape — answer these from official
  terms before any engineering.
- **Barrier math second**: 345–349 (exact unrealized P&L, daily-loss
  and max-drawdown formulas, balance-vs-equity snapshot, fee/funding
  timing around reset). M.250 cannot be built without these.
- **Execution surface third**: 335–336, 351–355 (API compatibility,
  order types, OCO/bracket support, stop trigger price source
  [mark/index/last — this changes stop placement], websocket fills).
- **Representativeness fourth**: 356–357 (sandbox availability, paper
  fidelity — determines how much our paper record predicts prop
  behavior).
- 362–368 (post-evaluation mechanics) matter but don't block design.

One BUILT note: tradekit's venue-error taxonomy (transient errors
RAISE, never fabricate terminal states) and reconcile machinery port
directly to whatever API R1 finds; the adapter is the only new code.

## S. Legal, tax, and operational boundaries

369. MIKE (presumably US — which matters for R1: confirm Kraken Props
     is available to US persons at all before paying an eval fee).
370. Yes — the ledger already preserves everything needed; add a
     tax-oriented export view (realized P&L by lot, fees, funding).
371. Yes — payouts, fees, and evaluation purchases tracked as distinct
     ledger categories.
372. Yes — monthly statements generated from the ledger.
373. Yes — rule-change audit trail (snapshot the venue's published
     rules on a schedule; diff and alert).
374. Yes — a detected terms-of-service change auto-suspends live
     trading pending human review. Cheap to build, saves the account
     exactly once.
375. MIKE — his standing capital/risk lines exist (documented in the
     project's vision answers); restate them in the Vision doc so the
     prop program inherits them explicitly.
376. MIKE. CTO recommendation: 3 evaluation fees maximum, then a
     mandatory full-program pause and review.
377. Yes — 2 consecutive evaluation failures trigger mandatory research
     review before a third attempt is purchased (a failed eval is data;
     two is a pattern).
378. MIKE. Suggested starting envelope: eval fees per 376; market data
     ~$0 (venue-native v1); cloud $20–40/mo; LLM per K.205; research
     tools $0–50/mo.

---

## CTO notes on the report set and document sequence

The 10-report decomposition is good — focused beats omnibus. Three
adjustments:

1. **Report 1 is the critical path and partially GO/NO-GO.** Commission
   it first and alone; its answers reshape Reports 2, 5, and 10. Don't
   parallelize the others until 337/359–361 confirm the program is
   viable.
2. **Reports 4 and 5 should be told what already exists.** tradekit has
   implemented DSR (Bailey–López de Prado, with kurtosis-corrected
   SR variance and n_trials deflation), penalized-Sharpe small-sample
   regimes, and PF/expectancy gates. Those reports should EXTEND this
   (PBO, purged CV, absorbing-barrier prop math) rather than re-derive
   it — otherwise we get a second, subtly incompatible math canon.
3. **Report 10 is mostly already built.** Event sourcing, order state
   machines, idempotency, reconciliation, fail-closed, replay,
   paper/live parity — tradekit has shipped and adversarially reviewed
   these. Rescope Report 10 to the genuinely open pieces: watchdog
   architecture, bracket emulation on Kraken specifically, and
   VPS/ops patterns.

Document sequence: agree, with one insertion — **Doc 2.5, "tradekit
Substrate Contract"**: a short document enumerating what the existing
system provides (risk kernel interfaces, thesis schema, ledger, policy
dials, edge_verdict machinery) so every subsequent strategy doc
designs against it instead of inventing parallel abstractions. The
Math Primer (Doc 3) should adopt tradekit's frozen definitions as its
notation baseline — the metrics conventions are binding and
golden-tested; the primer's job is to teach them plus the new prop
math, not to restate them differently.


