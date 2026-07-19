# Evidence Review of Intraday Crypto Strategy Families

## Overview

This report compares nine candidate strategy families against the evidence available for cryptocurrency markets specifically, evaluating each on proposed mechanism, empirical support, appropriate regime, data requirements, and suitability for a $5,000 intraday prop account. The strongest, most consistently replicated evidence across independent academic sources supports **time-series momentum/trend-following** and **pullback-continuation within an established trend** as the two most defensible starting points; mean-reversion carries real but more fragile and regime-dependent support; order-flow and open-interest methods are directionally sound in theory but require data and infrastructure this account does not yet have.

## 1. Time-series momentum / trend-following

**Mechanism:** Prior returns predict future returns in the same direction, commonly attributed to investor underreaction, late-informed-investor dynamics, and slow information diffusion. **Evidence:** This is the single best-supported strategy family for crypto in the sources reviewed. A recent multi-horizon EMA-based study across eight major cryptocurrencies from January 2020 to October 2025 found time-series momentum delivered 31.96% annualized returns versus 14.59% for cross-sectional momentum, with more than double the Sharpe ratio, and concluded the effect "remains economically meaningful in digital asset markets" over that sample. This is corroborated by an independent study finding "evidence of time-series momentum is strong, whereas evidence of cross-sectional momentum is almost non-existent," while cautioning that after accounting for transaction costs and daily price fluctuations, many naively-constructed momentum portfolios saw their statistically significant returns become economically insignificant — a direct warning that gross backtest returns overstate net-of-cost performance. **Regime:** Requires trending conditions; explicitly fails in range-bound/choppy regimes. **Data:** OHLCV only; no order-book or on-chain data required. **Holding time:** Typically multi-day to multi-week in the cited studies, longer than this account's 15m-entry/1h-4h-context design — the evidence base is strongest at daily-or-longer horizons and must be adapted carefully to intraday timeframes. **Cost sensitivity:** High — the Han (2023) finding that costs erase much of the raw effect is the single most important caution for a small account paying real spread and fees on every entry. **Suitability:** Good mechanism fit, moderate turnover, requires disciplined cost accounting; a strong candidate for the intraday adaptation the questionnaire specifies (4h trend context).[^1][^2][^3][^4][^5]

## 2. Breakout / volatility expansion

**Mechanism:** Price breaking through a defined resistance or volatility band signals the start of a new directional move as previously sidelined participants are forced to react. **Evidence:** Mixed and highly execution-dependent. One retail backtest of a Bollinger Band breakout-plus-squeeze strategy on ETH/USDT over 6 months found a 33.3% win rate (only 7 of 21 trades won) despite an eye-catching headline Sharpe, illustrating that breakout strategies frequently show positive expectancy built on a low win rate and a small number of large winners rather than consistent edge — a distribution that is fragile to sample size and prone to overfitting a short backtest window. The same source explicitly recommends volume confirmation and a volatility-regime filter (trade only when band width is above its rolling average) as necessary refinements, not optional enhancements. Practitioner guidance from FX-adjacent sources converges on requiring a volume or momentum confirmation alongside the price break itself, since unconfirmed breakouts fail at a documented higher rate than confirmed ones, particularly on weekends per Report 2's findings. **Regime:** Volatility expansion / regime transition specifically; the CTO's own framing of this as a "sibling" to pullback-continuation is consistent with the evidence, since both fire off the same underlying trend-context read but at different points in the cycle. **Suitability:** Reasonable as a secondary setup within the same family, but the low-win-rate/high-payoff distribution demands strict cost discipline and a larger sample before trusting any backtest Sharpe figure at face value — directly reinforcing the questionnaire's own M.257 disqualifier for profits concentrated in very few trades.[^6][^7]

## 3. Pullback continuation within trend

**Mechanism:** After an established trend, price temporarily retraces before resuming; entering on the retracement offers a favorable price relative to the trend's overall trajectory, typically confirmed via multi-timeframe alignment (higher timeframe for direction, lower timeframe for entry timing). **Evidence:** This is a widely practiced, mechanistically intuitive setup with consistent qualitative description across independent trading-education sources, though the specific sources reviewed are practitioner-level rather than peer-reviewed academic studies — a notable gap relative to the momentum literature. The core structural claim (multi-timeframe trend identification, then lower-timeframe entry on retracement, often paired with an oscillator like RSI to identify retracement exhaustion) appears consistently across three independent sources describing effectively the same architecture the CTO already selected: higher-timeframe trend filter (in one example a daily 72-EMA), intermediate-timeframe exhaustion signal (H4 RSI), and lower-timeframe execution trigger (M15 reversal signal). This maps almost exactly onto the questionnaire's chosen 4h/1h/15m structure. **Regime:** Trending only; explicitly prohibited in range/chop, consistent with E.61's mandatory prohibited-regime declaration. **Data:** OHLCV plus a trend/exhaustion indicator; no exotic data required. **Suitability:** Best evidence-to-complexity ratio of any family reviewed for this account's specific timeframe structure, though the absence of rigorous, cost-adjusted academic backtests (as exist for time-series momentum) means the strategy's edge must be established through the account's own R4/M validation process rather than borrowed confidence from the literature.[^8][^9][^10][^11]

