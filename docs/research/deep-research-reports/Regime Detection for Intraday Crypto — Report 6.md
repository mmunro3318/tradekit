# Regime Detection for Intraday Crypto

## Overview

This report surveys the primary quantitative methods for classifying market regime — Hidden Markov Models, ADX, variance ratio tests, the Hurst exponent, realized volatility, and change-point detection — and addresses BTC-conditioned market-wide regime classification and the well-documented pitfall of regime overfitting. The evidence supports tradekit's existing three-state HMM (low_vol_trend / high_vol_chop / breakdown) as methodologically mainstream, while highlighting that deterministic indicator-based fallback rules (ADX, variance ratio, Hurst) remain essential complements rather than legacy alternatives, since they are more interpretable and less prone to the kind of unstable, hard-to-audit failure modes that afflict regime-fitting ML models specifically.

## 1. Hidden Markov Models

HMMs model market dynamics as a system transitioning between a small number of hidden (unobserved) states, each with characteristic return and volatility behavior, fitted via maximum-likelihood estimation and the Baum-Welch algorithm from observed returns data. A practitioner walkthrough applying HMMs to trading demonstrates the standard workflow: fit an HMM with a fixed number of states (commonly two, often corresponding to low-volatility and high-volatility regimes) on historical returns, use the fitted model to predict tomorrow's regime probability, and route signal generation through regime-specific specialist models trained only on data from within each detected regime. Academic literature specific to cryptocurrency markets confirms HMMs are an active, current research area for crypto regime detection, with recent work combining HMMs with reinforcement learning to outperform baseline models on Sharpe ratio and risk-adjusted return metrics.[^1][^2][^3][^4][^5]

Critical calibration considerations from the sourced material: the number of hidden states must be deliberately chosen rather than assumed, since too many states risks each regime having too little data to characterize reliably, while too few states may blend genuinely distinct market conditions together. Cross-validation of the fitted regime assignments against known market events is recommended practice, not merely fitting the maximum-likelihood model and trusting its labels blindly. This directly supports the questionnaire's G.91 decision to start with tradekit's existing three-state model (low_vol_trend / high_vol_chop / breakdown) rather than immediately expanding to the full nine-state target vocabulary — the literature's caution about state-count calibration argues for validating the current three states thoroughly on live trade data before adding further granularity, exactly as the CTO already concluded ("don't fragment into 9 states before we have trades to validate 4").[^6][^3]

## 2. ADX (Average Directional Index)

ADX is a non-directional 0–100 indicator measuring trend strength regardless of direction, derived from the directional movement indicators (+DI, −DI) and the Average True Range, originally developed by J. Welles Wilder. Threshold interpretation is broadly consistent across every source reviewed, converging on a clear tiered structure: below 20 indicates a weak or trendless market where trend-following strategies are likely to underperform; 20–25 is a neutral/forming zone lacking confirmation; above 25 is the standard, most widely cited confirmation threshold for a genuine trend, considered the ideal zone for trend-following entries; above 40–50 indicates a very strong trend that may be approaching exhaustion, with a subsequent declining ADX slope signaling the trend is losing momentum. One source frames the level-25 threshold explicitly as "the gatekeeper of your capital", and another explicitly warns that "below 25 indicates a ranging or non-trending market where breakout and trend strategies typically fail" — directly validating the necessity of exactly the kind of regime-gated prohibition the questionnaire's E.61 requires for every strategy.[^7][^8][^9][^10][^11]

This gives a clean, well-established, and low-complexity deterministic fallback rule: **ADX above 25 as a minimum trend-strength gate before allowing any pullback-continuation or breakout entry**, fully consistent with tradekit's existing vol-percentile/ADX-grid fallback described in the questionnaire's G.93 answer.

## 3. Variance ratio test

The variance ratio test, developed by Lo and MacKinlay, tests the random-walk hypothesis by comparing the variance of k-period returns to k times the variance of one-period returns — under a true random walk, this ratio should equal exactly 1, since returns compound additively with no serial dependence; a ratio significantly above 1 indicates positive serial correlation (trending/momentum behavior), while a ratio significantly below 1 indicates negative serial correlation (mean-reverting behavior). The test produces a standardized z-statistic allowing formal hypothesis testing of whether the departure from a ratio of 1 is statistically significant rather than a chance sampling artifact.[^12][^13][^14][^15]

This gives a formal, statistically rigorous complement to the more heuristic ADX and ML-based approaches — rather than simply labeling a period "trending" or "ranging" based on a threshold crossing, the variance ratio test provides an actual significance test with a p-value, directly useful for the questionnaire's G.95 regime-confidence requirement. One practical caution surfaced during research: results from the variance ratio test and the (unit-root-testing) Augmented Dickey-Fuller test can disagree on the same series, since they test related but distinct null hypotheses — this argues for treating the variance ratio as one input among several rather than a sole arbiter of regime state.[^16]

