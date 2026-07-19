# Risk of Ruin and Prop-Account Optimization

## Overview

This report addresses the mathematics of survival under absorbing barriers: risk-of-ruin formulas, fixed-fractional and fractional-Kelly sizing, drawdown-sensitive position sizing, the static-versus-trailing drawdown distinction (directly relevant given Kraken Prop's own MDD design confirmed in Report 1), and industry pass-rate statistics that ground the questionnaire's own probability targets in real base rates. The central conclusion across every source reviewed is that survival-optimized sizing and growth-optimized sizing are different objectives requiring different formulas — and that the prop-account context specifically favors the survival objective, consistent with the CTO's own stated priority ordering.

## 1. Risk-of-ruin mathematics

Risk of ruin (RoR) is the probability that a trading account reaches a defined "ruin" threshold — total loss, or more commonly a specified drawdown percentage — before achieving its objective, given a fixed win rate, payoff ratio, and position size. Several closed-form approximations exist. A simplified equal-payoff formula is:[^1][^2][^3][^4]

\[
RoR = \left(\frac{1-p}{p}\right)^{C/R}
\]

where \(p\) is win rate, \(C\) is total capital in risk units, and \(R\) is risk per trade in the same units. A more general version incorporating an unequal payoff ratio is:[^5]

\[
RoR = \left(\frac{L}{W \times RR}\right)^{T/r}
\]

where \(L\) is loss rate, \(W\) is win rate, \(RR\) is reward-to-risk ratio, \(T\) is the ruin threshold, and \(r\) is risk per trade. A fixed-fractional variant, framed as an exponential decay in the ratio of edge to bet size, is:[^3]

\[
R = e^{\left(-\frac{2a}{d}\right)\left(\frac{\ln(1-z)}{\ln(1-d)}\right)}
\]

where \(a\) represents the account's statistical edge, \(d\) is the fractional bet size, and \(z\) is the fraction of capital defining ruin. Across every variant, the qualitative conclusion is identical and repeatedly emphasized: **risk of ruin changes exponentially, not linearly, with position size** — cutting position size in half reduces risk of ruin by far more than half. One worked numerical example illustrates this concretely: risking $5,000 per trade on a given account produced a 13% risk of ruin, while reducing risk per trade to $1,000 (a 5x reduction) reduced risk of ruin to a negligible 0.0005% — a reduction of several orders of magnitude for a proportionally much smaller change in bet size. This is the single most important quantitative justification for the questionnaire's conservative risk ramp (H.108: 0.05% for the first 30 trades, 0.10% for the next 30, only then 0.15%) — the exponential relationship means that early, uncertain-edge trades carry disproportionate ruin risk if sized at the eventual target level.[^4][^5][^1]

A commonly cited target threshold across retail risk-management sources: a well-managed strategy should target a risk of ruin below 0.5%, with the caveat that a risk of ruin of exactly 0% is mathematically impossible in any strategy with a nonzero loss probability. This directly informs how the questionnaire's own A.8 target (≤2%/month, ≤8%/6 months, ≤15%/year probability of failure) should be interpreted — these figures are meaningfully looser than the 0.5% retail rule-of-thumb, which is appropriate given the prop-account context (capital is not personally owned, so the failure consequence is an evaluation fee, not personal ruin) but should not be loosened further without deliberate justification.[^2]

## 2. Kelly criterion and fractional Kelly

The Kelly criterion computes the theoretically growth-optimal fraction of capital to risk per trade as:

\[
f^{*} = \frac{bp - q}{b}
\]

where \(p\) is win probability, \(q = 1-p\) is loss probability, and \(b\) is the payoff ratio (average win divided by average loss). Kelly sizing is explicitly a **growth-maximization** formula, not a survival-maximization formula — it is "theoretically optimal for a gambler with infinite time and no utility concern for drawdowns," a condition no real trader satisfies. Full Kelly sizing produces extremely large drawdowns in practice even when the underlying edge is genuine, which is why "most professionals don't use the full Kelly percentage but instead use a fraction of it — typically between 25% and 75% of the calculated value".[^6][^7][^8][^9]

Several practical constraints from the sourced material are directly relevant to the questionnaire's risk kernel design:

- **Sample size sensitivity:** Kelly inputs (p and b) require substantial trade history to estimate reliably — "fewer than 50 trades leaves too much estimation error," and a ±5 percentage-point uncertainty in win rate at small sample sizes can change the resulting position size by 3x or more. This directly validates the questionnaire's L.223 minimum sample threshold (≥30 live trades before a filter's live effect is evaluated) as being in the right neighborhood, though the Kelly literature specifically suggests 50–100 trades as the more defensible floor for sizing decisions.[^7]
- **Kelly as ceiling, not target:** the recommended practice is to set working size at quarter-Kelly and treat the full-Kelly calculation strictly as an upper bound, "scaling up only with a larger, more statistically stable sample". This directly matches tradekit's already-built quarter-Kelly sizing kernel described in the questionnaire's framing note — the literature confirms quarter-Kelly is not an arbitrary conservative choice but the standard practitioner recommendation.[^7]
- **Correlation adjustment:** Kelly's independence assumption breaks down for correlated positions; the correct treatment is to size the combined correlated exposure as a single Kelly-sized unit rather than applying Kelly independently to each leg. This directly supports the questionnaire's H.133 requirement that correlation-adjusted risk apply once multiple positions are enabled.[^7]
- **Per-strategy, not blended, calculation:** Kelly should be computed separately for each distinct strategy or setup type, since blending a breakout strategy's win rate/payoff with a mean-reversion strategy's produces "a meaningless average Kelly fraction". This is a direct, concrete argument for keeping the questionnaire's E.63–64 per-strategy parameterization at least at the level of Kelly inputs, even where other parameters are shared globally.[^7]
- **Sanity-check threshold:** if a computed Kelly fraction exceeds roughly 20%, the result should be treated with skepticism — either the sample is too small, the win rate is overestimated, or the strategy violates Kelly's underlying assumptions (fixed, i.i.d. payoff distribution). This is a useful automated sanity check the risk kernel could apply to flag a suspiciously large Kelly output rather than accepting it at face value, complementing tradekit's existing negative-Kelly-clips-to-zero behavior described in the questionnaire's framing note.[^7]
- **Recalculation cadence:** the Kelly fraction should be recalculated periodically (every 50–100 new trades, or quarterly) since win rates drift as market regimes change, and a Kelly fraction calculated during a trending market may be dangerously inflated if applied unchanged during a subsequent choppy regime. This is directly consistent with the questionnaire's own N.269 monthly full-strategy-review cadence.[^8][^7]

