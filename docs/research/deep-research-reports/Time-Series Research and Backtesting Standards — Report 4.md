# Time-Series Research and Backtesting Standards

## Overview

This report codifies the statistical machinery required to make backtest results trustworthy: bias taxonomy (lookahead, survivorship, data snooping), leakage-resistant cross-validation (purging, embargoing, combinatorial paths), walk-forward protocol design, event-based and triple-barrier labeling, multiple-hypothesis correction via the Deflated Sharpe Ratio and Probability of Backtest Overfitting, and Monte Carlo trade-sequence simulation. Every method here traces to Marcos López de Prado's "Advances in Financial Machine Learning" and the companion Bailey/López de Prado statistical papers, which form the dominant reference framework across both academic and practitioner sources reviewed.[^1][^2][^3][^4]

## 1. The bias taxonomy

Three biases dominate the literature on why backtests systematically overstate live performance. **Lookahead bias** occurs when a signal or feature uses information that would not actually have been knowable at decision time — described as "the most dangerous bias in the taxonomy because it can silently produce catastrophic distortions," since a single lookahead bug can inflate performance without any obvious symptom in the output. **Survivorship bias** arises when a backtest universe is built from currently-existing assets and projected backward, systematically excluding assets that failed, delisted, or were abandoned — this "flatters historical performance by excluding failures from the record". **Data snooping / overfitting** is the danger of testing many strategy variants against the same dataset until one appears profitable by chance — Bailey and López de Prado's guarantee that "a researcher will always find a misleadingly profitable strategy after a sufficient number of trials" is the central motivating fact behind the Deflated Sharpe Ratio machinery covered in Section 4.[^5][^6][^7][^8]

For this account's point-in-time semantics (questionnaire F.87–89), the direct implication is that every feature, indicator, and regime label must be computed only from data whose "knowable time" precedes the decision timestamp — exactly the discipline the questionnaire's swing-point k-bar delay convention already encodes, and exactly the discipline that must extend to any new indicator or ML feature introduced later.

## 2. Purging and embargoing

Standard k-fold cross-validation assumes independently and identically distributed observations; financial time series violate this assumption because adjacent observations are serially correlated, and because labels are frequently constructed by looking forward in time (e.g., "did price rise 3% within the next 10 bars"), which means a label near a train/test boundary can be built from data that spans into the other partition — leaking information across the split. **Purging** removes any training observations whose label-construction window overlaps with the test set's window, directly eliminating this specific leakage source. **Embargoing** adds a further buffer of excluded observations immediately after the test set, sized to exceed the data's serial-correlation decay length, preventing the training set from re-absorbing autocorrelated information that effectively "already saw" the test outcome. One practitioner's rule of thumb: purge width should be at least as long as the autocorrelation decay observed in the specific data being used, rather than a fixed constant applied across all assets or timeframes.[^9][^10][^11][^12][^13][^1]

**Combinatorial Purged Cross-Validation (CPCV)** extends this further by generating multiple train/test split combinations from N data groups, producing several independent backtest "paths" from the same dataset rather than a single train/test split, which gives a distribution of out-of-sample performance rather than one point estimate. This directly satisfies the questionnaire's L.216 requirement ("purged and embargoed cross-validation") and should be the standard applied whenever an ML filter model (per E.208's meta-labeling design) is trained and evaluated.[^14][^9]

## 3. Walk-forward testing: anchored vs. rolling

Walk-forward validation slices the full historical dataset into sequential windows, optimizes strategy parameters only on each window's in-sample portion, locks those parameters, and evaluates purely out-of-sample on the following segment before sliding forward — the out-of-sample slices are then stitched end-to-end into a single composite equity curve, in which "every bar is genuine out-of-sample". This is described as "the gold standard for testing whether a strategy will work going forward" and "the closest thing in quantitative research to a fair, repeated experiment".[^13][^15]

