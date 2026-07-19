# Quantitative Trading Math Primer
Concise, keyword-dense reference for the mathematics underlying an automated intraday crypto trading system. Each section states the concept, the formula, key terms, and a pythonic pseudocode contract (inputs/outputs only — no types, no implementation detail) suitable for an AI coding agent to implement against. Core conceptual framing draws on standard quant-trading pedagogy, including the treatment of statistical edge, Sharpe ratio, log returns, autoregression, and order-book mechanics presented in a widely-referenced introductory quant trading video.[^1]
## 1. Account state: balance, equity, realized and unrealized P&L
**Balance** is cash-settled capital reflecting only closed trades. **Equity** is balance plus the mark-to-market value of all open positions (unrealized P&L). **Realized P&L** is locked in the instant a position closes; **unrealized P&L** fluctuates with the mark price until then.

\[
\text{equity} = \text{balance} + \sum_i \text{unrealized\_pnl}_i
\]

\[
\text{unrealized\_pnl} = q \times (\text{mark\_price} - \text{entry\_price}) \times \text{side}
\]

where \(q\) is position quantity, side is \(+1\) for long, \(-1\) for short.

```
def compute_equity(balance, open_positions, mark_prices):
    # in: balance (scalar), open_positions (list of {qty, entry_price, side, symbol}),
    #     mark_prices (dict symbol -> price)
    # out: equity (scalar), unrealized_pnl_total (scalar)
    ...

def close_position(position, exit_price, fees):
    # in: position {qty, entry_price, side}, exit_price, fees (scalar)
    # out: realized_pnl (scalar), updated_balance (scalar)
    ...
```

Keywords: mark-to-market, cash balance, floating P&L, position marking, settlement.
## 2. Daily and lifetime drawdown barriers (MDL / MDD)
**Maximum Daily Loss (MDL)** resets each day off a reference balance; **Maximum Drawdown (MDD)** is a static or trailing lifetime barrier. Breach detection uses real-time equity; reset baseline typically uses balance, not equity (confirmed Kraken Prop convention).[^1]

\[
\text{daily\_floor} = \text{balance}_{00:30\,UTC} \times (1 - \text{mdl\_pct})
\]
\[
\text{lifetime\_floor} = \text{starting\_balance} \times (1 - \text{mdd\_pct})
\]
\[
\text{breach} = \text{equity} \leq \min(\text{daily\_floor}, \text{lifetime\_floor})
\]

```
def check_drawdown_breach(equity, daily_floor, lifetime_floor):
    # in: equity, daily_floor, lifetime_floor (scalars)
    # out: breached (bool), which_barrier ("daily" | "lifetime" | None)
    ...

def recompute_daily_floor(balance_at_reset, mdl_pct):
    # in: balance_at_reset, mdl_pct
    # out: daily_floor
    ...
```

Keywords: absorbing barrier, static vs. trailing drawdown, high-water mark, reset cadence, gambler's ruin.
## 3. Notional value and leverage
**Notional value** is the full economic exposure of a position; **leverage** is notional divided by margin/equity committed.

\[
\text{notional} = q \times \text{price}
\]
\[
\text{leverage} = \frac{\text{notional}}{\text{margin\_used}}
\]

```
def compute_notional(qty, price):
    # in: qty, price
    # out: notional
    ...

def compute_leverage(notional, margin_used):
    # in: notional, margin_used
    # out: leverage_ratio
    ...
```

Keywords: margin, exposure, effective leverage, initial margin, maintenance margin.
## 4. Position sizing inclusive of fees
Sizing must embed round-trip fees and slippage reserve directly into the constraint, not deduct them afterward — the load-bearing formula for the whole system.

\[
q(D + P(f+s)) \le R
\]
\[
q_{\max} = \frac{R}{D + P(f+s)}
\]

where \(R\) = max permitted loss, \(D\) = stop distance per unit, \(P\) = entry price, \(f\) = proportional round-trip fee, \(s\) = proportional slippage reserve.

```
def max_position_size(max_loss_R, stop_distance_D, entry_price_P, fee_f, slippage_reserve_s):
    # in: R, D, P, f, s (all scalars, consistent units)
    # out: q_max (scalar)
    denom = stop_distance_D + entry_price_P * (fee_f + slippage_reserve_s)
    return max_loss_R / denom
```