## 4. Mean-reversion

**Mechanism:** Prices that have moved unusually far from a reference level (moving average, band, or recent extreme) tend to revert toward that level. **Evidence:** Genuinely mixed and regime-conditional. One Gibbs-sampling-based academic study found evidence of "mean aversion" (the opposite of mean reversion) for multi-period Bitcoin returns, directly contradicting the mean-reversion premise at the horizons studied. A separate empirical analysis of BTC price extremes found a more nuanced pattern: price sitting at a local maximum tends to keep trending upward (momentum, not reversion), while price at a local minimum tends to bounce back (reversion) — meaning mean-reversion behavior in BTC appears asymmetric and concentrated specifically around downside extremes rather than existing symmetrically at both tails, and works best with short lookback windows (10–20 days outperformed 40–50 day windows in the cited study). Separately, intraday-specific research found "both intraday momentum and reversal" present in BTC and other major coins, with the specific pattern shifting around large price jumps, macro announcements, and low-liquidity conditions — meaning a mean-reversion signal that ignores these conditioning variables is likely to be unstable. **Suitability:** The CTO's own decision to deprioritize mean-reversion (E.56, calling it "a fee-and-tail-risk grinder for small accounts") is well-supported by this asymmetric and condition-dependent evidence — a pure mean-reversion strategy is a weaker starting candidate than trend-following or pullback-continuation, though a downside-only reversion overlay conditioned on macro/liquidity state could be a defensible later research track.[^12][^2][^3][^13]

## 5. Range trading

**Mechanism:** In the absence of a clear trend, price oscillates between defined support and resistance boundaries; the strategy buys near support and sells near resistance. This is mechanically a bounded special case of mean-reversion and inherits the same asymmetric-evidence caveat above — no independent evidence source specific to crypto range trading (as distinct from general mean-reversion) was found in this research pass. **Suitability:** Not independently validated beyond the general mean-reversion literature; given the account's decision to prohibit trend strategies from firing in range/chop regimes (E.61), a dedicated range strategy is a plausible regime-routing complement but should inherit the same skepticism applied to mean-reversion above rather than be treated as a separately-validated family.

## 6. Order-flow imbalance

**Mechanism:** The net difference between buy-initiated and sell-initiated volume at the book level signals short-term directional pressure; a common heuristic threshold is a 3:1 imbalance ratio between one side and the other, with "stacked" imbalances across consecutive price levels treated as a stronger signal. **Evidence:** The underlying logic is well-established in market-microstructure practice and academic literature broadly (not crypto-specific in the sources reviewed), and one crypto-specific technical analysis confirmed the OFI calculation methodology applies directly to Bitcoin book data. **Data requirement:** This is the critical constraint — order-flow imbalance requires live, granular order-book/tape data, which the questionnaire's own F.83–84 answers acknowledge is being collected starting now but is explicitly not used by any v1 strategy. **Suitability:** Theoretically sound but currently infeasible for v1 given the account's own data-infrastructure timeline; correctly deferred, as the CTO already concluded in E.56 ("order-flow needs tick/book data we don't yet have").[^14][^15][^16][^17]

## 7. Open interest / liquidation-based methods

**Mechanism:** Sharp drops in open interest combined with price extension beyond a volatility band (e.g., 2 standard deviations from VWAP) are interpreted as signs of a liquidation-driven, likely-exhausted move, offering a counter-trend fade entry once the forced selling/buying pressure is spent. **Evidence:** The clearest sourced example describes trading BTC using a VWAP-deviation trigger confirmed by an open-interest drop of 1% or greater, with liquidation clustering used as secondary confirmation — this is a retail/practitioner methodology, not an academically validated study, and the specific numeric thresholds (1% OI drop, 2 standard deviations) are heuristic rather than derived from a rigorous backtest. General open-interest research (largely from equity options markets, not crypto) supports the broader claim that open interest changes carry information content about future price movement, lending some indirect credibility to the mechanism. **Suitability:** Directionally interesting and aligned with the questionnaire's E.74 decision to allow open interest, funding rates, and liquidations as v1-eligible external data (since they are venue-native and point-in-time-safe), but this is fundamentally a counter-trend/fade strategy rather than trend-following — it would need its own dedicated validation track and its own prohibited-regime declaration (specifically prohibited during genuine trend continuation, since a liquidation-driven bounce read as a fade during a real trend break would be exactly the failure mode). Better suited as a v2 research candidate than a v1 core setup, since the current v1 family is trend/pullback based and this mechanism describes a distinct, opposing thesis category.[^18][^19][^20][^21]