## 4. Hurst exponent

The Hurst exponent H is a single scalar summarizing long-term persistence in a time series, classically estimated via Rescaled Range (R/S) analysis: dividing the series into sub-windows of varying length, computing the rescaled range (cumulative deviation range divided by standard deviation) for each window size, then taking the slope of log(rescaled range) against log(window size) as the estimate of H. Interpretation is consistent across sources: H greater than 0.5 indicates a persistent, trending series where past movements tend to continue; H less than 0.5 indicates an anti-persistent, mean-reverting series; H at or near 0.5 indicates behavior indistinguishable from a random walk over the sample measured. One practitioner comparison notes the Hurst exponent is "a more nuanced tool compared to EMA slopes or the Kaufman's Efficiency Ratio, as it quantifies the degree of mean reversion or trend" rather than merely detecting its presence or absence — meaning H provides a continuous, gradated regime-strength measure rather than the simple threshold crossing that ADX provides, complementary to rather than redundant with it.[^17][^18][^19][^20][^21]

An important caveat carried across multiple Hurst-exponent sources: the estimate is sample-length and estimation-method sensitive (R/S, detrended fluctuation analysis, periodogram regression, and wavelet methods can each produce somewhat different H estimates on the same data), meaning the specific numeric H value should be treated as informative about the general character of a regime rather than as a precisely calibrated, single-decimal threshold.[^18]

## 5. Realized volatility and entropy

Realized volatility (typically computed as the sum of squared high-frequency returns over a rolling window) is the most direct, model-free measure of how much price movement has actually occurred, and forms the foundation for volatility-regime classification independent of any directional trend/range distinction — it answers "how much is the market moving" as a distinct question from "which direction, if any." The questionnaire's own G.100 answer (halt altcoin entries when BTC realized volatility exceeds a percentile threshold) already positions realized volatility as the primary market-wide risk-off trigger, which this research supports as a standard, well-understood, and computationally simple choice relative to the more exotic entropy-based measures. Entropy-based liquidity/regime measures were referenced in the questionnaire's own research scope but no crypto-specific empirical validation of entropy as a regime feature was surfaced in this research pass — this should be treated as an open research item rather than an established, ready-to-implement method, in contrast to the well-validated ADX, variance ratio, Hurst, and HMM approaches above.

## 6. Change-point detection (CUSUM and related)

CUSUM (cumulative sum) change-point detection identifies shifts in a time series' mean by accumulating standardized deviations from an estimated baseline mean and flagging a change point once the cumulative sum exceeds a pre-defined threshold — critically, this is described as "an 'online' algorithm," meaning it can run on a live data stream continuously rather than requiring the full dataset in advance, which is directly relevant for live regime-transition detection rather than only offline backtesting analysis. A companion academic framing formalizes this using a two-sample mean comparison statistic evaluated at every candidate split point τ, comparing the empirical mean before and after τ, with a change declared when the resulting standardized statistic exceeds a suitably chosen threshold. More flexible extensions include binary segmentation (recursively applying CUSUM to detect multiple change points across a series, not just one) and the PELT (Pruned Exact Linear Time) algorithm for efficient multi-change-point detection at scale.[^22][^23][^24]

This directly satisfies the questionnaire's N.264 requirement (CUSUM for change-point detection of edge decay) and G.96's regime-transition handling — the online property of CUSUM specifically supports the questionnaire's design of suppressing new entries for N bars following a detected transition, since the algorithm is designed to flag the transition moment itself in real time rather than only in retrospective analysis.

## 7. BTC market-wide conditioning

No independent academic literature specific to BTC-as-market-factor conditioning for altcoin trading strategies was surfaced in this research pass beyond the general microstructure findings already covered in Report 2 (BTC leading ETH price adjustment, and the well-established fact that crypto asset correlations approach 1 during stress, as the CTO's questionnaire answer to D.53 already states). This is consistent with — but does not independently validate beyond — the questionnaire's own G.98–100 design (BTC regime constrains alt trades; halt alt entries when BTC realized volatility exceeds a percentile threshold). This is flagged as a residual open item: the specific threshold calibration for the BTC-volatility altcoin-halt trigger should be derived empirically from the account's own collected data (per F.83's tick-data collection already underway) rather than borrowed from any external published threshold, since no crypto-specific published calibration was found.

## 8. Pitfalls of regime overfitting

