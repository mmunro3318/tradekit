# Gemini Adversarial Review of DESIGN.md — 2026-07-12

> Reviewer: Gemini (Codex unavailable — usage cap). Subject: docs/DESIGN.md v0.1 (post consistency-review).
> Disposition decided by CTO-agent, approved workflow per SCOPE §3.3. Findings tagged G1–G6; DESIGN.md cites these tags.

## Disposition summary

| # | Finding | Disposition | Landed in DESIGN.md |
|---|---------|-------------|---------------------|
| G1 | DSR/PSR variance uses sample skew+kurtosis → unstable below n=30; single outlier detonates the kurtosis term | **Accepted.** DSR gates at n≥30 per strategy_tag; 10≤n<30 = provisional regime (penalized Sharpe 1/√n haircut + hard MDD bound, ineligible for promotion). Resolves former open question Q3 | TD-14, §9.4 |
| G2 | float64→Decimal conversion noise can flip a strict `gte` grading predicate | **Accepted.** `quantize(value, asset.tick_size)` utility mandatory at MAE boundary | TD-23 (new), §13 |
| G3 | Weekly-refit HMM is blind to intraweek regime shocks | **Accepted.** Deterministic EWMA realized-vol monitor beside HMM; >3σ deviation from fitted state variance forces `high_vol_override` risk-off output | TD-13, §9.2 |
| G4 | SQLite WAL + busy_timeout will throw `database is locked` under multi-agent write storms; proposed in-process single-threaded write queue | **Partially rejected.** The proposed fix assumes one multithreaded process; tradekit is many short-lived CLI processes — an in-memory queue serializes nothing across them. Accepted mitigations: bounded retry-with-jitter on `ledger.append`, scouts write wiki files not events; escalation path is the Phase-2 single-writer daemon (already planned, TD-19) | TD-16, §14 |
| G5 | Exact-touch limit fills are optimistic; at-touch retail limits often rest unexecuted | **Accepted.** Paper limit fills require trade-through ≥1 tick. Resolves former open question Q2 | §8.3 |
| G6 | Derivatives fallback: Kraken Futures public tickers (funding + OI, no auth, US-accessible) primary; Coinalyze free API secondary cross-check | **Accepted.** Also, per Mike: futures *signals* deprioritized below stocks/crypto → implementation moves to Phase 3 (port designed now). Resolves former open question Q1 | TD-12, §9.1, §17 |

Reviewer's closing question (R-013 threshold + cross-asset correlation methodology) answered in DESIGN §9.1 (new correlation-methodology bullet): |r| > 0.75 flag on 30-day Pearson of daily log-returns, inner-joined on UTC days where both assets have bars; <20 overlapping observations → `insufficient_overlap`, treated as unmeasured (requires review flag, never a silent pass).

## Verbatim review

This is an exceptionally well-thought-out design document. Transitioning from standard state management to a purely event-sourced, append-only architecture is a heavy lift, but you've nailed the structural boundaries. Building a system where state is just a projection of immutable facts is exactly how institutional trading desks guarantee auditability. It is particularly elegant how this maps to multi-agent orchestration—having a single, cryptographic source of truth keeps disparate LLM agents mathematically grounded.

Here is my rigorous review of the architecture, highlighting the fortifications you've successfully built, followed by the mathematical and structural gaps that need addressing before this touches live capital.

---

### The Fortifications: What is exceptionally well-designed

* **The Two-Phase Order Pipeline (TD-5 / §8.2):** This is the crown jewel of your security model. Forcing the policy engine to evaluate the `ProposedAction` and ledger the `VerdictIssued` event *before* the broker executes is flawless. It makes rogue agent execution structurally impossible through the approved interface.
* **Grading as Pure Arithmetic (§10.2):** Moving subjective grading entirely into a deterministic predicate DSL prevents the LLM from hallucinating its win rate. The strict `VOID` gaming guards (requiring attestation *and* secondary sign-off) are exactly how you prevent an agent from aggressively culling its losers to pad its stats.
* **The Cost Model Singularity (TD-8):** Forcing the paper broker, backtester, and metrics engine to share the exact same `tradekit.costs` module is a vital defense against simulation optimism. Too many systems bleed edge because their backtester assumes zero spread while paper trading pays taker fees.

---

### The Vulnerabilities: Gaps, Ambiguities, and Solutions

#### 1. The DSR Small-Sample Breakdown (Answers your Q3)