## 3. Absorbing barrier / gambler's ruin models

The mathematical foundation underlying risk-of-ruin calculations is the classical gambler's ruin problem: a random walk confined between two absorbing barriers (ruin at the lower barrier, a target/target-wealth at the upper barrier), where the walk terminates permanently the instant either barrier is touched. For a symmetric random walk on states \(\{0, 1, ..., N\}\) starting at state \(k\), the closed-form probability of eventually reaching the lower absorbing barrier (ruin) is \(1 - k/N\), and the probability of reaching the upper barrier (the target) is \(k/N\). This is the direct mathematical formalization of the questionnaire's own framing — the prop evaluation is structurally identical to a two-barrier gambler's ruin problem, where the lower barrier is the MDL/MDD breach threshold and the upper barrier is the profit target, and \(k/N\) (starting distance from ruin divided by total distance between barriers) is the single most important structural determinant of pass probability before any strategy-specific edge is even considered.[^10][^11][^12][^13]

Extended gambler's ruin models generalize beyond the simple symmetric case to compute not just absorption probabilities but also expected absorption time and the probability distribution of the maximum/minimum values reached before absorption — this generalized framework is exactly what the questionnaire's M.241–243 Monte Carlo simulation (estimating both pass probability and expected time-to-outcome) is approximating numerically rather than solving in closed form, which is the correct approach once realistic asymmetric win/loss distributions and serial correlation are introduced, since the closed-form gambler's ruin solution assumes symmetric, i.i.d. steps that real trading returns do not satisfy.[^13]

## 4. Static vs. trailing drawdown