This is the single most operationally important finding in this report, and it directly contradicts a natural intuition that more regime-model sophistication is always better. A practitioner discussion of exactly this failure mode is instructive: a trader who fine-tuned a market-regime filter reported that small parameter adjustments produced wildly different backtest results, and received the following diagnosis — "a strategy should work +/- indifferent with small incremental adjustment of the values. If you are getting wildly different results, it likely indicates it's not gonna stand the test of time". This is a direct, practical restatement of Report 4's parameter-stability diagnostic (wildly drifting optimal parameters across folds signals overfitting to noise, not a stable edge) applied specifically to regime-filter tuning.[^25]

The same discussion offers two concrete, actionable mitigations directly relevant to this account's design. First, regime-filter parameters should be selected from a heatmap of nearby parameter values showing **consistent** results across a neighborhood, never a single sharply-peaked optimum — "after optimization, market regime filter can be added without forcing its parameter; its parameter should be picked on heatmap, which parameter area can show consistent results". This directly reinforces Report 4's parameter-perturbation stress test (±20% on every parameter) and gives a specific, visual diagnostic technique (heatmap inspection) for applying it to regime thresholds specifically. Second, and more structurally, the discussion recommends testing the regime filter's true out-of-sample robustness by deliberately reserving an *earlier* period as the genuine holdout rather than the most recent period — "you shouldn't be backtesting on 2018-2024; you should be backtesting on 2016-2022, and then try out different strategies on that range... once you have picked your best strategy, then and only then would you test it on the 2022-2024 period" — explicitly framed as "guaranteed to make sure you don't overfit to your test set". This is functionally identical to the questionnaire's own M.237 single-use holdout requirement, reinforcing that regime-filter development must respect the same holdout discipline as strategy development itself, not receive an exemption as "just infrastructure."[^25]

A further, more general overfitting caution applicable to any regime-classification component: overfitting "occurs when a system learns from noise rather than the true market structure," and its signature failure mode is producing an artificially clean backtest that "collapses" once live-forward data — which the model never saw during fitting — begins arriving. Combined with the earlier finding that regime-fitting ML models (HMMs specifically) benefit from cross-validating regime assignments against known market events rather than trusting maximum-likelihood labels blindly, the overall picture argues strongly for treating the ML-based HMM regime classifier and the deterministic ADX/variance-ratio/Hurst fallback as permanently coexisting checks on each other, rather than treating the deterministic rules as a temporary bridge to be retired once the HMM matures — consistent with, and now further justified by, the questionnaire's own G.93–94 design decision to keep both permanently in place.[^3][^26]

## Synthesis for regime architecture

Combining these findings into concrete guidance: ADX above 25 is a well-established, near-universal deterministic trend-confirmation threshold and should anchor the fallback rules layer; the variance ratio test provides a formal significance test that can quantify regime confidence (satisfying G.95) in a way ADX alone cannot; the Hurst exponent adds a continuous, gradated persistence measure complementary to ADX's binary-ish threshold behavior; CUSUM's online property makes it the correct tool for live regime-transition flagging (G.96) and strategy-level edge-decay monitoring (N.264) simultaneously, since both are fundamentally the same statistical problem (detecting a mean/distribution shift in a live stream) applied at different levels of the system; and the regime-overfitting literature's heatmap-based parameter selection and out-of-order holdout discipline should be adopted as a mandatory, explicit step in validating any regime-model change, exactly mirroring the strategy-validation discipline already specified in Report 4 and the questionnaire's Section M.

---

## References