Your document correctly flags an issue with using the Deflated Sharpe Ratio (DSR) on small sample sizes (n=10 to 30), but the mathematical reality is harsher than a simple "penalty." DSR relies on the Probabilistic Sharpe Ratio (PSR), which calculates the variance of the sample Sharpe ratio using higher-order moments—specifically skewness (γ̂₃) and kurtosis (γ̂₄):

PSR = Φ( ((SR − SR*) √(n−1)) / √(1 − γ̂₃·SR + ((γ̂₄ − 1)/4)·SR²) )

**The Issue:** At n < 30, sample skew and kurtosis are wildly unstable. A single outlier trade will detonate the γ̂₄ term, artificially collapsing the estimated variance and causing the PSR (and subsequently the DSR) to throw massive false positives or negatives. The standard normal approximation Φ fundamentally breaks down here.
**The Solution:** Do not gate on DSR until a strategy hits n ≥ 30. For the n=10 to n=29 regime, rely strictly on a Penalized Sharpe Ratio where you artificially haircut the observed return by a factor of 1/√n and enforce strict upper bounds on max drawdown. Once n ≥ 30, DSR unlocks as the canonical gate.

#### 2. The float64 to Decimal Boundary (§13)

**The Issue:** You explicitly state that `float` is allowed in `mae._indicators`/`_metrics`, but `Decimal` is enforced for money and quantities at the contract boundary. Converting a NumPy `float64` directly back to `Decimal` can introduce microscopic floating-point noise (e.g., 10.05 becoming 10.049999999999999). If a success predicate is checking for a strict `gte` evaluation, this noise can fail a winning thesis.
**The Solution:** Introduce a strict `quantize` utility at the boundary where MAE data enters the ledger or policy engine. The quantization must be dynamically tied to the asset's tick size (e.g., 0.01 for equities, 0.0001 for specific crypto pairs).

#### 3. HMM Regime Blindness (§9.2)

**The Issue:** You are persisting the Gaussian HMM model and only refitting weekly to ensure determinism. However, financial regimes are non-stationary. If a massive macroeconomic shock occurs on a Tuesday, a weekly-fitted HMM will confidently output a "low volatility trend" regime while the market is in freefall, blinding your sizing logic.
**The Solution:** Implement a deterministic intraday circuit breaker. Keep the weekly HMM, but run an exponentially weighted moving average (EWMA) of realized volatility alongside it. If current intraday volatility deviates by more than 3σ from the HMM's expected state variance, force an immediate override to a "high-volatility/risk-off" regime payload, bypassing the stale weekly fit.

#### 4. Concurrency Under Multi-Agent Pressure (§14)

**The Issue:** You rely on SQLite WAL mode and `busy_timeout` to handle concurrency. While this works well for standard procedural workloads, multi-agent frameworks often trigger bursty, asynchronous write storms (e.g., multiple scouts attempting to log memory, combined with policy evaluations and metric writes). `busy_timeout` will eventually throw `OperationalError: database is locked` under simultaneous contention in Python.
**The Solution:** Decouple the write path. All read models can query SQLite concurrently, but force all mutating actions (events) through an isolated, single-threaded write queue (even an in-memory `queue.Queue` fed into a dedicated writer loop in the CLI lifecycle). Guarantee absolute serialization before it hits the disk.

#### 5. Paper-Fill Realism Limits (Answers your Q2)

**The Issue:** Your paper broker assumes a limit order fills when a bar's `[low, high]` crosses the limit price. At $10-$25 notionals, your assumption that queue position doesn't matter is absolutely correct. Liquidity is essentially infinite for you. However, *spread crossing* is not.
**The Solution:** If a bar's low *exactly touches* your limit price, do not assume a fill. Retail limits at the exact touch often rest unexecuted because the bid/ask spread didn't actually sweep through the limit. Require the bar to trade *through* your limit price by at least one minimum tick increment to guarantee the fill in simulation.

#### 6. Derivatives Fallback Chain (Answers your Q1)

Kraken Futures public endpoints (`/derivatives/api/v3/tickers`) are excellent and highly reliable for US IP addresses—they give you clean funding rates and aggregate open interest without auth overhead. If you need a secondary aggregator for cross-checking, Coinalyze's free API is the industry-standard fallback for retail quants looking for aggregate OI and liquidations. Stick to Kraken Futures as the primary fallback when Binance `fapi` blocks you.

---

The separation of concerns here is incredibly clean, and the defensive posture of the architecture gives it a strong foundation.

To help me give you better feedback on the policy logic, what is your current threshold for the `R-013` correlation cap, and how are you calculating correlation across differing asset classes in the MAE?