**Anchored** walk-forward keeps the training window's start date fixed and only extends its end date forward with each step, so every subsequent training set is a strict superset of the previous one. **Rolling** walk-forward keeps the training window a fixed length and slides both start and end dates forward together, discarding the oldest data as new data is added. One source notes rolling windows "generally prove more realistic" for markets whose underlying dynamics genuinely change over time, since anchored windows increasingly dilute recent regime information with an ever-larger pool of old data — this is a direct tension with the questionnaire's M.235 choice of anchored walk-forward as primary. Given the account's cross-regime requirement (spanning 2020 crash through 2025–26 recovery per M.231–233), a **hybrid recommendation** is to run anchored walk-forward as the primary protocol (per the existing decision) but also report the rolling-window composite Sharpe as a diagnostic — a large gap between the two indicates the strategy's edge is regime-specific rather than durable, which is valuable information the anchored-only approach alone would not surface.[^15][^16][^13]

Key diagnostics recommended for interpreting walk-forward output: the **decay ratio** (composite out-of-sample Sharpe divided by average in-sample Sharpe — a ratio near 1.0 means no decay, 0.6–0.8 is considered healthy, below 0.5 signals significant overfitting); **parameter stability** across folds, where wildly drifting optimal parameters across folds indicates the optimization is fitting noise rather than a stable edge; and **per-fold variance**, since an average that blends several profitable folds with one catastrophic fold is a misleading headline number and should be reported alongside the average rather than instead of it.[^15]

A practical heuristic for controlling overfitting risk during window selection: keep the number of free/tunable parameters below the square root of the training window's observation count, since a strategy with 20 tunable parameters trained on only 500 observations is "almost certainly overfitting in-sample". This gives a concrete, checkable bound the CTO's E.63–64 "globally shared parameters" preference should be measured against quantitatively, not just qualitatively.[^13]

## 4. Triple-barrier labeling and event-based sampling

The triple-barrier method labels each trading opportunity by which of three boundaries is touched first: an upper barrier (profit-take), a lower barrier (stop-loss), or a vertical barrier (a fixed time horizon), with the label set according to whichever boundary is hit first. Barriers are typically set dynamically as a function of estimated volatility (e.g., an EWMA of recent returns) rather than as fixed percentages, so the label definition adapts to the asset's current volatility regime rather than using a one-size-fits-all threshold. This maps directly and almost exactly onto tradekit's existing thesis-grading behavior described in the questionnaire (L.215: "stop-wins-on-ambiguous-bar, horizon-expiry=FAIL") — the account's existing infrastructure already implements the academically standard labeling approach, which is a meaningful validation of the existing design rather than a new requirement.[^17][^18][^19]

**Event-based sampling**, as opposed to sampling at every fixed time interval, uses a filter (commonly the symmetric CUSUM filter) to select only the bars where a meaningful, statistically significant price move has occurred, reducing the number of low-information, redundant observations fed into any labeling or training pipeline. This is directly relevant to Report 6's CUSUM-based regime change-point detection and to controlling label count for any ML filter model — sampling only genuine "events" rather than every bar reduces both computational load and the overlapping-label leakage problem described next.[^19]

**Overlapping-label leakage** is a specific instance of the general leakage problem: because triple-barrier labels look forward across a multi-bar window, adjacent labeled events frequently share overlapping outcome windows — this must be corrected either via the purge/embargo mechanism (Section 2) or via a specific overlap-weighting scheme, since standard cross-validation and sample-weighting assumptions (each observation contributes independent information) are violated when consecutive labels are built from heavily overlapping return paths. This directly answers the questionnaire's L.216 sub-question on overlapping-label leakage.[^12][^1]

## 5. Deflated Sharpe Ratio and Probability of Backtest Overfitting