Keywords: cost-aware sizing, risk-first sizing, fee-inclusive stop distance, budget constraint.
## 5. Bid, ask, spread, mid, mark, index, and last price
- **Bid/ask**: best buy/sell price in the order book.
- **Spread** = ask − bid.
- **Mid price** = (bid + ask) / 2 — preferred over last price to avoid bid-ask bounce noise.[^1]
- **Mark price**: typically index price plus a funding-basis adjustment, used for margin/liquidation calculations, distinct from **last traded price**.
- **Index price**: aggregated reference price across venues.

\[
\text{mid} = \frac{\text{bid} + \text{ask}}{2}, \quad \text{spread} = \text{ask} - \text{bid}
\]

```
def compute_mid_and_spread(bid, ask):
    # in: bid, ask
    # out: mid, spread, spread_bps
    ...

def resolve_reference_prices(orderbook, index_feed, last_trade):
    # in: orderbook {bid, ask}, index_feed (scalar), last_trade (scalar)
    # out: {mid, mark, index, last}
    ...
```

Keywords: bid-ask bounce, liquidity price discovery, best bid/offer (BBO), funding basis, liquidation price basis.
## 6. Maker and taker execution
**Making** posts limit orders that add liquidity (often rebated, lower fee); **taking** crosses the book with market orders (guaranteed fill, higher fee, pays the spread).[^1]

```
def classify_execution(order_type, filled_against_resting_order):
    # in: order_type ("limit" | "market"), filled_against_resting_order (bool)
    # out: role ("maker" | "taker")
    ...

def apply_execution_fee(notional, role, maker_fee_bps, taker_fee_bps):
    # in: notional, role, fee schedules
    # out: fee_paid
    ...
```

Keywords: liquidity provision, liquidity removal, rebate, fee tier, adverse selection.
## 7. Expected versus stressed slippage
**Expected slippage** is the baseline execution cost under normal book depth; **stressed slippage** applies during volatility spikes or thin liquidity (weekend/low-volume regimes), and should be modeled as a distinct regime, not a blended average.

\[
\text{slippage} = |\text{fill\_price} - \text{decision\_price}|
\]

```
def estimate_slippage(order_size, orderbook_depth, regime):
    # in: order_size, orderbook_depth (levels of {price, qty}), regime ("normal"|"weekend"|"stress")
    # out: expected_slippage, worst_case_slippage
    ...
```

Keywords: regime-conditional cost model, liquidity depth, market impact, tail slippage.
## 8. Order-book depth and market impact
Market orders "walk the book" when size exceeds depth at the best level, consuming successive price levels and shifting the mid price.[^1]

\[
\text{avg\_fill\_price} = \frac{\sum_i q_i \times p_i}{\sum_i q_i}, \quad q_i \le \text{depth\_at\_level}_i
\]

```
def simulate_book_walk(order_qty, book_levels):
    # in: order_qty, book_levels (list of {price, qty}, sorted by priority)
    # out: avg_fill_price, levels_consumed, residual_unfilled_qty
    ...

def market_impact_estimate(order_qty, avg_daily_volume, impact_coefficient):
    # in: order_qty, avg_daily_volume, impact_coefficient
    # out: expected_impact_bps
    ...
```

Keywords: book walking, depth-of-market, VWAP fill, square-root impact model, liquidity consumption.
## 9. Funding event calculations
Perpetual futures periodically exchange funding payments between longs and shorts to anchor price to index.

\[
\text{funding\_payment} = \text{notional} \times \text{funding\_rate}
\]

Sign convention: positive funding rate → longs pay shorts.

```
def compute_funding_payment(notional, funding_rate, side):
    # in: notional, funding_rate, side (+1 long, -1 short)
    # out: payment (positive = paid, negative = received)
    ...

def accrue_funding_over_window(position, funding_rate_series, interval_hours):
    # in: position, funding_rate_series (list), interval_hours
    # out: total_funding_cost
    ...
```

Keywords: perpetual swap, funding interval, basis, carry cost.
## 10. Gross and net reward-to-risk
\[
\text{RR}_{\text{gross}} = \frac{\text{take\_profit\_distance}}{\text{stop\_distance}}
\]
\[
\text{RR}_{\text{net}} = \frac{\text{take\_profit\_distance} - \text{cost\_per\_unit}}{\text{stop\_distance} + \text{cost\_per\_unit}}
\]