This distinction is directly relevant given Report 1's finding that Kraken Prop's Maximum Drawdown is calculated from starting balance and does not trail upward with gains. Multiple independent sources confirm and describe this distinction generally: **static drawdown** stays fixed at its initial level regardless of subsequent profit, giving a trader a clear, unmoving risk boundary throughout the evaluation, and is generally described as the more flexible, more manageable option for traders because "it doesn't move, no matter how much you profit". **Trailing drawdown** ratchets upward as account equity reaches new highs, permanently locking in a portion of gained equity as the new floor, but never relaxes downward during a losing stretch — one source frames this plainly: "trailing drawdown is one of the main weapons of a prop firm against you as a trader. Your real account size is your trailing drawdown".[^14][^15][^16][^17][^18]

The practical trading implication is significant: trailing drawdown "tightens your risk" specifically as a strategy becomes profitable, since the maximum allowable equity retracement shrinks in absolute terms even as the account grows, making trailing drawdown "restrictive" for exactly the accounts that are succeeding. Static drawdown is generally recommended as better suited to strategies with longer holding periods or larger natural equity swings (e.g., swing trading), while trailing drawdown is described as fitting shorter-duration, scalping-style trading better, since it more tightly polices moment-to-moment equity retracement. Kraken Prop's confirmed use of a static MDD (Report 1) is therefore a structurally favorable design for the questionnaire's intraday-but-not-scalping strategy family — it does not punish the account for giving back a portion of unrealized gains during normal equity fluctuation the way a trailing structure would, which somewhat reduces the urgency (though not the prudence) of the questionnaire's H.127 "ratchet, give back at most half the day's gain" daily-profit-protection rule, since that specific mechanic exists to manage the daily MDL reset (which does behave in a trailing-like fashion day-to-day) rather than the lifetime MDD.[^16][^17]

## 5. Drawdown-sensitive sizing ladders

Beyond Kelly, several sources describe simple, rule-based drawdown ladders as a practical, auditable alternative to continuous formula-based sizing — directly matching the questionnaire's H.106 preference for fixed tiers over a continuous formula. One representative example ladder: reduce position size by 30% at 5% drawdown, by 50% at 8% drawdown, and stop trading entirely for review at 10% drawdown, describing this as "the exact system funds use". A separate, complementary rule specifically targets consecutive-loss-triggered de-risking: cut risk by 50% after 3 consecutive losses, returning to normal risk only after the account returns to breakeven — explicitly framed as protecting the account "when you're out of sync with the market" rather than assuming any specific number of losses proves the edge itself has failed. Both of these general-purpose ladder designs are directionally consistent with, though less granular than, the questionnaire's own already-specified ladder (H.106: 0.15% → 0.10% at −2% from high-water → 0.05% at −4% → halt at internal soft limit; H.124: 3 losses → cooldown, 4 → risk-tier-down, 5 → done for the day).[^19]

One important caution surfaced across multiple sources: increasing size after profits should only ever occur relative to a **new equity high**, never as a reaction to a short winning streak that has not yet produced a durable new high-water mark, since "big size + bad accuracy = account damage" is the standard failure mode being guarded against. This directly reinforces the questionnaire's H.105 hard rule against automatic risk increase from profits, and adds a specific refinement: even the eventual, human-reviewed step-up in risk tier should be gated on a genuine new equity high rather than any shorter-term winning-streak signal.[^19]

## 6. Base-rate reality: prop firm pass rates

Industry-wide pass-rate statistics give essential context for calibrating the questionnaire's own probability targets against real-world base rates, though these figures should be treated with appropriate skepticism given inconsistent public reporting across firms. Aggregated figures across multiple retail-facing sources converge on a **5–15% first-attempt pass rate** for typical prop-firm evaluations, with one source citing FTMO specifically as "the most transparent source on its own statistics page" and treating the 8–15% range as a reasonable industry cluster for two-phase evaluations. A separate source states flatly that "roughly 90% of people who buy a prop firm challenge fail it", and another cites an 80% failure rate specifically within the first 30 days of an evaluation attempt. Beyond the initial pass, payout completion rates are dramatically lower still — one source states that even among traders who publicly post a passing certificate, 97% go on to blow the resulting funded account, and that only about 7% of all evaluation purchasers ever see any payout at all.[^20][^21][^22][^23][^24]