## 8. Chart-pattern / market-structure methods

**Mechanism:** Formations such as flags, pennants, triangles, and cup-and-handles are interpreted as visual encodings of the same underlying trend-continuation or reversal dynamics described above, with entries typically triggered on a confirmed breakout of the pattern boundary. **Evidence:** The described entry/exit/stop logic is essentially indistinguishable in mechanism from the breakout and pullback-continuation families already covered — chart patterns are a visual overlay on the same price-action logic rather than an independently validated alternative mechanism, and no source reviewed provided rigorous quantitative backtest evidence isolating chart-pattern recognition as an edge distinct from simpler trend/breakout rules. **Suitability:** This directly supports the CTO's own E.72 decision to defer the FORGE-style pattern engine — pattern logic appears to be a restatement of already-covered mechanisms with substantially higher hypothesis-count (n_trials) cost from the large number of pattern-shape permutations, without independent evidence of incremental edge.[^22]

## 9. Statistical arbitrage-like methods

No crypto-specific statistical arbitrage or pairs-trading evidence was surfaced in this research pass; this family is not evaluated further here given the account's single-position, single-asset-family v1 scope, and should be revisited only if the questionnaire's later multi-position architecture (already built but disabled) is activated.

## Comparative summary

| Family | Mechanism clarity | Evidence strength (crypto) | Data needs | Cost sensitivity | v1 suitability |
|---|---|---|---|---|---|
| Time-series momentum/trend | High | Strong, multi-study[^1][^4][^5] | OHLCV only | High | Good, adapt horizon down |
| Pullback continuation | High | Practitioner-consistent, no academic backtest found | OHLCV + indicator | Moderate | **Best fit for chosen timeframe structure** |
| Breakout/vol expansion | Moderate | Mixed; low win rate/high payoff pattern[^6] | OHLCV + volume | High | Good as sibling setup, needs volume filter |
| Mean-reversion | Moderate | Mixed/asymmetric[^12][^13] | OHLCV | High | Weak, correctly deprioritized |
| Range trading | Moderate | Not independently found | OHLCV | High | Unvalidated, inherits mean-reversion caveats |
| Order-flow imbalance | High | Sound in theory, not crypto-validated here | Tick/book data | Low-moderate | Infeasible for v1 (no data yet) |
| Open interest/liquidation | Moderate | Practitioner heuristic only[^19] | Venue-native OI/liq data | Moderate | v2 research candidate, distinct thesis category |
| Chart patterns | Low (restates others) | No independent evidence | OHLCV | High (n_trials cost) | Correctly deferred |
| Statistical arbitrage | N/A | Not surfaced for crypto | N/A | N/A | Out of scope for v1 |

## Implications for strategy selection

This review supports the CTO's E.56 recommendation without modification: pullback-continuation as the primary v1 setup, with breakout/volatility-expansion as the closely related sibling, is the best-evidenced combination available given the account's data constraints, timeframe structure, and cost sensitivity. The time-series momentum literature is the single strongest academic evidence base found, and its multi-timeframe-trend-filter architecture is structurally identical to what pullback-continuation already requires — meaning the strategy family effectively borrows credibility from the momentum literature's macro-level validation while executing at the CTO's chosen intraday micro-level. The clearest caution across every family reviewed is cost sensitivity: multiple independent sources found that raw backtest edges shrink or disappear once realistic transaction costs are applied, reinforcing the importance of Report 2's three-regime cost model and the questionnaire's own I.137–138 cost-share gates as binding constraints on strategy selection, not just execution detail.

---

## References