```
def reward_to_risk(tp_distance, stop_distance, cost_per_unit=0):
    # in: tp_distance, stop_distance, cost_per_unit (fees+slippage per unit)
    # out: rr_gross, rr_net
    ...
```

Keywords: R-multiple, payoff ratio, net-of-cost RR.
## 11. Gross and net expectancy
Expectancy is the average P&L per trade — the core statistical-edge quantity.[^1]

\[
E_{\text{gross}} = p_w \cdot \bar{W} - p_l \cdot \bar{L}
\]
\[
E_{\text{net}} = p_w \cdot \bar{W} - p_l \cdot \bar{L} - \bar{C}
\]

where \(p_w, p_l\) are win/loss probabilities, \(\bar{W}, \bar{L}\) average win/loss size, \(\bar{C}\) average round-trip cost.

```
def expectancy(win_rate, avg_win, avg_loss, avg_cost=0):
    # in: win_rate (0..1), avg_win, avg_loss (positive magnitude), avg_cost
    # out: expectancy_gross, expectancy_net
    loss_rate = 1 - win_rate
    gross = win_rate * avg_win - loss_rate * avg_loss
    net = gross - avg_cost
    return gross, net
```

Keywords: expected value (EV), edge, per-trade P&L, law of large numbers.
## 12. Probability of target before stop
Modeled as a two-barrier absorbing random walk (gambler's ruin). For a symmetric random walk starting at distance \(k\) from ruin out of total distance \(N\):[^1]

\[
P(\text{target first}) = \frac{k}{N}
\]

For asymmetric drift/volatility, use Monte Carlo path simulation instead of the closed form.

```
def prob_target_before_stop_analytic(distance_to_stop, distance_to_target):
    # in: distance_to_stop, distance_to_target (both positive, same units)
    # out: prob_target_first  (symmetric random walk approximation)
    total = distance_to_stop + distance_to_target
    return distance_to_stop / total

def prob_target_before_stop_montecarlo(drift, volatility, stop_distance, target_distance, n_paths, dt):
    # in: drift, volatility, stop_distance, target_distance, n_paths, dt
    # out: prob_target_first, expected_bars_to_outcome
    ...
```

Keywords: absorbing barriers, first-passage probability, triple-barrier method, Monte Carlo path simulation.
## 13. Cost share as a fraction of planned risk
Quantifies how much of the risk budget is consumed by costs alone — a strategy viability gate.

\[
\text{cost\_share} = \frac{\bar{C}}{R}
\]

```
def cost_share_of_risk(avg_round_trip_cost, planned_risk_R):
    # in: avg_round_trip_cost, planned_risk_R
    # out: cost_share_pct
    return avg_round_trip_cost / planned_risk_R
```

Keywords: cost-to-risk ratio, viability threshold, fee drag.
## 14. Gap and jump-loss modeling
When price gaps through a stop (illiquidity, weekend, liquidation cascade), realized loss exceeds planned stop distance.

\[
\text{jump\_loss} = q \times |\text{gap\_exit\_price} - \text{stop\_price}|
\]

```
def model_gap_loss(qty, stop_price, historical_gap_distribution):
    # in: qty, stop_price, historical_gap_distribution (empirical samples of gap sizes)
    # out: expected_jump_loss, tail_jump_loss_p99
    ...

def apply_gap_multiplier(planned_risk_R, gap_multiplier):
    # in: planned_risk_R, gap_multiplier (derived from empirical tail, e.g. Report 2's cascade data)
    # out: stressed_risk_allowance
    ...
```

Keywords: slippage tail, liquidation cascade, fat tails, empirical gap distribution, stop-loss failure mode.
## 15. Human execution latency and discrepancy cost
Cost incurred between signal generation and actual order placement, whether from human review delay or system latency.

\[
\text{discrepancy\_cost} = |\text{price}(t_{\text{signal}}) - \text{price}(t_{\text{fill}})| \times q
\]

```
def latency_discrepancy_cost(price_at_signal, price_at_fill, qty):
    # in: price_at_signal, price_at_fill, qty
    # out: discrepancy_cost, discrepancy_bps
    ...

def track_latency_distribution(signal_timestamps, fill_timestamps):
    # in: signal_timestamps (list), fill_timestamps (list)
    # out: latency_distribution_stats {mean, p95, p99}
    ...
```

Keywords: decision-to-execution lag, latency risk, stale price, review delay.
## 16. Prop evaluation as absorbing barriers
The evaluation itself is a two-barrier random walk: ruin = MDD/MDL breach, target = profit goal. Structural pass probability before any strategy edge is applied is governed by starting distance from each barrier (k/N).

```
def simulate_evaluation_path(starting_balance, daily_loss_pct, lifetime_dd_pct,
                              profit_target_pct, trade_pnl_sampler, n_paths, max_days):
    # in: starting_balance, daily_loss_pct, lifetime_dd_pct, profit_target_pct,
    #     trade_pnl_sampler (function producing bootstrapped trade outcomes),
    #     n_paths, max_days
    # out: pass_probability, fail_probability, avg_days_to_outcome, path_distribution
    ...
```

Keywords: two-barrier gambler's ruin, evaluation Monte Carlo, block bootstrap, absorbing states.
## 17. Probability of target before account failure (funded stage)
Distinct objective from #16 — models long-run survival with recurring payouts rather than a single pass/fail event, since funded-account survival and evaluation-passing are empirically very different objectives (payout-completion rates are far lower than pass rates industry-wide).[^1]

```
def simulate_funded_survival(starting_balance, mdd_pct, payout_schedule,
                              trade_pnl_sampler, n_paths, horizon_days):
    # in: starting_balance, mdd_pct, payout_schedule (rules for withdrawal timing/amount),
    #     trade_pnl_sampler, n_paths, horizon_days
    # out: survival_probability, expected_cumulative_payout, ruin_time_distribution
    ...
```

Keywords: perpetual survival objective, payout drag on equity, funded-stage ruin, long-run viability.

***
## 18. Foundational quant math (deep dive)
### 18.1 Returns: simple vs. log
Simple returns are asymmetric (a +20% move followed by a −20% move does not return to start); log returns are symmetric and time-additive, which is why they are preferred for modeling.[^1]

\[
r_{\text{simple}} = \frac{P_t - P_{t-1}}{P_{t-1}}, \qquad r_{\text{log}} = \ln\left(\frac{P_t}{P_{t-1}}\right)
\]

\[
r_{\text{log}}(t_0 \to t_n) = \sum_{i=1}^{n} r_{\text{log}}(t_{i-1} \to t_i)
\]

```
def simple_return(p_curr, p_prev):
    return (p_curr - p_prev) / p_prev

def log_return(p_curr, p_prev):
    return math.log(p_curr / p_prev)

def compound_log_returns(log_return_series):
    # in: log_return_series (list)
    # out: total_log_return, equivalent_simple_return
    total = sum(log_return_series)
    return total, math.exp(total) - 1
```

Keywords: time additivity, symmetric returns, compounding, geometric vs. arithmetic returns.
### 18.2 Statistical edge: expected value
The foundational quantity of any strategy — a positive expectancy with a low win rate can be profitable; a high win rate with poor payoff asymmetry can lose money.[^1]

\[
E[X] = p \cdot W - (1-p) \cdot L
\]

```
def edge_check(win_prob, win_amount, loss_amount):
    # in: win_prob (0..1), win_amount, loss_amount (positive magnitudes)
    # out: expected_value, is_positive_edge
    ev = win_prob * win_amount - (1 - win_prob) * loss_amount
    return ev, ev > 0
```

Keywords: expected value, statistical edge, law of large numbers, bet sizing philosophy ("bet small, bet often").
### 18.3 Risk-adjusted returns: Sharpe ratio
\[
\text{Sharpe} = \frac{E[R] - R_f}{\sigma(R)}
\]

Intraday strategies commonly drop the risk-free rate term since holding periods are too short for it to matter.[^1]

```
def sharpe_ratio(returns_series, risk_free_rate=0, annualization_factor=1):
    # in: returns_series (list), risk_free_rate, annualization_factor
    # out: sharpe
    mean_excess = mean(returns_series) - risk_free_rate
    return (mean_excess / stdev(returns_series)) * sqrt(annualization_factor)
```

Related risk-adjusted metrics worth including in the same module:

\[
\text{Sortino} = \frac{E[R] - R_f}{\sigma_{\text{downside}}(R)}, \qquad
\text{Calmar} = \frac{\text{annualized return}}{\text{max drawdown}}
\]

```
def sortino_ratio(returns_series, risk_free_rate=0):
    # in: returns_series, risk_free_rate
    # out: sortino  (uses downside deviation only)
    ...

def calmar_ratio(annualized_return, max_drawdown_pct):
    # in: annualized_return, max_drawdown_pct
    # out: calmar
    ...
```

Keywords: standard deviation as risk proxy, downside deviation, leverage safety, smoothness of equity curve.
### 18.4 Autoregression and linear models
An AR(1) model predicts the next value from the last known value; a positive weight models momentum, a negative weight models mean reversion.[^1]

\[
\hat{y}_t = w \cdot x_{t-1} + b
\]

```
def ar1_predict(x_lag, weight, bias):
    return weight * x_lag + bias

def fit_ar1_closed_form(x_lags, y_targets):
    # in: x_lags (list), y_targets (list)  -- ordinary least squares
    # out: weight, bias
    ...

def fit_ar1_gradient_descent(x_lags, y_targets, learning_rate, n_iterations, loss_fn):
    # in: x_lags, y_targets, learning_rate, n_iterations, loss_fn
    # out: weight, bias, loss_history
    ...
```

Keywords: lag, autoregression, closed-form / ordinary least squares (OLS), gradient descent, learning rate (eta), convex loss, univariate model, Occam's razor.
### 18.5 Mean reversion vs. momentum signatures
Detected via the sign of the fitted AR(1) weight, or via formal statistical tests (variance ratio, Hurst exponent) as covered in Report 6.

\[
H > 0.5 \Rightarrow \text{trending (persistent)}, \quad H < 0.5 \Rightarrow \text{mean-reverting}, \quad H \approx 0.5 \Rightarrow \text{random walk}
\]

```
def hurst_exponent(price_series, min_window, max_window):
    # in: price_series, min_window, max_window  -- rescaled range (R/S) method
    # out: hurst_H
    ...

def variance_ratio_test(returns_series, k):
    # in: returns_series, k (aggregation horizon)
    # out: variance_ratio, z_statistic, p_value
    ...

def adx(high_series, low_series, close_series, period=14):
    # in: OHLC series, period
    # out: adx_value  (>25 conventionally = trending regime)
    ...
```

Keywords: Hurst exponent, R/S analysis, variance ratio test (Lo-MacKinlay), ADX, regime classification.
### 18.6 Regime detection: Hidden Markov Models
Models market dynamics as transitions between latent states (e.g., low-vol trend, high-vol chop, breakdown), fitted via Baum-Welch / EM.[^1]

```
def fit_hmm_regimes(returns_series, n_states):
    # in: returns_series, n_states
    # out: transition_matrix, state_means, state_variances, fitted_model

def predict_current_regime(fitted_model, recent_returns):
    # in: fitted_model, recent_returns
    # out: regime_label, regime_probabilities
```

Keywords: latent state, transition matrix, Baum-Welch, Viterbi decoding, emission distribution.
### 18.7 Change-point detection: CUSUM
Detects a shift in a time series' mean via cumulative deviation from baseline, usable online for live regime-transition or edge-decay flagging.

\[
S_t = \max(0, S_{t-1} + (x_t - \mu_0 - k))
\]

Flag change when \(S_t\) exceeds threshold \(h\).

```
def cusum_detector(series_stream, baseline_mean, drift_k, threshold_h):
    # in: series_stream (iterable/generator), baseline_mean, drift_k, threshold_h
    # out: change_point_index or None, running_statistic
    ...
```

Keywords: online algorithm, cumulative sum, structural break, PELT, binary segmentation.
### 18.8 Position sizing: fixed-fractional, Kelly, and risk-of-ruin
\[
f^{*} = \frac{bp - q}{b} \quad (\text{Kelly}), \qquad f_{\text{used}} = \lambda \cdot f^{*}, \; \lambda \in [0.25, 0.75]
\]

\[
\text{RoR} \approx \left(\frac{1-p}{p}\right)^{C/R}
\]

```
def kelly_fraction(win_prob, payoff_ratio):
    # in: win_prob (0..1), payoff_ratio (avg_win/avg_loss)
    # out: kelly_f
    loss_prob = 1 - win_prob
    return (payoff_ratio * win_prob - loss_prob) / payoff_ratio

def fractional_kelly(kelly_f, fraction=0.25):
    return kelly_f * fraction

def risk_of_ruin(win_prob, capital_units, risk_units_per_trade):
    # in: win_prob, capital_units (C), risk_units_per_trade (R)
    # out: ror_estimate
    loss_prob = 1 - win_prob
    return (loss_prob / win_prob) ** (capital_units / risk_units_per_trade)
```

Keywords: growth-optimal sizing, fractional Kelly, exponential ruin decay, edge estimation sample size.
### 18.9 Meta-labeling and probability calibration
A secondary classifier filters a primary signal's true/false positives rather than generating new signals; its output probability should be calibrated before use in sizing.

```
def build_meta_labels(primary_signals, price_path, upper_barrier, lower_barrier, vertical_barrier):
    # in: primary_signals, price_path, barrier definitions (triple-barrier method)
    # out: labels (1=profit_hit, -1=stop_hit, 0=timeout), label_metadata
    ...

def train_meta_model(features, labels, model_type):
    # in: features, labels, model_type ("logistic_regression"|"gradient_boosted_tree")
    # out: fitted_meta_model
    ...

def calibrate_probabilities(fitted_model, holdout_features, holdout_labels, method):
    # in: fitted_model, holdout_features, holdout_labels, method ("platt"|"isotonic")
    # out: calibrated_model, reliability_diagram_data
    ...
```

Keywords: triple-barrier labeling, meta-labeling, Platt scaling, isotonic regression, reliability diagram, Brier score.
### 18.10 Validation statistics: DSR and PBO
\[
\text{DSR} = \Psi\left[\frac{(\hat{SR} - SR^{*})\sqrt{n-1}}{\sqrt{1 - \gamma_3 \hat{SR} + \frac{\gamma_4 - 1}{4}\hat{SR}^2}}\right]
\]

where \(SR^{*}\) is the expected maximum Sharpe under \(N\) trials by chance, \(\gamma_3, \gamma_4\) are skewness/kurtosis of returns, and \(\Psi\) is the standard normal CDF.

```
def deflated_sharpe_ratio(observed_sharpe, n_trials, n_observations, skewness, kurtosis):
    # in: observed_sharpe, n_trials, n_observations, skewness, kurtosis
    # out: dsr  (probability true SR > 0 after correcting for multiple testing)
    ...

def probability_of_backtest_overfitting(in_sample_results_matrix):
    # in: in_sample_results_matrix (results across combinatorial train/test splits)
    # out: pbo_estimate  (via CSCV)
    ...
```

Keywords: deflated Sharpe ratio, probability of backtest overfitting (PBO), combinatorially symmetric cross-validation (CSCV), multiple hypothesis correction, data snooping.
### 18.11 Cross-validation for time series: purging and embargo
```
def purged_kfold_split(timestamps, label_end_times, n_splits, embargo_pct):
    # in: timestamps, label_end_times, n_splits, embargo_pct
    # out: list of (train_indices, test_indices)  -- purges overlapping labels, embargoes post-test buffer
    ...
```

Keywords: purging, embargo, combinatorial purged cross-validation (CPCV), overlapping labels, serial correlation.
### 18.12 Monte Carlo trade-sequence simulation
```
def block_bootstrap_trades(trade_sequence, block_size, n_paths):
    # in: trade_sequence (historical realized trades), block_size, n_paths
    # out: simulated_equity_curves, drawdown_distribution, ruin_probability
    ...
```

Keywords: block bootstrap, sequence-order risk, path dependency, bust probability.
### 18.13 Market microstructure: order book mechanics
```
def walk_the_book(order_qty, book_side_levels):
    # in: order_qty, book_side_levels (sorted list of {price, qty})
    # out: avg_fill_price, fully_filled (bool), levels_touched
    ...

def quote_skew_from_inventory(base_spread, inventory, skew_coefficient):
    # in: base_spread, inventory (signed position), skew_coefficient
    # out: bid_quote, ask_quote   -- market-making inventory-skew model
    ...
```

Keywords: market making, adverse selection, inventory risk, quote skew, liquidity taking, book depth.
### 18.14 Position-sizing response functions (constant / piecewise / nonlinear)
Trade size can scale with signal strength using bounded nonlinear functions (e.g., tanh) to avoid unbounded sizing on extreme predictions.[^1]

```
def size_constant(base_size, signal):
    return base_size

def size_piecewise_linear(signal, max_size, signal_cap):
    # in: signal, max_size, signal_cap
    # out: size = clip(signal, -signal_cap, signal_cap) / signal_cap * max_size
    ...

def size_nonlinear_tanh(signal, max_size, scale):
    # in: signal, max_size, scale
    # out: size = tanh(signal / scale) * max_size
    ...
```

Keywords: bounded scaling, tanh sizing, signal-proportional sizing, saturation function.

***
## Summary keyword index
Absorbing barriers · ADX · autoregression · Baum-Welch · bid-ask bounce · block bootstrap · Brier score · Calmar ratio · CPCV · CUSUM · deflated Sharpe ratio · drawdown (static/trailing) · EMA · expectancy · fixed-fractional sizing · funding rate · gambler's ruin · gradient descent · Hurst exponent · isotonic regression · Kelly criterion · leverage · log returns · maker/taker · mark price · market impact · meta-labeling · mid price · Monte Carlo simulation · notional value · order book depth · OLS · PBO · Platt scaling · purging/embargo · quote skew · reliability diagram · reward-to-risk · risk of ruin · Sharpe ratio · slippage · Sortino ratio · spread · triple-barrier method · variance ratio test · walk-forward validation.

---

## References

1. [prop-questionnaire-answers-CTO-2026-07-18.md](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/85632446/6bea8a66-5155-4de6-9289-77e2fa653382/prop-questionnaire-answers-CTO-2026-07-18.md?AWSAccessKeyId=ASIA2F3EMEYE4UTTO6XL&Signature=FIM0fOMtNERjBJcmGa%2BuAvut1ik%3D&x-amz-security-token=IQoJb3JpZ2luX2VjEMH%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJIMEYCIQD%2B5B2InGCW5jjoyzV%2BUIbnlX0NJy03VxzhWC6qNPi7cwIhANMG%2Brwpcn7PZUd%2FlvxH2QnJZj%2B1jDGJm0DxPkNWgr3IKvwECIn%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEQARoMNjk5NzUzMzA5NzA1IgxLLT1OEFAKwyiBERoq0ATqq%2BVFo9MnQN6KRuVScUFhKtRrcGK9GaSb0uFqoHMDjzWTY%2FaEvD4Ioz7Cmm%2FQ%2BYHeODX9c0YppG0XRfYn9hD4Lt0x8OaW7wSgpyXX2FDDueBfJMgwmEbrt1zrjowTYuqF9YmGJnq7l1RYdU%2BPydL6YnRk3VpIvcPOfuNGIOjPFi2Mt%2BSeT5zfHyGMNzJMSblTOfqgfODS6QrVC9jfoTR4%2Badzb5mVP70C7NIVWhxK78jsGdzosLK0fgjwetEvDpBB35csBWoS34G%2Bh2EE95zloAbbkDhpRpxx%2FDpdvIrTfcYf%2BBSvUAKOno1hXLZrrxIg8PMfo%2F0j%2F4iRcOzdeBOZ3lk9BI%2FZIfYphCqu6QgQ6qfiC612QMh6Bp1K2HxT26P5PnIoaVUSKCCY1wun%2FpsXp9ypowpYlbRoO%2FddSubQopo3NxAm2ZA8nWff6LzkqJyIo5CTwh3NswBj%2BpdVEiC8y8GmvL69FZuERK5MDgodKb%2BWbMBZrE%2Bapr9%2FDOIl7xQrHYGVVMoI96Awi2Ai3rQ12SujqGiw0CMj5YERO0HbDoYixaLtTubE1ys4Z9i0R3VLf6%2BDkFMY2GxcRSsHGjMwHUtUddyxViigJDKDGKrLxuKXKD%2BxuF9z48t0EdLb9XQpHryAbC9CEvv0zCm4DcqZMLjumD5gINwoJRxmGgGoCJxLbycLaFVnmkI0SaJYZ7FKeSGQyKp0hY1cbAz6Jy0RngVqCFylRKBJOdLgGFGiPSrpN5xdfVnleAuiUUXwRSO91M6xXbl1TJbrTerit7DlMP%2BQ8tIGOpcBhzZhjCaB%2FTA4onfj8dU362q9WaUL0ioaImgawsJ7LFcR0r42%2FVYgG7Iy4IhivMP%2F15n2sfz4H5Na35BuP8u54SEYEsxtGLiQXGjbNLLiQHqG%2Fx4PPh7MWPlHbmB6bb8pZbORRiQE9sQmEX5O4RzDtWSFBnnEOdypDOmoxKhhrl1jw6Vws99tndz8%2BA6Tt587%2Bg0%2FloQOnA%3D%3D&Expires=1784452690) - Answers to GPT 5.6 Sols 378-question discovery sheet for the Kraken-prop strategy program. Answered ...