The Deflated Sharpe Ratio (DSR), developed by Bailey and López de Prado, answers a precise question: given that N strategy configurations were tested and the best-performing one was selected, what is the probability that this selected strategy's Sharpe ratio reflects genuine skill rather than being the statistical artifact expected to emerge from testing that many configurations by chance alone? The DSR formula adjusts the observed Sharpe ratio downward by subtracting the expected maximum Sharpe ratio that would arise from pure noise given N trials, then further corrects for the sample's skewness and kurtosis (since real trading returns are rarely normally distributed) and for the finite sample length. A DSR above roughly 0.95 is typically treated as evidence the observed performance reflects genuine skill after accounting for all these effects; below that threshold, the result is treated as more likely a false positive. This directly validates and formalizes the n≥30 threshold and n_trials penalty mechanism the CTO describes as already built into tradekit's edge-verdict framework — the DSR is precisely the mathematical machinery underlying that gate.[^2][^20][^21][^22][^5]

The related **Probability of Backtest Overfitting (PBO)** metric, introduced in a companion paper by the same authors, uses a technique called Combinatorially Symmetric Cross-Validation (CSCV) to directly estimate the probability that a strategy selected as the best performer in-sample will underperform the median strategy out-of-sample. Where the DSR corrects a single strategy's Sharpe ratio for the number of trials, PBO more directly answers "how likely is it that the strategy I picked as the winner is actually a below-median performer once tested honestly" — the two metrics are complementary, and a rigorous validation standard should report both rather than treating them as interchangeable.[^3][^23][^24]

**Critical operational discipline underlying both metrics:** they only work if every trial is honestly recorded. As one source states plainly, "the key is to record all trials and determine correctly the clusters of effectively independent trials" — a research program that quietly discards failed parameter searches before computing DSR/PBO is defeating the entire purpose of the correction. This directly reinforces the CTO's own L.206 concern that novel-edge search "pays the n_trials selection penalty" and that "the experiment registry that feeds it honestly is open work and becomes MANDATORY the day we start searching" — the literature confirms this is not a nice-to-have but a load-bearing requirement for the whole validation framework to mean anything.[^5]

## 6. Monte Carlo trade-sequence simulation

Monte Carlo simulation in a trading context takes the set of trades produced by a single historical backtest and generates many alternative orderings and/or subsets of those same trades — commonly by randomly shuffling trade sequence, randomly skipping some trades, or bootstrap-resampling with replacement — to test whether the backtest's headline performance depended on the specific lucky ordering of trades that happened to occur historically, rather than reflecting a property that would hold under any plausible ordering. A commonly cited minimum is at least 1,000 simulation runs, with some sources recommending thousands more for a stable distribution estimate. Position sizing is generally held constant at whatever the original backtest used, since the goal is to isolate sequence-order risk specifically, not sizing risk.[^25][^26][^27][^28]

This method is what reveals "drawdowns, bust probability, and potential returns under different market sequences, position sizing, and leverage" beyond the single historical path, and is precisely the mechanism the questionnaire's M.241–244 already specifies (block-bootstrap resampling of trade order, ≥10,000 paths). The block-bootstrap refinement specified in the questionnaire (preserving short runs of serially correlated trades rather than shuffling every trade independently) is an important improvement over naive independent-trade resampling, since real trade outcomes are not independent — consecutive trades in the same regime tend to be correlated, and a naive shuffle would understate true sequence risk by breaking that correlation structure artificially.[^27]

## 7. Synthesis: a layered validation protocol

Combining the elements above into a single recommended validation sequence for any candidate strategy before live promotion:

1. **Design and label** using the triple-barrier method with volatility-scaled barriers and event-based (CUSUM-filtered) sampling, eliminating fixed-interval sampling redundancy.[^19]
2. **Cross-validate with purging and embargoing** (or full CPCV where computationally feasible) during any parameter search or ML model selection, never plain k-fold.[^11][^1][^9]
3. **Walk-forward test** using anchored windows as primary, with rolling-window composite Sharpe computed as a regime-sensitivity diagnostic; track decay ratio, parameter stability, and per-fold variance explicitly rather than reporting only an average.[^13][^15]
4. **Reserve one final, untouched holdout** used exactly once immediately before live promotion — consistent with the questionnaire's M.237 answer, and directly supported by the literature's caution that "iterated out of sample is not out of sample" once a researcher has seen and reacted to a supposed holdout more than once.[^4]
5. **Compute DSR and PBO** on the final candidate, honestly incorporating the full count of all trials/configurations tested during the research process, not just the winning configuration.[^2][^3][^5]
6. **Run Monte Carlo block-bootstrap simulation** (≥1,000, ideally the questionnaire's ≥10,000 paths) on the final candidate's realized trade sequence to establish a distribution of plausible outcomes rather than trusting the single historical path.[^28][^25][^27]
7. **Disqualify** any candidate that fails at any of these stages rather than iterating the model based on backtest results directly — the literature is explicit that "one should not adjust the model based on the backtest results since it is a waste of time and it is dangerous due to overfitting," and that a backtest's proper purpose "is to discard bad models, not to improve them".[^4]

This sequence directly operationalizes the questionnaire's Section M requirements and gives quantitative, checkable pass/fail criteria (DSR threshold, PBO threshold, decay ratio, parameter-count-to-observation-count ratio) that the Research and Validation Standard document can adopt without further derivation.

---

## References

1. [Enhancing Time Series Cross-Validation with Purging and ...](https://www.kaggle.com/competitions/optiver-trading-at-the-close/discussion/453128) - Enhancing Time Series Cross-Validation with Purging and Embargo Techniques 🛡️ ... Lopez de Prado in ...

2. [THE DEFLATED SHARPE RATIO](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) - by DH Bailey · Cited by 291 — The Probabilistic Sharpe Ratio (PSR), developed in Bailey and López de...

3. [The Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253) - by DH Bailey · 2015 · Cited by 316 — We propose a framework that estimates the probability of backte...

4. [8.3 The Dangers of Backtesting](https://portfoliooptimizationbook.com/book/8.3-dangers-backtesting.html) - by DP Palomar · Cited by 46 — Indeed, what makes backtest overfitting so hard to assess is that the ...

5. [Deflated Sharpe Ratio (how to avoid been fooled by ...](https://quantdare.com/deflated-sharpe-ratio-how-to-avoid-been-fooled-by-randomness/) - López de Prado and Bailey developed the Deflated Sharpe Ratio (DSR) that computes the probability th...

6. [Look-ahead Bias - Data Science & Machine Learning 101](https://bowtiedraptor.substack.com/p/look-ahead-bias) - Look-ahead bias is a cognitive bias that causes people to mistakenly believe that they have access t...

7. [A Taxonomy of Backtest Lies: Survival Bias, Lookahead Bias ...](https://www.susanpotter.net/quant/backtest-bias-taxonomy/) - Lookahead bias is the most dangerous bias in the taxonomy because it can silently produce catastroph...

8. [Point-in-Time Data: Critical for Investment Decisions](https://starqube.com/point-in-time-data/) - Using current index composition and projecting it backward introduces systematic survivorship bias t...

9. [What is Combinatorial Purged Cross-Validation for time ...](https://stats.stackexchange.com/questions/443159/what-is-combinatorial-purged-cross-validation-for-time-series-data) - I'm trying to understand the "Combinatorial Purged Cross-Validation" technique for time series data ...

10. [Cross Validation in Finance: Purging, Embargoing, ...](https://blog.quantinsti.com/cross-validation-embargo-purging-combinatorial/) - De Prado calls purging and embargoing. ed to it: a trade time and an event time. financial time seri...

11. [Combinatorial Purged Cross-Validation Explained](https://www.youtube.com/watch?v=hDQssGntmFA) - De Prado's work at all. Time series challenges in machine learning. Cross-Validation for Time Series...

12. [[D] Benefits of Purged CV in Time Series?](https://www.reddit.com/r/MachineLearning/comments/1j392dd/d_benefits_of_purged_cv_in_time_series/) - Purging and embargo aim to prevent information leakage between the train- and test-set, and they ser...

13. [Walk-Forward Optimization: Anchored vs. Rolling Windows ...](https://www.susanpotter.net/quant/walk-forward-optimization/) - Walk-forward validation has its own parameters: training window length, test window length, and step...

14. [Combinatorial Purged Cross-Validation Insights | PDF](https://www.scribd.com/document/725401650/SSRN-id4778909) - This research explores integrating machine learning into financial analytics. Prado's Combinatorial ...

15. [Walk-Forward Validation: Anchored vs Rolling](https://quanterlab.com/articles/foundations-walk-forward) - Walk-forward validation is the gold standard for forward-testing a strategy. How anchored and rollin...

16. [Walk-Forward Analysis vs. Backtesting: Pros, Cons, and ...](https://surmount.ai/walk-forward-analysis-vs-backtesting-pros-cons-best-practices) - Rolling windows generally prove more realistic than anchored approaches The right tools can signific...

17. [ML for Algotrading Pt 1: Intro to Labeling Financial Data with ...](https://www.youtube.com/watch?v=-Yxkd5WC_gg) - I'm going to be talking about the triple barrier method which is one way to label financial data.

18. [Quant Trading: Master Triple Barrier Method for Robust ML](https://xglamdring.com/what-is-the-triple-barrier-method-a-labeling-technique-to-prevent-overfitting-in-ml-based-quantitative-trading/) - Triple Barrier Method embeds risk management into data labeling to fix overfitting. Leakage & Overfi...

19. [Labeling Financial Data](https://risklab.ai/research/financial-data-science/labeling) - Dynamic Approaches: The Triple-Barrier Method ; Label 1: The upper barrier (profit-take) is hit firs...

20. [Deflated Sharpe ratio](https://en.wikipedia.org/wiki/Deflated_Sharpe_ratio) - The Deflated Sharpe ratio (DSR) is a statistical method used to determine whether the Sharpe ratio o...

21. [Deflating the Sharpe Ratio by asking for a Minimum Track ...](http://boston.qwafafew.org/wp-content/uploads/sites/4/2017/01/Lopez_de_Prado_Sharpe.pdf) - It deflates the skill measured on “well-behaved” investments (positive skewness, negative excess kur...

22. [Deflated Sharpe Ratio Explained (Algo Trading)](https://paperswithbacktest.com/course/deflated-sharpe-ratio) - The deflated Sharpe ratio (DSR) is a statistical test introduced by Bailey and Lopez de Prado (2014)...

23. [THE PROBABILITY OF BACKTEST OVERFITTING](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) - by DH Bailey · 2015 · Cited by 316 — For a given strategy, the probability of backtest overfitting (...

24. [Statistical Overfitting and Backtest Performance - SDM](https://sdm.lbl.gov/oapapers/ssrn-id2507040-bailey.pdf) - by DH Bailey · Cited by 21 — In the second study (Bailey et al. [2015]), a formula was derived for t...

25. [What is the Monte Carlo method used for in backtesting?](https://www.reddit.com/r/algotrading/comments/1i90odm/what_is_the_monte_carlo_method_used_for_in/) - Hi!

I asked as a response to a comment in another post, in this same sub-reddit, bay I had not reps...

26. [Monte Carlo Stress Testing for TradingView Backtests](https://www.backtestbase.com/education/monte-carlo-stress-testing) - Free Monte Carlo stress test for trading strategy backtests. Run 1000+ simulations to reveal true dr...

27. [Monte Carlo Simulation In Trading, Investing, and ...](https://www.quantifiedstrategies.com/monte-carlo-simulation-in-trading/) - Monte Carlo simulation and backtesting in trading (and investing) is a statistical tool to measure u...

28. [Monte Carlo Simulation for Trading | Why Backtest Isn't Enough?](https://www.youtube.com/watch?v=y-d5FtnAFnY) - Backtesting a strategy on historical data gives you just one possible outcome. But markets are unpre...