1. [Momentum Trading in Cryptocurrencies: A Comparative ...](https://www.zurnalai.vu.lt/BATP/article/download/44540/42590) - by AD Gbadebo · 2026 — Relatively few studies provide a direct comparison between time-series and cr...

2. [Intraday return predictability in the cryptocurrency markets: momentum ...](https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID4135239_code2537556.pdf?abstractid=4080253&mirid=1) - This paper reports evidence of intraday return predictability, consisting of both intraday momentum ...

3. [Intraday return predictability in the cryptocurrency markets: Momentum ...](https://ideas.repec.org/a/eee/ecofin/v62y2022ics1062940822000833.html) - by Z Wen · 2022 · Cited by 45 — This paper reports evidence of intraday return predictability, consi...

4. [Momentum in the Cryptocurrency Market](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4675565) - by C Han · 2023 · Cited by 6 — Evidence of time-series momentum is strong, whereas evidence of cross...

5. [Dynamic time series momentum of cryptocurrencies](https://community.portfolio123.com/uploads/short-url/amrMsuqIKzdHcHHyvMud4YNPwZB.pdf) - by O Borgards · 2021 · Cited by 30 — We find evidence that price persistence is highly prevalent in ...

6. [Breakout Trading Strategy: Does It Work on Crypto? (Backtested)](https://www.coinquant.ai/blog/breakout-trading-strategy-does-it-work-on-crypto-backtested) - We tested a Bollinger Bands breakout strategy on Ethereum using CoinQuant. Over 6 months, it returne...

7. [Can You Backtest a Breakout Strategy? Here's How to Do It Right](https://fxreplay.com/learn/can-you-backtest-a-breakout-strategy-heres-how-to-do-it-right) - How to Backtest a Breakout Strategy on FX Replay · 1. Define Clear Breakout Rules · 2. Choose a Time...

8. [How to Trade Trend Continuations (The Only Strategy New ...](https://www.youtube.com/watch?v=i8pR0Nsi1Nc) - I break down trend continuation trading, the strategy I personally use to capture high-probability m...

9. [Popular trend trading strategies | IG AU](https://www.ig.com/au/learn-to-trade/ig-academy/shorts/popular-trend-trading-strategies) - Pullback trading is a strategy where you try to take advantage of temporary price reversals within a...

10. [Trend Pullback Trading Strategy](https://themarketstructuretrader.com/trend-pullback-trading-strategy/) - The trend pullback strategy is a multi-timeframe strategy that uses a higher timeframe in two ways. ...

11. [Pullback Trading Strategy: Entering and Exiting Trends ...](https://capital.com/en-int/learn/trading-strategies/pullback-trading) - A pullback is a brief pause in a trend. A pullback trading strategy means you enter when the asset p...

12. [Testing for mean reversion in Bitcoin returns with Gibbs-sampling- ...](https://www.sciencedirect.com/science/article/abs/pii/S1544612319306415) - by DE Turatti · 2020 · Cited by 12 — We found evidence of mean aversion for multi-period Bitcoin ret...

13. [Trend-following and Mean-reversion in Bitcoin](https://quantpedia.com/trend-following-and-mean-reversion-in-bitcoin/) - mean-reversion theory suggests that assets tend to revert to their long-term mean after all. Therefo...

14. [How Order Flow Imbalance Can Boost Your Trading Success](https://bookmap.com/blog/how-order-flow-imbalance-can-boost-your-trading-success) - Order flow imbalance is the difference between the volume of buy orders and sell orders at different...

15. [Order Flow Imbalance - A High Frequency Trading Signal](https://dm13450.github.io/2022/02/02/Order-Flow-Imbalance.html) - Order flow imbalance represents the changes in supply and demand. With each row one of the price or ...

16. [Order Flow Imbalance Signals: A Guide for High Frequency ...](https://www.quantvps.com/blog/order-flow-imbalance-signals) - A good starting point is using a 3:1 imbalance ratio, which helps you focus on meaningful buying or ...

17. [How to Identify Order Flow Imbalance in the Markets](https://optimusfutures.com/blog/order-flow-imbalance/) - Order flow imbalance arises when a substantial difference exists between the number of buy and sell ...

18. [Trading on the Information Content of Open Interest](https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID288123_code011027100.pdf?abstractid=288123) - Our empirical evidence thus suggests that equity options open interest contain information about the...

19. [The BEST Scalping Strategy for Bitcoin? [Open Interest ...](https://www.youtube.com/watch?v=JDtkLZkCerY) - The BEST Scalping Strategy for Bitcoin? [Open Interest - VWAP - Liquidations]. @CrackingCrypto56 lik...

20. [Interpreting Open Interest in Futures Markets for Better ...](https://bookmap.com/blog/interpreting-open-interest-in-futures-markets-for-better-trades) - Combining open interest with volume or RSI improves the accuracy of trading signals. High volume and...

21. [Building a Strategy with Open Interest](https://www.buildalpha.com/free-friday-18-building-a-strategy-with-open-interest/) - A trading strategy that relies on Open Interest as an input signal or filter can be considered an Op...

22. [The Best Trend Continuation Chart Patterns](https://tradeciety.com/the-best-trend-continuation-chart-patterns) - This guide will cover the most effective trend continuation patterns, shedding light on how traders ...