These figures should not be read uncritically as directly representative of Kraken Prop specifically, since methodologies, marketing incentives, and reporting transparency vary enormously across the cited sources, and none of them are Kraken-specific data. However, they establish an important calibration point: the questionnaire's own A.8 target of ≤2% monthly account-failure probability, if achieved, would represent a very substantially better survival profile than industry base rates suggest is typical — which is exactly consistent with the CTO's stated design philosophy (prioritizing account survival above evaluation-completion speed) and should be treated as an ambitious but directionally correct target rather than an unrealistically lax one. The stark payout-completion gap (pass rate vastly exceeding payout-completion rate) also reinforces the questionnaire's own emphasis on funded-account survival as a distinct, separately-simulated objective from evaluation completion (A.7, M.242) — the literature confirms this split is the single biggest determinant of whether "passing" translates into any actual realized value.

## 7. Synthesis for the risk kernel

Combining the above into concrete guidance for the questionnaire's Risk Kernel Prop Extension document: the exponential relationship between position size and risk of ruin justifies the conservative early-live risk ramp quantitatively, not just qualitatively; quarter-Kelly is the practitioner-standard sizing ceiling and should be treated as a hard cap that the deterministic ATR-based sizing formula never exceeds, consistent with tradekit's existing design; Kelly inputs require ≥50 trades (not merely ≥30) before being trusted for anything beyond a directional sanity check, arguing for a staged trust model where the 30-trade DSR gate governs whether a strategy trades live at all, while a separate, later 50–100 trade threshold governs whether its Kelly-derived sizing inputs are trusted over the fixed conservative default; Kraken Prop's confirmed static (non-trailing) MDD structure is more forgiving of normal equity fluctuation than a trailing structure would be, meaning the account's real defensive burden falls more heavily on the daily MDL management (via H.122-131's ladder) than on lifetime MDD management; and the industry base-rate context confirms the questionnaire's ambitious but achievable target of dramatically outperforming typical prop-trader survival statistics through exactly the discipline the CTO has already specified — conservative sizing, fixed tiers over continuous formulas, no profit-driven risk escalation, and separate simulation of evaluation-passing versus funded-account-survival objectives.

---

## References

1. [Minimizing Your Risk Of Ruin](https://www3.gmu.edu/schools/vse/seor/studentprojects/graduate/2009Fall/ISG/Investment_Optimization/Resources_files/Risk_of_ruin.pdf) - For fixed fractional position size, the risk of ruin equation is: R = e^((-2*a/d)*(ln(1-z)/ln(1-d)))...

2. [The risk of ruin applied to risk management in trading](https://www.forex-central.net/risk-of-ruin-risk-management.php) - There is a formula for calculating your risk of ruin, and ideally your risk of ruin should be betwee...

3. [Risk of Ruin Calculator — Will Your Strategy Survive?](https://journalplus.co/tools/risk-of-ruin-calculator) - Risk of Ruin estimates the probability of losing a set percentage of your account. Formula: RoR = (L...

4. [The Risk of Ruin in Trading: Probability of Ruin and Loss ...](https://www.quantifiedstrategies.com/risk-of-ruin-in-trading/) - The risk of ruin is 13% if you risk 5,000 per trade, but is reduced to a negligible 0.0005% if you r...

5. [Calculating Risk of Ruin in Trading | James Hornick posted ...](https://www.linkedin.com/posts/jameshornick_what-if-i-told-you-there-was-a-way-to-calculate-activity-7404566268135137280-qvRO) - Risk of Ruin is the probability you'll lose your entire trading capital before your edge has time to...

6. [Kelly Criterion Explained: Smarter Position Sizing for Traders](https://www.tastylive.com/news-insights/kelly-criterion-explained-smarter-position-sizing-traders) - The Kelly criterion provides a mathematical framework for position sizing that balances growth poten...

7. [Kelly Criterion for Position Sizing Explained](https://journalplus.co/learn/guides/kelly-criterion-guide) - The Kelly Criterion gives you the mathematically optimal fraction of your account to risk on each tr...

8. [The Kelly Criterion: A retail trader's guide to position sizing](https://experts.deriv.com/insights/kelly-criterion-position-sizing) - The Kelly Criterion provides a framework for determining position size based on win rate and payoff ...

9. [Kelly Criterion for Stock Trading: Optimal Position Sizing](https://zerodha.com/varsity/chapter/kellys-criterion/) - Learn Kelly Criterion for stock trading - calculate optimal position size using win rate and risk/re...

10. [Simple Random Walk Absorbing Barriers](https://math.stackexchange.com/questions/2759862/simple-random-walk-absorbing-barriers) - I read upon Gambler’s Ruin problem and encountered this interesting question. Consider a simple rand...

11. [Random Walk Absorbing Barrier Sim Calculator](https://metricgate.com/docs/random-walk-absorbing-barrier/) - The gambler's ruin interpretation frames the random walk as a gambler who wins or loses one unit per...

12. [18MST24E: Stochastic Processes UNIT-II](https://gacbe.ac.in/pdf/ematerial/18MST24E-U2.pdf) - Random Walk Processes with two Absorbing Barriers: Suppose a Gamblers Ruin is with two adversaries w...

13. [[1301.2702] Extended gambler's ruin problem](https://arxiv.org/abs/1301.2702) - We obtain absorption probabilities, probabilities for maximum and minimum values of the ruin problem...

14. [Trailing Drawdown : r/Daytrading](https://www.reddit.com/r/Daytrading/comments/12lmnki/trailing_drawdown/) - Trailing drawdown is one of the main "weapons" of a prop firm against you as a trader. Your real acc...

15. [Static vs Trailing Drawdown: Which Risk Model Gives ...](https://www.linkedin.com/pulse/static-vs-trailing-drawdown-which-risk-model-gives-traders-14vxf) - A static drawdown stays fixed from the initial account balance. A trailing structure moves upward as...

16. [Static vs. Trailing Maximum Drawdown](https://theproptrade.com/blog-static-vs-trailing-drawdown/) - If you want more flexibility and control, static drawdown is the smarter choice. ✓ It gives you a fi...

17. [Static Drawdown vs Trailing Drawdown: A Complete Guide](https://www.defcofx.com/static-drawdown-vs-trailing-drawdown/) - Static is better for swing trading. Trailing fits well with scalping or short trades. Both types are...

18. [Trading Prop Firm: Static vs Trailing Drawdown](https://www.youtube.com/shorts/LVicHxxIxxM) - drawdown rules is one of the biggest advantages you can have before buying a prop firm challenge. co...

19. [How to Control Drawdown Using Dynamic Position Sizing](https://www.mql5.com/en/blogs/post/766052) - Dynamic sizing rule: After 3 consecutive losses, cut your risk by 50%. Example: Normal risk = 1% per...

20. [Passing a prop firm challenge is “easy”, but why is getting ...](https://www.reddit.com/r/Forex/comments/yedmeh/passing_a_prop_firm_challenge_is_easy_but_why_is/) - That's roughly a 99.9% fail rate if my math is correct.. This also shows that 97% people who post th...

21. [Prop Firm Evaluation Pass Rates: Statistics & Reality Check](https://damnpropfirms.com/trading-guides/prop-firm-evaluation-pass-rates-statistics-reality-check/) - Only 5% to 15% of traders pass their prop firm evaluations on the first try. Even fewer – just 7% – ...

22. [The Prop Firm Math No One Wants You to Do: Pass Rate × ...](https://www.mql5.com/en/blogs/post/770369) - the 8-15% range across two-phase evaluations. Pass rate assumed: 10% (the optimistic end of publicly...

23. [Prop Firm Challenge Failure Rate: 80% Fail—Here's Why](https://www.jptradingcapital.com/blog/en/prop-firm-challenge-failure-rate-statistics) - The prop firm challenge failure rate statistics show that approximately 80% of traders fail their ev...

24. [The Math Behind Prop Firm Failure: Why 90% Lose Evaluations](https://forexbroker500.com/why-prop-firm-traders-fail-math/) - roughly 90% of people who buy a prop firm challenge fail it. To pass, you need to make $10,000 using...

