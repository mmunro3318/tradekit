# Intraday Crypto Market Microstructure and Execution Cost Modeling

## Overview

Crypto markets trade continuously across a fragmented set of venues with no centralized consolidated tape, producing microstructure behavior that differs from equities and futures in ways directly relevant to a small ($5,000-scale) intraday prop account: spreads are structurally wider than headline averages suggest once volatility spikes, weekend liquidity is measurably and persistently thinner, stop-market orders can experience severe slippage during cascading liquidations, and the mark/index/last-price distinction determines whether a position gets liquidated at all. Each of these mechanics has direct, quantifiable implications for the cost models, liquidity gates, and stop-order behavior specified in the questionnaire's Sections C, H, and I.

## 1. Bid-ask spread behavior

Academic microstructure research on BTC spot and futures markets found bid-ask spreads averaging just 0.0298% under normal conditions across major spot exchanges, but this tight average masks tail behavior: spreads exceeded 0.8% for a combined 226 seconds across the entire sample period studied — meaning spreads are usually extremely tight but occasionally blow out by more than 25x the median. This confirms that a fixed basis-point cost assumption (the questionnaire's I.142 "stage 1" model) will systematically understate costs during the specific volatile windows where a trend-following or breakout strategy is most likely to be entering.[^1][^2]

Weekend-specific spread data quantifies this further: one comparative dataset showed BTC-USDT spreads on Binance widening from roughly 0.012% on a representative weekday to roughly 0.028% on a weekend — more than doubling — alongside a fall in 24-hour spot volume from $32B to $6.5B. A separate industry dataset (Kaiko, cited secondhand) found weekend BTC trading volume has fallen from 28% of weekly volume in 2019 to just 16% in more recent data, indicating the weekend liquidity gap has been widening over time rather than closing as the market matures. This directly supports the questionnaire's C.29 decision to require stricter liquidity/spread gates specifically for weekend trading, and suggests the gate thresholds should be materially different (roughly double the weekday spread ceiling, at minimum) rather than a uniform modest adjustment.[^3]

## 2. Order book depth and slippage

Order book depth — the cumulative size available at each price level away from the best bid/ask — determines how much a market order (or a stop-market order once triggered) will move the price against the trader before it fully fills. For central limit order books (as opposed to AMM-style DEX liquidity pools), thin books mean progressively worse fills as order size increases, while thick books absorb the same order with minimal price impact. Academic work on BTC/CME and spot markets found that trade sizes over $1 million moved the market by less than 1% in aggregate, but this reflects deep, mature BTC liquidity specifically — smaller altcoins and thinner weekend books do not share this resilience.[^4][^5][^2][^6][^7][^1]

Practical guidance converges on splitting large orders to allow book replenishment between fills, avoiding market orders in thin conditions in favor of limit orders, and treating pool/book liquidity (in dollar terms) as a direct input to position sizing rather than a static assumption. This validates the questionnaire's I.141 depth-based position-size cap (order size ≤5% of visible depth) as directionally correct, though the specific 5% threshold should be validated per-asset with live order-book data rather than treated as a global constant, since BTC and a smaller altcoin do not share the same depth profile at the same nominal order size.[^7][^4]

## 3. Volatility clustering

Bitcoin's return volatility exhibits strong clustering — large price changes tend to be followed by more large changes, and calm periods tend to be followed by more calm periods, consistent with the general Mandelbrot-Cont stylized fact for financial time series generally and confirmed specifically for BTC. The autocorrelation of absolute returns decays slowly across timescales from minutes to weeks, meaning a strategy's realized-volatility-based position sizing or regime classifier should expect volatility regimes to persist for extended windows rather than mean-revert quickly. One dedicated empirical study found this clustering effect is strong at shorter timeframes and that the relationship between low-volatility periods and subsequent low-risk outcomes weakens over long horizons, since the standard deviation of future moves grows faster in the low-volatility percentile bins than in high-volatility bins — a caution against assuming calm regimes reliably predict continued calm at longer horizons. This is directly relevant to Report 6's regime-detection work: realized volatility and GARCH-style clustering measures are well-supported empirically as regime features for BTC specifically.[^8][^9][^10]

## 4. Liquidation cascades

A liquidation cascade begins when a price move against leveraged positions forces automatic, exchange-triggered liquidations; these forced closes add directional selling (or buying, for short liquidations) pressure that pushes price further, triggering additional liquidations in a feedback loop. A recent academic dissection of the October 10–11, 2025 crypto liquidation cascade documented $19 billion in open interest erased within 36 hours, giving a concrete, recent, extreme-tail benchmark for how severe and fast these events can be. Contributing factors include high leverage usage, stop-loss orders converting to market orders en masse at similar trigger levels, and adverse news catalysts compounding an already-stressed market.[^11][^12][^13][^14]

For a small prop account, the direct implication is that stop-market orders — which the questionnaire mandates for all protective exits (H.149) — are exactly the order type most exposed to slippage during a cascade, since a triggered stop becomes an ordinary market order subject to whatever liquidity remains in the book at that instant. Practical mitigation cited across multiple sources: avoid excessive leverage, maintain sufficient account buffer above liquidation thresholds, and size positions assuming stop fills may occur meaningfully worse than the stop price during high-volatility windows. This directly supports the questionnaire's H.134 gap/jump-risk estimate and H.121 gap allowance (0.30% max loss vs. 0.15% planned risk) as a reasonable, evidence-consistent buffer — though the October 2025 cascade magnitude suggests the tail case can exceed a simple 2x gap multiplier during genuinely extreme, multi-hour cascade events, arguing for the H.129 slippage-anomaly halt to trigger conservatively.[^13][^15][^16]

## 5. Mark price, index price, and last-traded price

These three reference prices serve distinct functions and must not be conflated in strategy or risk-kernel logic. The **index price** is a volume/quality-weighted average of an asset's spot price across multiple major exchanges, serving as a manipulation-resistant baseline. The **mark price** is derived from the index price plus an adjustment for the funding basis (the gap between contract and spot price), and is the price actually used to calculate unrealized P&L and to trigger liquidations — specifically engineered to resist short-term manipulation or a single exchange's momentary price spike. The **last-traded price** is simply the most recent executed trade price on that specific venue; it is the most volatile and most exposed to single-exchange wicks or thin-book manipulation, and is used for realized P&L at the moment a trade actually executes.[^17][^18][^19][^20][^21]

The practical consequence: a stop or liquidation level should be evaluated against mark price wherever configurable, since last-price-triggered stops are more exposed to brief, single-exchange wicks that do not reflect genuine market consensus. This is a direct, unresolved question for Report 1 follow-up — Kraken Prop's specific mark/index/last convention for stop and liquidation triggers was not confirmed in the prior report and should be verified directly, since it changes how conservatively the risk kernel should treat H.135's liquidation-distance requirement.

## 6. Funding rates and holding-cost timing

Perpetual futures funding rates are periodic payments exchanged between long and short position holders, calculated from the sum of a fixed interest-rate component and a variable premium index reflecting the gap between contract and spot price. Funding intervals vary by venue and region — Kraken Pro specifically applies funding every 8 hours for US clients and every hour for EEA clients. Because funding is charged (or paid) purely as a function of holding a position through the funding timestamp, regardless of whether the position is profitable, it functions as a real, timing-dependent cost that a purely price-based backtest will misprice if funding timestamps are not modeled explicitly.[^22][^23][^24][^25][^26]

For the questionnaire's I.159 policy (model funding exactly; avoid holding through funding only when it flips trade EV), this means the strategy's expected-holding-time model must be timestamp-aware relative to the funding schedule, not just duration-aware — a position held for the same number of minutes carries very different expected funding cost depending on whether that window straddles a funding timestamp. Given Kraken's 8-hour US funding interval, and the questionnaire's 15-minute execution / 1-hour intermediate timeframe, most single trades within the target holding-time range will cross at most one funding timestamp, making this a tractable, boundable cost rather than an open-ended one.

## 7. Maker vs. taker execution

Maker orders (resting limit orders that add liquidity to the book) are charged lower fees than taker orders (market orders or aggressively-priced limit orders that immediately remove liquidity) on essentially all centralized exchanges using this fee model, including Kraken. This fee asymmetry is a direct, quantifiable incentive supporting the questionnaire's I.143 preference for passive limit entries wherever the setup allows, since maker orders both avoid paying the spread (no crossing cost) and earn the lower fee tier simultaneously. The tradeoff is fill uncertainty: a passive limit order at or better than the current market will not fill if price simply moves away, which is why the questionnaire's I.144–146 policy (limit lifetime capped at the setup window, no chasing, max 2 repricing attempts) is a reasonable, evidence-consistent constraint — it bounds the maker-fee benefit against the risk of holding a stale, unfilled entry order past its setup validity.[^27][^28][^29][^30][^31]

## 8. Weekend and session effects

Multiple independent sources converge on the same finding: crypto markets exhibit a distinct weekend liquidity contraction, with lower trading volume, wider spreads, higher volatility-to-liquidity ratio, and a documented higher failed-breakout rate (one source found 53% weekend breakout failure vs. 37% weekday). Academic work using hourly volume-share and realized-variance data on Bitstamp found trading activity follows a reverse-V-shaped intraday pattern, peaking during US and European stock market operating hours, with weekday volume and volatility "markedly higher" than weekend figures across the whole dataset. This is one of the more robust, well-replicated findings in the crypto microstructure literature and should be treated as a high-confidence input to Report 6's liquidity-regime and blackout-hour design — specifically, the questionnaire's C.30 "empirically poor-liquidity hours" blackout should weight weekend sessions and the low-activity Asia-only overnight window (outside European/US hours) as the two primary blackout candidates, pending asset-specific validation.[^32][^33][^34][^3]

One caveat: a separate "weekend effect" literature strand claims Bitcoin shows a tendency toward positive price drift specifically over weekends. This is a directional-return claim distinct from the liquidity-contraction claim, is less rigorously sourced in the search results retrieved (a single non-academic source), and should not be treated as validated evidence for a weekend-specific directional bias — it is flagged here only to distinguish it clearly from the well-supported liquidity-contraction finding, which is the operationally relevant one for the questionnaire's gating logic.[^32]

## 9. Execution cost model recommendations for a small prop account

Synthesizing the above into a cost model appropriate for the questionnaire's progressive-richness approach (I.142: fixed bps → volatility-scaled → historical replay → live depth):

| Cost component | Typical/normal | Stress condition | Source |
|---|---|---|---|
| Spread (BTC, weekday) | ~0.01–0.03% | Up to 0.8%+ during volatility spikes | [^1][^2][^3] |
| Spread (BTC, weekend) | ~2x weekday baseline | Materially wider during thin weekend windows | [^3] |
| Maker fee vs taker fee | Maker consistently lower | N/A — structural, not stress-dependent | [^27][^28] |
| Slippage on stop-market during cascade | Model-dependent | Can be severe; $19B OI erased in 36h in Oct 2025 tail event | [^11][^13][^15] |
| Funding cost per 8h window (Kraken US) | Small, rate-dependent | Can spike sharply during extreme one-sided positioning | [^22][^25] |

A fixed-bps model for stage 1 should therefore be calibrated separately for weekday-normal, weekend-normal, and stress conditions rather than using a single blended average — the weekday/weekend spread gap alone is roughly 2x, which would otherwise systematically under-price weekend execution risk even before considering the cascade tail.

## 10. Implications for the questionnaire's open items

This report directly informs several previously deferred (R2) questionnaire items: the weekend/blackout liquidity thresholds (C.29–30) should use spread- and volume-ratio gates roughly double the weekday baseline; the per-asset spread/slippage model (I.140) should be built as a three-regime model (weekday-normal, weekend, stress) rather than a single static estimate; the gap/jump risk multiplier feeding H.121 and H.134 should reference realistic cascade magnitudes rather than a flat historical percentile, since the tail is fatter than a normal-times sample would suggest; and the mark/index/last-price convention used for Kraken Prop's own stop and liquidation triggers remains an open item that should be folded into the Report 1 follow-up questions on venue-side stop behavior, since it directly affects how much liquidation-distance buffer (H.135) is actually conservative.

---

## References

1. [Bitcoin Spot and Futures Market Microstructure](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3459111) - by S Aleti · 2020 · Cited by 63 — Bid-ask spreads average 0.0298%.Trade. Bid-ask spreads exceed 0.8%...

2. [Bitcoin spot and futures market microstructure](https://ideas.repec.org/a/wly/jfutmk/v41y2021i2p194-225.html) - by S Aleti · 2021 · Cited by 63 — Bid‐ask spreads average 0.0298%. Bid‐ask spreads exceed 0.8% for o...

3. [Why Weekend Crypto Trading Is a Mirage](https://www.binance.com/en/square/post/24390778876242) - 1. Weekend Liquidity Has Fallen Off a Cliff. A 2024 Kaiko study shows that only 16 % of all BTC trad...

4. [How to Read and Interpret Liquidity and Order Book Depth](https://www.altrady.com/crypto-trading/fundamental-analysis/liquidity-order-book-depth) - Liquidity and order book depth are critical factors that directly impact trading dynamics and overal...

5. [How Market Depth Impacts Crypto Trading: A Guide for ...](https://bookmap.com/blog/how-market-depth-impacts-crypto-trading-a-guide-for-retail-investors) - Market depth reveals how many buy and sell orders exist at various price levels. It shows how much t...

6. [Order Book Depth & Heatmaps Explained](https://whaleportal.com/blog/order-book-depth-explained/) - Order book depth shows how many buy and sell limit orders exist at different price levels for a cryp...

7. [What is slippage? Order books, AMMs, and how ...](https://metamask.io/news/what-is-slippage) - Slippage is the difference between expected execution price and actual execution price. Market order...

8. [Volatility Clustering in Bitcoin](https://papers.ssrn.com/sol3/Delivery.cfm/5073986.pdf?abstractid=5073986&mirid=1) - This paper examines Bitcoin's volatility from an observational standpoint, emphasizing volatility cl...

9. [Volatility Clustering](https://www.daytrading.com/volatility-clustering) - Volatility clustering refers to the observation that large price changes in financial markets are of...

10. [Volatility Clustering in Financial Markets: Empirical Facts and ...](http://rama.cont.perso.math.cnrs.fr/pdf/clustering.pdf) - by R Cont · Cited by 652 — While GARCH, FIGARCH and stochastic volatility models propose statistical...

11. [Anatomy of the Oct 10–11, 2025 Crypto Liquidation Cascade](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5611392) - This paper dissects the October 10-11, 2025, crypto liquidation cascade, which erased $19 billion in...

12. [Liquidation Cascade: Causes, Risks, and Prevention](https://chain.link/article/liquidation-cascade-crypto-lending) - It occurs when declining asset prices trigger liquidations, which further depress prices and cause s...

13. [What Are Liquidation Cascades in Crypto](https://simpleswap.io/blog/what-are-liquidation-cascades-in-crypto) - Liquidation cascades in crypto happen when lots of traders' positions are forcefully closed by excha...

14. [The Evolution of Crypto's Infamous Liquidation Cascade](https://www.allstarcharts.com/2022-04-21/evolution-cryptos-infamous-liquidation-cascade) - So, as the name "liquidation cascade" would suggest, it occurs when liquidations pile on top of each...

15. [Crypto Futures Order Types: A Beginner's Guide [2026]](https://wazirx.com/blog/crypto-futures-order-types/) - The Risk: Gap Slippage Stop-market orders guarantee execution but not price. In a fast market or dur...

16. [What Is a Stop Order?](https://www.cube.exchange/what-is/stop-order) - Learn what a stop order is, how the stop price triggers a market order, why traders use buy and sell...

17. [What Is Mark Price?](https://www.cube.exchange/what-is/mark-price) - mark price is an estimate of contract value used to calculate margin requirements, and liquidation o...

18. [Index Price and Mark Price - Crypto Trading](https://support.btse.com/en/support/solutions/articles/43000557589-index-price-and-mark-price) - The Mark Price is the price used for mark-to-market PnL calculation and platform liquidation, partia...

19. [What Are Index Price, Mark Price, and Last Price?](https://www.bitget.com/academy/what-are-index-price-mark-price-and-last-traded-price) - The mark price is a critical factor of derivatives trading, used to trigger liquidations, calculate ...

20. [Perps 101: Mark Price and Index Price - ApeX Blog](https://www.apex.exchange/blog/detail/Mark-Price-and-Index-Price) - The mark price is the price used to determine unrealized PnL (profit and loss) and trigger liquidati...

21. [Mark Price vs. Last Price: Crypto Futures Differences & Guide](https://changehero.io/blog/index-last-price-mark-price-meaning/) - While the mark price represents the estimated value of a futures contract, the last price refers to ...

22. [Understanding Funding Rates in Perpetual Futures and ...](https://www.coinbase.com/learn/perpetual-futures/understanding-funding-rates-in-perpetual-futures) - The funding rate keeps futures prices aligned with the spot price of the underlying asset, helping p...

23. [Understanding Perpetual Futures: A Guide for ...](https://www.investopedia.com/what-are-perpetual-futures-7494870) - The funding rate is a mechanism that ensures that the price of the perpetual futures contract stays ...

24. [A guide to perpetual futures funding mechanics and timing](https://metamask.io/news/perpetual-futures-funding-frequency-strategies) - The funding rate is a periodic fee exchanged between long and short traders to keep the perpetual co...

25. [What are perpetual futures contracts? A complete guide](https://www.kraken.com/learn/trading/perpetual-futures-contracts) - The perpetual funding rate mechanism involves traders paying or receiving fees at regular intervals.

26. [Perpetual Futures Pricing*](https://finance.wharton.upenn.edu/~jermann/AHJ-main-10.pdf) - by D Ackerer · 2024 · Cited by 53 — Perpetual futures are contracts without expiration date in which...

27. [Understanding Maker-Taker Fees: Impact on Traders and ...](https://www.investopedia.com/articles/active-trading/042414/what-makertaker-fees-mean-you.asp) - Market takers place market orders, prioritize immediate execution, and generally pay higher taker fe...

28. [Maker vs. taker fees: Key differences, examples, and ...](https://www.cointracker.io/blog/maker-vs-taker-fees-key-differences-examples-and-strategies) - An example of maker and taker fees. Suppose a crypto exchange has a maker-taker fee model that charg...

29. [What are maker fees and taker fees? | Bitpanda Academy](https://www.bitpanda.com/en/academy/what-are-maker-fees-and-taker-fees-for-cryptocurrency-traders) - While maker fees are often lower because they stabilise the market, Taker fees are usually higher th...

30. [Maker vs Taker : r/BitcoinBeginners](https://www.reddit.com/r/BitcoinBeginners/comments/tvsdvm/maker_vs_taker/) - On exchanges where the Taker fee is higher than the Maker fee (I'm using Kraken) I'd prefer to be ch...

31. [Maker and Taker Fees Explained](https://markets.bitcoin.com/glossary/maker-taker) - Takers pay fees that are typically higher due to instant execution. This fee difference is especiall...

32. [Weekend Effect In Bitcoin (Crypto) – Rules, Settings ...](https://www.quantifiedstrategies.com/weekend-effect-in-bitcoin/) - Lower Trading Volume: Fewer traders, especially institutional ones, participate over weekends, leadi...

33. [Weekend Risk in Crypto Trading Guide](https://menthorq.com/guide/weekend-risk-in-crypto-trading/) - This article explains how crypto markets behave on weekends, highlighting liquidity drops, volatilit...

34. [Time-of-day periodicities of trading volume and volatility in ...](https://www.sciencedirect.com/science/article/abs/pii/S1544612319301904) - by JN Wang · 2020 · Cited by 54 — We propose using the hourly share of trading volume and realized v...