1. [Market Regime Detection using Hidden Markov Models in ...](https://www.quantstart.com/articles/market-regime-detection-using-hidden-markov-models-in-qstrader/) - Fitting a Hidden Markov Model to the returns data allows prediction of new regime states, which can ...

2. [Market Regime using Hidden Markov Model](https://blog.quantinsti.com/regime-adaptive-trading-python/) - This project builds a Python-based adaptive trading strategy that: Detects current market regime usi...

3. [Market Regime Detection Using Hidden Markov Models](https://questdb.com/glossary/market-regime-detection-using-hidden-markov-models/) - Hidden Markov Models detect market regimes by modeling hidden states and transitions, identifying vo...

4. [HMM-Based Market Regime Detection with RL for Portfolio ...](https://www.cloud-conf.net/datasec/2025/proceedings/pdfs/IDS2025-3SVVEmiJ6JbFRviTl4Otnv/966100a067/966100a067.pdf) - by J Ndoutoumou · Cited by 2 — This paper studies the impact of combining a Hidden Markov Model (HMM...

5. [Markov and Hidden Markov Models for Regime Detection ...](https://www.preprints.org/manuscript/202603.0831) - by H Malekinezhad · 2026 — This study investigates the application of Markov and Hidden Markov Model...

6. [Market Regime Identification Using Hidden Markov Model](https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID3406068_code3576909.pdf?abstractid=3406068&mirid=1) - The aim of this project is to construct the regime switching model, and figure out how many states s...

7. [ADX Explained: How to Measure and Trade Trend Strength](https://www.investopedia.com/articles/trading/07/adx-trend-indicator.asp) - The average directional index (ADX) measures trend strength and ranges from 0 to 100, with readings ...

8. [ADX Trend Strength Threshold Rules](https://sites.google.com/view/indicatorsoftrades/adx-trend-strength-threshold-rules) - Instead of just looking at whether the ADX is rising or falling, traders use defined thresholds to g...

9. [ADX 25+: The One Filter That Kills Bad Trades 🚫](https://fxnx.com/en/blog/adx-strategy-efficiency-filter-measure-trend-strength-like) - Above 40 indicates a very strong trend (often near exhaustion), and readings above 60 are rare and u...

10. [ADX Indicator: Measuring Trend Strength Like a Pro](https://www.chartguys.com/articles/adx-indicator) - The ADX measures trend strength on a scale from 0 to 100, ADX readings below 20 signal weak or absen...

11. [How traders use the ADX indicator to identify strong trends](https://www.equiti.com/sc-en/news/trading-ideas/adx-indicator-definition-use-and-characteristics/) - The ADX is plotted on a scale from 0 to 100, with values generally divided into thresholds that defi...

12. [Market Efficiency: Testing Random Walk by the Runs ...](https://iknowfirst.com/market-efficiency-testing-random-walk-by-the-runs-test-and-the-variance-ratio-test) - The Variance Ratio test has been developed by Lo and MacKinlay and it checks Random Walks by analyzi...

13. [VARIANCE RATIOS TEST](https://nb.vse.cz/~arlt/publik/AA_VR_00.pdf) - by J Arlt · Cited by 3 — Therefore, the acceptability of the random walk model can be checked by com...

14. [vratiotest - Variance ratio test for random walk - MATLAB](https://www.mathworks.com/help/econ/vratiotest.html) - This MATLAB function returns the rejection decision from conducting the variance ratio test for asse...

15. [Do stock returns follow random walks? - Variance ratio test ...](https://www.youtube.com/watch?v=LZHQdcaC964) - Do stock returns follow random walks? One of the clever statistical procedures - the variance ratio ...

16. [Variance ratio test and ADF test for random walk](https://quant.stackexchange.com/questions/63226/variance-ratio-test-and-adf-test-for-random-walk) - I am trying to use both ADF test and variance ratio test for random walk. However, the ADF test tell...

17. [Detecting trends and mean reversion with the Hurst exponent](https://macrosynergy.com/research/detecting-trends-and-mean-reversion-with-the-hurst-exponent/) - The Hurst exponent is a single scalar value that indicates if a time series is purely random, trendi...

18. [Hurst Exponent Explained: Formula, R/S, Examples](https://fractalcycles.com/guides/hurst-exponent-explained) - Hurst exponent (coefficient, index, parameter) explained: R/S calculation step by step, interpret va...

19. [Rescaled Range Analysis: A Method for Detecting ...](https://rpc.cfainstitute.org/blogs/enterprising-investor/2013/rescaled-range-analysis-a-method-for-detecting-persistence-randomness-or-mean-reversion-in-financial-markets) - A Hurst exponent ranges between 0 and 1, and measures three types of trends in a time series: persis...

20. [Hurst Exponent: Calculation, Values and More](https://blog.quantinsti.com/hurst-exponent/) - This comprehensive article gives you an insight into the Hurst Exponent and shows you how to calcula...

21. [Hurst Exponent. : r/algotrading](https://www.reddit.com/r/algotrading/comments/18lzvas/hurst_exponent/) - The Hurst Exponent is indeed a more nuanced tool compared to EMA slopes s Efficiency Ratio, as it qu...

22. [Probabilistic CUSUM for change point detection](https://sarem-seitz.com/posts/probabilistic-cusum-for-change-point-detection.html) - In summary, CUSUM detects shifts in the mean of a time-series that is stationary between two changep...

23. [Change Point Detection Calculator](https://metricgate.com/docs/change-point-detection/) - Detect change points in time series to identify structural breaks and regime shifts. Apply CUSUM, PE...

24. [1 An Introduction to Changepoint Detection](https://www.lancaster.ac.uk/~romano/teaching/2425MATH337/1_intro_cusum.html) - Changepoints are sudden, and often unexpected, shifts in the behavior of a process. They are also kn...

25. [market regime fine tuning leads to overfitting : r/algotrading](https://www.reddit.com/r/algotrading/comments/1bzzimj/market_regime_fine_tuning_leads_to_overfitting/) - STDEV of ATR can help reducing the losing trades, when the STDDEV is declining, indicating a narrowi...

26. [Overfitting in Trading Models: Examples, Risks, and ...](https://arongroups.co/forex-articles/overfitting-in-trading/) - Overfitting occurs when a system learns from noise rather than the true market structure. deep drawd...

