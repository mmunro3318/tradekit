# Market Analysis Engine — Comprehensive Design Document
> Codex build target: a Python MCP server / importable library for AI-driven market analysis across crypto and equities. No paid subscriptions required for core functionality.

***

## Executive Summary

This document is the complete specification for **MAE** (Market Analysis Engine) — a tool designed to be called by an LLM agent (Claude, Codex, GPT-4o, etc.) during a live session to analyze market conditions, identify setups, size positions, evaluate strategy performance, and return structured JSON. It functions as both an importable Python library and an on-demand FastMCP server. All data sources are free or free-tier. Kraken Pro (authenticated) is used for live crypto execution data.[^1]

***

## 1. Architecture Overview

```
┌────────────────────────────────────────────────────────┐
│                  AI Agent (LLM Session)                │
│  calls tools via: Python import OR MCP tool invocation │
└────────────────┬───────────────────────────────────────┘
                 │
┌────────────────▼───────────────────────────────────────┐
│              MAE Public API  (mcp_server.py)            │
│  scan_markets · get_regime · compute_metrics            │
│  get_derivatives · size_position · get_correlation      │
└──────┬─────────────────────┬──────────────────┬────────┘
       │                     │                  │
┌──────▼──────┐   ┌──────────▼────────┐  ┌─────▼──────────┐
│  data/      │   │  indicators/      │  │  risk/         │
│  Fetchers   │   │  TA Engine        │  │  Sizing        │
└──────┬──────┘   └──────────┬────────┘  └─────┬──────────┘
       │                     │                  │
┌──────▼──────────────────────▼──────────────────▼────────┐
│                    External APIs                         │
│  Kraken · Binance · Alpaca · CoinGecko · yfinance        │
└──────────────────────────────────────────────────────────┘
```

**Protocol choice:** FastMCP over `stdio` transport for local use; `sse` (HTTP SSE) transport for remote/headless deployment. The MCP layer is a thin decorator wrapper — business logic lives in pure Python modules callable without MCP at all.[^1]

**Session memory strategy:** MCP tool definitions are *not* loaded into every AI session. A compact skill descriptor (plain text, ~200 tokens) tells the AI how to start the server and which tools exist. Full tool schemas load only when the agent invokes the skill. This keeps base context clean.[^2][^3]

***

## 2. External APIs — Selection, Contracts & Access Flows

### 2.1 API Selection Rationale

| API | Purpose | Auth Required | Cost |
|---|---|---|---|
| **Kraken REST + WebSocket v2** | Crypto OHLCV, L2 orderbook, trades, funding rates, OI (authenticated for private) | Public endpoints: none. Private (orders/account): API key | Free (account required for private)[^4] |
| **Binance Futures REST** | Funding rate history, mark price, open interest (public) | None for market data | Free, no key needed[^5] |
| **Alpaca Markets API** | US equities OHLCV (historical + real-time), crypto via Alpaca | API key (free account) | Free tier: unlimited historical bars, real-time SIP data[^6][^7] |
| **CoinGecko API v3** | Coin metadata, market caps, dominance, global market data | API key (Demo plan) | Free: 100 req/min[^8] |
| **yfinance** | Macro indices (SPX, VIX, DXY, NDX), fallback equity OHLCV | None (unofficial Yahoo Finance wrapper) | Free; ~2,000 req/hr[^9] — use for batch/daily data only, not real-time[^10] |
| **CoinMarketCap Basic** | Broad market cap rankings, sector rotations | API key (free Basic plan) | Free: 15,000 credits/month[^11] |

> **Coinglass note:** Coinglass has no free API tier. For liquidation heatmap and advanced OI data, use Binance Futures + Kraken public endpoints and build the aggregation layer internally. Coinglass is listed as an optional paid upgrade path (Hobbyist: $29/mo).[^12][^13]

***

### 2.2 Kraken API

**Base URL (REST):** `https://api.kraken.com/0`
**WebSocket v2:** `wss://ws.kraken.com/v2` (public) | `wss://ws-auth.kraken.com/v2` (private)[^14]

Kraken's real-time feeds — ticker, L2 order book, trades, OHLCV — require **no authentication**. L3 order data and all private (account/order) endpoints require a signed API key from your Kraken Pro account.[^15][^4]

**Access Flow:**

```
Step 1 — Key setup (private endpoints only):
  Kraken Pro → Account → Security → API → Create Key
  Permissions needed: Query Funds, Query Open Orders, Create/Cancel Orders
  Store as: KRAKEN_API_KEY, KRAKEN_API_SECRET in .env

Step 2 — Public market data (no key):
  GET /0/public/OHLC?pair=XBTUSD&interval=60
    → Returns: time, open, high, low, close, vwap, volume, count
    → Max 720 candles per call

  GET /0/public/Depth?pair=XBTUSD&count=50
    → Returns: asks[], bids[] each as [price, volume, timestamp]

  GET /0/public/Trades?pair=XBTUSD&since=<unix>
    → Returns: array of [price, volume, time, buy/sell, market/limit]
    → Used for CVD computation

  WebSocket subscription (real-time, no auth):
    {"method": "subscribe", "params": {"channel": "ohlc", "symbol": ["BTC/USD"], "interval": 1}}
    {"method": "subscribe", "params": {"channel": "trade", "symbol": ["BTC/USD"]}}
    {"method": "subscribe", "params": {"channel": "book", "symbol": ["BTC/USD"], "depth": 25}}
   

Step 3 — Futures / derivatives (authenticated, Kraken Futures sub-account):
  GET /derivatives/api/v3/instruments/<symbol>/fundingrate
  GET /derivatives/api/v3/openinterest
    → Requires separate Kraken Futures API key
```

**Rate limits:** Decay model — standard REST 15–20 calls/sec public; escalating cost per private order action. Monitor `X-Ratelimit-*` headers.[^15]

***

### 2.3 Binance Futures REST API (Public Market Data)

**Base URL:** `https://fapi.binance.com`
No API key required for all market data endpoints listed below.[^5]

**Access Flow:**

```
Funding rate history:
  GET /fapi/v1/fundingRate?symbol=BTCUSDT&limit=100
  → Returns: [{symbol, fundingTime, fundingRate, markPrice}]
  → Rate limit: 500 req/5min/IP shared bucket

Open interest:
  GET /fapi/v1/openInterest?symbol=BTCUSDT
  → Returns: {symbol, openInterest, time}

  GET /futures/data/openInterestHist?symbol=BTCUSDT&period=5m&limit=500
  → Returns: [{symbol, sumOpenInterest, sumOpenInterestValue, timestamp}]

Long/short ratio:
  GET /futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=5m&limit=500

Top-trader ratio:
  GET /futures/data/topLongShortPositionRatio?symbol=BTCUSDT&period=5m&limit=500

Liquidation orders (real-time WebSocket):
  wss://fstream.binance.com/ws/btcusdt@forceOrder
  → Streams forced liquidation events with side, price, qty

OHLCV (public, no auth):
  GET /fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=500
```

**Usage note:** Binance is the deepest open-interest and funding rate dataset available free. Use it as the primary derivatives signal source; Kraken Futures supplements for Kraken-specific positioning.[^16]

***

### 2.4 Alpaca Markets API

**Base URL (data):** `https://data.alpaca.markets/v2`
**Base URL (trading):** `https://api.alpaca.markets/v2`
Authentication: `APCA-API-KEY-ID` and `APCA-API-SECRET-KEY` headers.[^6]

**Free account:** Sign up at alpaca.markets → API Keys (sidebar). Paper trading account is auto-provisioned. Free tier includes real-time SIP stock data and historical bars (7+ years).[^7]

**Access Flow:**

```
Historical equity bars:
  GET /v2/stocks/{symbol}/bars
    ?timeframe=1Day&start=2023-01-01&end=2024-01-01&feed=sip&limit=1000
  Headers: APCA-API-KEY-ID, APCA-API-SECRET-KEY
  → Returns: {bars: [{t, o, h, l, c, v, n, vw}], symbol, next_page_token}
  Note: Use bars.df for pandas DataFrame; `in` operator on BarSet returns False

Real-time equity quotes (WebSocket):
  wss://stream.data.alpaca.markets/v2/sip
  Auth message: {"action":"auth","key":"...","secret":"..."}
  Subscribe: {"action":"subscribe","quotes":["AAPL","SPY"]}

Crypto OHLCV via Alpaca:
  GET /v2/crypto/us/bars
    ?symbols=BTC/USD&timeframe=1Hour&start=...
  → Same structure; Alpaca crypto feed covers BTC, ETH, major pairs

Macro indices (via yfinance fallback — Alpaca does not carry ^VIX, ^DXY):
  Use yfinance.download("^VIX", period="6mo") for batch daily pulls
```

**Rate limits:** Free tier: 200 req/min REST; WebSocket: unlimited subscriptions.[^7]

***

### 2.5 CoinGecko API v3

**Base URL:** `https://api.coingecko.com/api/v3`
Auth: `x-cg-demo-api-key` header (Demo plan key from coingecko.com/en/api).[^17]

**Access Flow:**

```
Global market data (BTC dominance, total market cap):
  GET /global
  → Returns: {total_market_cap, total_volume, market_cap_percentage{btc,eth,...}}
  Use: dominance shifts signal altcoin rotation events

Coin market data (batch, up to 250):
  GET /coins/markets
    ?vs_currency=usd&order=market_cap_desc&per_page=100&page=1&sparkline=false
  → Returns: [{id, symbol, current_price, market_cap, total_volume, price_change_percentage_24h}]

Historical OHLCV (free, daily granularity > 90 days):
  GET /coins/{id}/ohlc?vs_currency=usd&days=30
  → Returns: [[timestamp, open, high, low, close]]
  Limit: hourly data available for last 90 days only on free tier

Rate limits: 100 req/min on Demo plan
Batch strategy: Fetch /coins/list once → cache IDs → query /coins/markets in pages
```

***

### 2.6 yfinance (Macro / Fallback)

**Install:** `pip install yfinance>=0.2.54` (0.2.54+ fixes rate-limit bugs)[^9]

**Access Flow:**

```python
import yfinance as yf

# Macro indices
macro_tickers = ["^GSPC", "^VIX", "^DXY", "^NDX", "GLD", "TLT"]
data = yf.download(macro_tickers, period="6mo", interval="1d", auto_adjust=True)
# Returns MultiIndex DataFrame: (Price, Ticker)

# Single ticker detailed
spy = yf.Ticker("SPY")
hist = spy.history(period="1y", interval="1h")
info = spy.info  # P/E, market cap, sector, etc.
```

**Caveats:** 15–20 min delayed during US market hours; unofficial API — fragile for production real-time. Use only for: macro index daily closes, sector ETF historical bars, fallback equity OHLCV when Alpaca is unavailable.[^10]

***

## 3. MAE Public API Contract

The tool exposes six callable surfaces. All inputs/outputs are typed Python dicts (JSON-serializable). Each is usable via `import market_analysis` or via MCP tool invocation.

***

### `scan_markets`

**Purpose:** Screen a universe of assets for setups matching specified TA conditions across timeframes. The primary *discovery* entrypoint.

**Input:**
```python
{
  "asset_class": "crypto" | "equity" | "macro",
  "symbols": ["BTC/USD", "ETH/USD", ...],  # omit for full universe scan
  "timeframes": ["1h", "4h", "1d"],
  "filters": {
    "rsi_max": 35,           # optional: RSI below threshold (oversold)
    "rsi_min": None,
    "macd_signal": "bullish_cross" | "bearish_cross" | None,
    "bb_position": "below_lower" | "above_upper" | None,
    "volume_spike": 2.0,     # optional: volume > N × 20-period avg
    "atr_percentile_min": 40 # optional: min ATR percentile (volatility gate)
  },
  "regime_gate": True        # if True, pre-filter by HMM regime compatibility
}
```

**Output:**
```python
{
  "scan_ts": "2026-07-12T05:00:00Z",
  "regime_context": {"state": "low_vol_trend", "confidence": 0.82},
  "matches": [
    {
      "symbol": "BTC/USD",
      "timeframe": "4h",
      "price": 67420.5,
      "rsi": 32.1,
      "macd_hist": -120.4,
      "atr": 1850.2,
      "atr_pct_of_price": 0.027,
      "volume_ratio": 2.3,
      "signal_tags": ["oversold", "volume_spike", "at_support"]
    }
  ]
}
```

**Internal pipeline:** Fetch OHLCV (Kraken/Alpaca) → compute indicators → apply filters → prepend regime state from `get_regime`.

***

### `get_regime`

**Purpose:** Classify the current market regime for a symbol using a Hidden Markov Model. Called automatically inside `scan_markets` when `regime_gate=True`; also callable directly when the agent needs regime context before formulating a thesis.[^18][^19]

**Input:**
```python
{
  "symbol": "BTC/USD",
  "lookback_days": 90,    # training window
  "n_states": 3           # 2 = trend/chop, 3 = trend/chop/breakdown
}
```

**Output:**
```python
{
  "symbol": "BTC/USD",
  "current_state": "low_vol_trend" | "high_vol_chop" | "breakdown",
  "state_index": 0 | 1 | 2,
  "confidence": 0.82,       # P(current state | observations)
  "state_metrics": {
    "annualized_vol": 0.42,
    "mean_return_daily": 0.0015,
    "avg_state_duration_days": 18
  },
  "recommended_strategies": ["momentum", "breakout"],
  "avoid_strategies": ["mean_reversion"]
}
```

**Internal pipeline:** Pull daily OHLCV → compute log-returns + realized vol → fit `hmmlearn.GaussianHMM` → decode most probable state sequence → return current state + P(state).

***

### `get_derivatives_context`

**Purpose:** Return perpetual futures market structure signals for a crypto symbol. Called before entering any leveraged crypto trade to detect crowded positioning, liquidation cluster proximity, and funding carry.

**Input:**
```python
{
  "symbol": "BTCUSDT",       # Binance futures symbol format
  "lookback_periods": 48     # periods of funding rate + OI history
}
```

**Output:**
```python
{
  "symbol": "BTCUSDT",
  "funding_rate_current": 0.00031,
  "funding_rate_annualized": 0.34,   # current_rate × 3 × 365
  "funding_trend": "rising" | "falling" | "neutral",
  "open_interest_usd": 14_200_000_000,
  "oi_trend": "rising" | "falling",
  "positioning_signal": "overleveraged_longs" | "overleveraged_shorts" | "balanced",
  "long_short_ratio": 1.24,
  "liquidation_clusters": [
    {"price": 65000, "liq_volume_usd": 340_000_000, "direction": "longs"},
    {"price": 70500, "liq_volume_usd": 180_000_000, "direction": "shorts"}
  ],
  "carry_signal": "pay_long" | "pay_short" | "neutral",
  "risk_assessment": "elevated_long_squeeze_risk" | "elevated_short_squeeze_risk" | "low"
}
```

**Internal pipeline:** Binance `/fapi/v1/fundingRate` → `/futures/data/openInterestHist` → `/futures/data/globalLongShortAccountRatio` → aggregate → classify per signal matrix.[^20][^21]

***

### `compute_strategy_metrics`

**Purpose:** Evaluate a completed or running strategy's statistical edge from a trade log. Called by the agent to validate a thesis before scaling, or to audit performance periodically.

**Input:**
```python
{
  "trade_log": [
    {
      "entry_ts": "2026-01-10T14:00:00Z",
      "exit_ts":  "2026-01-11T09:30:00Z",
      "entry_price": 66500.0,
      "exit_price":  68200.0,
      "side": "long" | "short",
      "size_usd": 5000.0,
      "fees_usd": 8.4
    }
  ],
  "risk_free_rate_annual": 0.045,  # US 3-month T-bill yield
  "mar": 0.0                       # minimum acceptable return for Sortino
}
```

**Output:**
```python
{
  "n_trades": 47,
  "win_rate": 0.574,
  "avg_win_usd": 312.4,
  "avg_loss_usd": 198.7,
  "expectancy_per_trade": 0.574 * 312.4 - 0.426 * 198.7,   # = +94.3 USD
  "profit_factor": 1.87,
  "sharpe_annual": 1.94,
  "sortino_annual": 2.61,
  "calmar_ratio": 3.12,
  "max_drawdown_pct": 0.143,
  "max_drawdown_usd": 714.5,
  "total_pnl_usd": 4431.2,
  "total_fees_usd": 394.8,
  "net_pnl_usd": 4036.4,
  "avg_hold_hours": 18.4,
  "edge_verdict": "positive" | "marginal" | "negative",
  "warnings": ["sample_size_small: n<50", "overfit_risk: PF>3"]
}
```

**Formulas applied**:[^22][^23][^24][^25][^26]

\[
E = (W \times \bar{W}) - ((1-W) \times \bar{L})
\]
\[
PF = \frac{\sum \text{wins}}{\sum |\text{losses}|}
\]
\[
S_A = \sqrt{365} \cdot \frac{\bar{R}_a - R_f}{\sigma_a}
\]
\[
Sortino = \frac{\bar{R}_p - MAR}{\sigma_d}
\]
\[
Calmar = \frac{CAGR}{|MDD|}
\]

**Internal pipeline:** Pure Python/NumPy; no external API calls. Fully offline.

***

### `size_position`

**Purpose:** Compute risk-appropriate position size using ATR-normalized and Kelly methods. Called immediately after a setup is confirmed — before any order.

**Input:**
```python
{
  "symbol": "BTC/USD",
  "account_equity_usd": 25000.0,
  "risk_pct_per_trade": 0.01,       # 1% of equity at risk
  "atr_multiplier": 2.0,            # stop distance = ATR × multiplier
  "kelly_win_rate": 0.574,          # from compute_strategy_metrics
  "kelly_payoff_ratio": 1.572,      # avg_win / avg_loss
  "kelly_fraction": 0.25            # quarter-Kelly default
}
```

**Output:**
```python
{
  "symbol": "BTC/USD",
  "current_price": 67420.5,
  "atr_14": 1850.2,
  "stop_distance_usd": 3700.4,      # ATR × multiplier
  "stop_pct": 0.0549,
  "atr_position_size_usd": 6757.8,  # (equity × risk_pct) / stop_distance × price
  "atr_units": 0.1002,              # size in base asset
  "kelly_full_f": 0.2102,           # f* = W - (1-W)/R
  "kelly_quarter_f": 0.0526,
  "kelly_position_size_usd": 1314.0,
  "recommended_size_usd": 1314.0,   # min(ATR size, Kelly size) — conservative
  "recommended_units": 0.0195,
  "risk_usd": 250.0,                # equity × risk_pct
  "r_multiple_target": 2.0          # default TP = 2× stop distance
}
```

**Formulas**:[^27][^28][^29][^30]

\[
\text{Size}_{ATR} = \frac{E \times r\%}{ATR \times m}
\]
\[
f^* = W - \frac{1-W}{R}
\]

**Internal pipeline:** Fetch latest ATR (from OHLCV via Kraken/Alpaca) → compute both sizing methods → return the *minimum* of the two as the conservative default.

***

### `get_correlation_matrix`

**Purpose:** Compute rolling Pearson correlation across a symbol set. Called when constructing a portfolio, validating that a new position adds diversification, or detecting regime-driven correlation breakdown.

**Input:**
```python
{
  "symbols": ["BTC/USD", "ETH/USD", "SPY", "^VIX", "GLD"],
  "window_days": 30,
  "timeframe": "1d"
}
```

**Output:**
```python
{
  "window_days": 30,
  "as_of": "2026-07-12",
  "matrix": {
    "BTC/USD": {"BTC/USD": 1.0, "ETH/USD": 0.89, "SPY": 0.43, "^VIX": -0.31, "GLD": 0.12},
    "ETH/USD": {"BTC/USD": 0.89, "ETH/USD": 1.0, ...},
    ...
  },
  "high_correlation_warnings": [
    {"pair": ["BTC/USD", "ETH/USD"], "r": 0.89, "note": "near-redundant exposure"}
  ]
}
```

**Internal pipeline:** Fetch daily close from Kraken (crypto) + Alpaca/yfinance (equities/macro) → align dates → `pandas.DataFrame.corr()` → flag pairs with |r| > 0.75.

***

## 4. Module Architecture

```
market_analysis/
├── __init__.py               # re-exports all public API functions
├── mcp_server.py             # FastMCP thin wrapper (optional)
├── config.py                 # env var loading (KRAKEN_*, APCA_*, etc.)
│
├── data/
│   ├── kraken.py             # REST + WebSocket OHLCV, orderbook, trades
│   ├── binance.py            # Futures: funding rate, OI, liq orders
│   ├── alpaca.py             # Equities + crypto bars; real-time quotes
│   ├── coingecko.py          # Market caps, dominance, metadata
│   └── macro.py              # yfinance: SPX, VIX, DXY, GLD, TLT
│
├── indicators/
│   ├── momentum.py           # RSI, MACD, Stoch RSI, Rate of Change
│   ├── trend.py              # EMA/SMA, ADX, Supertrend, Ichimoku
│   ├── volatility.py         # ATR (Wilder), Bollinger Bands, Keltner
│   ├── volume.py             # CVD, VWAP, OBV, Volume Profile
│   └── structure.py          # S/R levels, QFL base detection
│
├── regime/
│   └── hmm.py                # hmmlearn GaussianHMM; 2–3 state model
│
├── signals/
│   ├── scanner.py            # Multi-asset, multi-TF screener
│   └── patterns.py           # Candlestick pattern recognition
│
├── risk/
│   ├── sizing.py             # Kelly + ATR-normalized position sizing
│   └── portfolio.py          # Correlation matrix, drawdown tracker
│
├── metrics/
│   └── strategy.py           # Sharpe, Sortino, Calmar, PF, Expectancy
│
└── backtest/
    └── engine.py             # Vectorized sim; slippage + fee model
```

***

## 5. Feature Usage Guide — When Each Feature is Called

This section defines *who* calls each feature (the LLM agent externally, or the pipeline internally) and *when* it belongs in the workflow.

### 5.1 Agent-Callable (External Surface)

These six tools are the only surfaces exposed through the MCP API or library public interface. The LLM invokes these directly.

| Tool | When Agent Calls It | Typical Trigger |
|---|---|---|
| `scan_markets` | Start of an analysis session — "find setups now" | "Screen crypto for oversold RSI + volume spike on 4H" |
| `get_regime` | Before forming a directional thesis on any symbol | "What regime is BTC in before I run momentum strats?" |
| `get_derivatives_context` | Before any crypto leveraged position | "Check if funding is extreme before I enter ETH long" |
| `compute_strategy_metrics` | After accumulating a trade log (≥20 trades), or on demand for audit | "Evaluate my last 60 trades for edge" |
| `size_position` | Immediately after a setup is confirmed, before order | "Size my BTC position given my edge metrics" |
| `get_correlation_matrix` | Portfolio construction; before adding a correlated asset | "How correlated are my current positions?" |

### 5.2 Internal Pipeline (Never Agent-Facing)

These functions are called automatically *within* the above tools. The agent has no reason to invoke them directly; they are not exposed as MCP tools.

| Internal Function | Called By | Purpose |
|---|---|---|
| `data.kraken.get_ohlcv()` | `scan_markets`, `get_regime`, `size_position`, `get_correlation_matrix` | Fetch OHLCV bars for any crypto pair |
| `data.kraken.stream_trades()` | `indicators.volume.compute_cvd()` | Tick-level trade stream for CVD |
| `data.binance.get_funding_rate()` | `get_derivatives_context` | Binance perpetual funding rate history |
| `data.binance.get_open_interest()` | `get_derivatives_context` | OI history + current |
| `data.binance.get_long_short_ratio()` | `get_derivatives_context` | Global L/S positioning |
| `data.alpaca.get_bars()` | `scan_markets` (equities), `get_correlation_matrix` | Equity + macro OHLCV |
| `data.coingecko.get_global()` | `scan_markets` (when `asset_class="crypto"`) | BTC dominance shift detection |
| `data.macro.get_index()` | `get_correlation_matrix`, `get_regime` (cross-asset) | SPX, VIX, DXY daily data |
| `indicators.volatility.atr()` | `size_position`, `scan_markets` (ATR filter) | ATR computation (Wilder smoothing) |
| `indicators.momentum.rsi()` | `scan_markets` | RSI computation |
| `indicators.volume.cvd()` | `scan_markets` (order flow divergence filter) | Cumulative Volume Delta |
| `indicators.volume.vwap()` | `scan_markets` | VWAP vs. price position |
| `regime.hmm.classify()` | `get_regime`, `scan_markets` (when `regime_gate=True`) | HMM state classification |
| `risk.sizing.kelly()` | `size_position` | Full Kelly calculation |
| `risk.sizing.atr_normalized()` | `size_position` | ATR-based stop/size |
| `risk.portfolio.drawdown()` | `compute_strategy_metrics` | MDD calculation from equity curve |
| `metrics.strategy.sharpe()` | `compute_strategy_metrics` | Sharpe ratio (annualized) |
| `metrics.strategy.sortino()` | `compute_strategy_metrics` | Sortino ratio (downside deviation) |
| `metrics.strategy.calmar()` | `compute_strategy_metrics` | Calmar ratio (CAGR / MDD) |
| `metrics.strategy.expectancy()` | `compute_strategy_metrics` | Per-trade expected value |
| `indicators.structure.qfl_bases()` | `scan_markets` (structure filter) | QFL support base detection |

***

## 6. MCP Server Implementation

```python
# mcp_server.py
from fastmcp import FastMCP
from market_analysis import (
    scan_markets, get_regime, get_derivatives_context,
    compute_strategy_metrics, size_position, get_correlation_matrix
)

mcp = FastMCP(
    name="market-analysis",
    instructions="""
    Market Analysis Engine. Use for: screening setups (scan_markets),
    regime classification (get_regime), derivatives risk (get_derivatives_context),
    strategy evaluation (compute_strategy_metrics), position sizing (size_position),
    and portfolio correlation (get_correlation_matrix).
    Call get_regime first on any new symbol before running scans or sizing.
    """
)

@mcp.tool
async def scan_markets(asset_class: str, timeframes: list[str], filters: dict,
                       symbols: list[str] = None, regime_gate: bool = True) -> dict: ...

@mcp.tool
async def get_regime(symbol: str, lookback_days: int = 90, n_states: int = 3) -> dict: ...

@mcp.tool
async def get_derivatives_context(symbol: str, lookback_periods: int = 48) -> dict: ...

@mcp.tool
async def compute_strategy_metrics(trade_log: list[dict],
                                   risk_free_rate_annual: float = 0.045,
                                   mar: float = 0.0) -> dict: ...

@mcp.tool
async def size_position(symbol: str, account_equity_usd: float,
                        risk_pct_per_trade: float = 0.01,
                        atr_multiplier: float = 2.0,
                        kelly_win_rate: float = None,
                        kelly_payoff_ratio: float = None,
                        kelly_fraction: float = 0.25) -> dict: ...

@mcp.tool
async def get_correlation_matrix(symbols: list[str],
                                 window_days: int = 30,
                                 timeframe: str = "1d") -> dict: ...

if __name__ == "__main__":
    mcp.run()  # stdio transport (local); add transport="sse" for remote
```

**Launch:** `python -m market_analysis.mcp_server`

***

## 7. Agent Skill Descriptor

Load this in an AI system prompt or skill file (~200 tokens). Full MCP tool schemas load only when the server is started.

```
SKILL: market_analysis
VERSION: 1.0
START_CMD: python -m market_analysis.mcp_server
TRANSPORT: stdio

TOOLS:
  scan_markets          — discover setups across assets/timeframes
  get_regime            — classify HMM market regime for a symbol
  get_derivatives_context — crypto perpetuals: funding, OI, liquidations
  compute_strategy_metrics — evaluate trade log: Sharpe, Sortino, Calmar, Expectancy
  size_position         — ATR + Kelly position sizing
  get_correlation_matrix — rolling correlation across symbol set

RECOMMENDED WORKFLOW:
  1. get_regime(symbol)              → confirm market state
  2. scan_markets(filters)           → candidate symbols
  3. get_derivatives_context(symbol) → no positioning trap?
  4. size_position(symbol, equity)   → set position size
  5. compute_strategy_metrics(log)   → validate edge (run periodically)
  6. get_correlation_matrix(symbols) → check portfolio redundancy

REQUIRED ENV VARS:
  KRAKEN_API_KEY, KRAKEN_API_SECRET   (private endpoints only)
  APCA_API_KEY_ID, APCA_API_SECRET_KEY
  COINGECKO_API_KEY
```

***

## 8. Environment Setup

```bash
# Install
pip install fastmcp ccxt hmmlearn pandas numpy yfinance alpaca-py requests websockets python-dotenv

# .env
KRAKEN_API_KEY=your_key
KRAKEN_API_SECRET=your_secret
APCA_API_KEY_ID=your_key
APCA_API_SECRET_KEY=your_secret
COINGECKO_API_KEY=your_demo_key
# CMC_API_KEY=your_key   # optional
```

***

## 9. Build Order

1. `config.py` + `data/kraken.py` — OHLCV, orderbook, trade stream
2. `data/binance.py` — funding rate, OI, liquidation orders (no key required)
3. `data/alpaca.py` — equity bars + real-time
4. `indicators/` — ATR, RSI, MACD, CVD, VWAP (core compute layer)
5. `metrics/strategy.py` — standalone; no data dependency, testable immediately
6. `risk/sizing.py` — Kelly + ATR sizing
7. `regime/hmm.py` — HMM classifier; integrate as gate
8. `signals/scanner.py` — multi-TF screener, regime-gated
9. `data/coingecko.py` + `data/macro.py` — supplementary data
10. `risk/portfolio.py` + `get_correlation_matrix` — portfolio layer
11. `backtest/engine.py` — vectorized sim with fees/slippage
12. `mcp_server.py` — FastMCP wrapper; final integration

***

## 10. Footnotes

¹ **MCP (Model Context Protocol):** Anthropic's open standard for giving AI clients structured access to external tools; each tool is a typed, callable function the model invokes via JSON-RPC.

² **CVD (Cumulative Volume Delta):** Net sum of aggressive buy minus sell volume; computed from tick-level trades. Divergence from price is a leading order-flow warning.[^31]

³ **HMM (Hidden Markov Model):** Probabilistic sequence model where market "regime" is a latent state; Baum-Welch EM algorithm fits emission parameters from observed returns/vol.[^19][^18]

⁴ **Kelly Criterion:** `f* = W − (1−W)/R`; optimizes long-run geometric growth. Quarter-Kelly is the practitioner default.[^28][^27]

⁵ **ATR (Average True Range):** Wilder-smoothed mean of `max(H−L, |H−C₋₁|, |L−C₋₁|)`; the canonical volatility-normalized stop and position-sizing basis[^32][^29].

⁶ **Calmar Ratio:** `CAGR / |MDD|`; favored where tail risk dominates over daily vol[^24].

⁷ **Regime:** Semi-persistent market state with distinct return, vol, and correlation profile. Momentum alpha decays in high-vol chop; mean-reversion underperforms in trending regimes.[^18]

⁸ **Sortino Ratio:** Like Sharpe but penalizes only downside deviation, not upside vol — more honest for skewed return distributions.[^23]

---

## References

1. [How to Create an MCP Server in Python](https://gofastmcp.com/tutorials/create-mcp-server) - A step-by-step guide to building a Model Context Protocol (MCP) server using Python and FastMCP, fro...

2. [MCP tool design: Practical approaches and tradeoffs](https://aws.amazon.com/blogs/machine-learning/mcp-tool-design-practical-approaches-and-tradeoffs/) - Includes runtime hosting, gateway for multi-server tool discovery, and persistent memory across sess...

3. [Client Best Practices](https://modelcontextprotocol.io/docs/develop/clients/client-best-practices) - MCP Servers can provide an optional outputSchema for each tool. When an output schema is present, th...

4. [Kraken API Unlocked — the market data feeds systematic ...](https://blog.kraken.com/product/api/unlocked-3-the-market-data-feeds-systematic-traders-use) - Kraken's real-time market data feeds (ticker, order book (L2), trades, and OHLCV) do not require aut...

5. [Get Funding Rate History | Binance Open Platform](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History) - REST API; Get Funding Rate History. On this page. Get Funding Rate History. API ... Request Weight​....

6. [About Market Data API](https://docs.alpaca.markets/us/docs/about-market-data-api) - Gain seamless access to a wealth of data with Alpaca Market Data API, offering real-time and histori...

7. [Unlimited Access, Real-time Market Data API](https://alpaca.markets/data) - Trading API. Real-Time Stock, Options and Crypto Market Data. Developer-first API with up to 10,000 ...

8. [Crypto API Pricing Plans](https://www.coingecko.com/en/api/pricing) - What are the rate limits for CoinGecko's API? The CoinGecko API Demo plan has a rate limit of 100 ca...

9. [Yfinance saying “Too many requests.Rate limited”](https://www.reddit.com/r/learnpython/comments/1isuc4h/yfinance_saying_too_many_requestsrate_limited/) - Rate limits apply per IP address. Free tier: ~2,000 requests/hour (roughly 48,000/day). After limit:...

10. [Yahoo Finance API: Complete Guide + Best Alternatives ...](https://marketxls.com/blog/yahoo-finance-api-ultimate-guide) - RapidAPI free tiers: Most Yahoo Finance providers on RapidAPI offer a free tier with severe limitati...

11. [Best Free Crypto API in 2026: Free Tier Comparison](https://coinmarketcap.com/academy/article/best-free-crypto-api-in-2026-free-tier-comparison) - Compare the best free crypto APIs of 2026 for students, indie devs, and early builders, and see why ...

12. [qbhdwe/coinglass: CoinGlass API: Free Tier + Save Up to ...](https://github.com/qbhdwe/coinglass) - You get real-time liquidation data, open interest charts, funding rates, long/short ratios, and the ...

13. [CoinGlass API Review (2026): Is It Worth It for Crypto ...](https://dev.to/great-time-flies/coinglass-api-review-2026-is-it-worth-it-for-crypto-quant-traders-2bcf) - There's no free API tier, but the CoinGlass website gives you visual access to the same data before ...

14. [Kraken WebSocket API - Frequently Asked Questions](https://support.kraken.com/articles/360022326871-kraken-websocket-api-frequently-asked-questions) - Full details regarding the trading endpoints are available via the WebSocket API documentation, and ...

15. [Kraken API Unlocked: automated crypto trading on Kraken](https://blog.kraken.com/product/api/unlocked-1-strategies-infrastructure-and-where-to-start) - Kraken's API supports automated crypto trading via REST, WebSocket, and FIX 4.4 protocols across spo...

16. [How do derivatives market signals predict crypto price ...](https://web3.gate.com/crypto-wiki/article/how-do-derivatives-market-signals-predict-crypto-price-movements-through-funding-rates-open-interest-and-liquidation-data-20260207) - Funding rates reflect market demand for open positions, while liquidation data triggers forced closu...

17. [Crypto Data API: Most Comprehensive & Reliable ...](https://www.coingecko.com/en/api) - Get reliable crypto prices and market data with CoinGecko API, trusted by 150M+ monthly users. Acces...

18. [Market Regime Detection using Hidden Markov Models in ...](https://www.quantstart.com/articles/market-regime-detection-using-hidden-markov-models-in-qstrader/) - The risk manager checks, for every trade sent, whether the current state is a low volatility or high...

19. [Market Regime Detection Using Hidden Markov Models](https://questdb.com/glossary/market-regime-detection-using-hidden-markov-models/) - Hidden Markov Models detect market regimes by modeling hidden states and transitions, identifying vo...

20. [Reading Crypto Liquidation Heatmaps And Funding Rates](https://cryptouniversity.network/guides/reading-crypto-liquidation-heatmaps-and-funding-rates-a-practical-traders-guide) - Learn how to read crypto liquidation heatmaps, funding rates, open interest, and long-short ratios t...

21. [Funding Rate + Open Interest: How to Spot Liquidations](https://tradelink.pro/blog/funding-rate-open-interest) - Funding Rate and Open Interest are key metrics for analysing cryptocurrency derivatives markets. The...

22. [Sharpe Ratio for Algorithmic Trading Performance ...](https://www.quantstart.com/articles/Sharpe-Ratio-for-Algorithmic-Trading-Performance-Measurement/) - The ratio compares the mean average of the excess returns of the asset or strategy with the standard...

23. [Sortino: A 'Sharper' Ratio](https://www.cmegroup.com/education/files/rr-sortino-a-sharper-ratio.pdf) - The. Sortino ratio is a modification of the Sharpe ratio but uses downside deviation rather than sta...

24. [Calmar Ratio - Measure Your Risk-Adjusted Returns](https://journalplus.co/metrics/calmar-ratio) - Calmar Ratio = CAGR / |Maximum Drawdown|. CAGR is the compound annualized growth rate over the trail...

25. [Trading Expectancy: The Formula That Predicts If Your ...](https://www.tradezella.com/blog/trading-expectancy) - Expectancy in Trading: The Metric That Actually Predicts Profitability · Expectancy = (Win Rate x Av...

26. [Profit Factor Definition: Formula, Calculator & Trading ...](https://www.backtestbase.com/education/win-rate-vs-profit-factor) - = Gross Profit ÷ Gross Loss. Key insight: A positive expectancy always means profit factor > 1.0. Ex...

27. [The Kelly Criterion: A retail trader's guide to position sizing](https://experts.deriv.com/insights/kelly-criterion-position-sizing) - The Kelly Criterion provides a framework for determining position size based on win rate and payoff ...

28. [Kelly Criterion Calculator | Free Trading Position Size Tool](https://www.backtestbase.com/education/how-much-risk-per-trade) - Free Kelly Criterion calculator for traders. Enter your win rate and average win/loss to get Full, H...

29. [ATR Trading Strategies Guide](https://blog.traderspost.io/article/atr-trading-strategies-guide) - Master ATR (Average True Range) trading strategies for volatility measurement, position sizing, stop...

30. [Average True Range (ATR): How to Measure Volatility for ...](https://www.tradealgo.com/trading-guides/technical-analysis/average-true-range-atr-how-to-measure-volatility-for-better-trade-sizing) - The formula is: Position Size = Dollar Risk per Trade / (ATR Multiplier x ATR x Point Value). For st...

31. [Cumulative Volume Delta: The Ultimate CVD Indicator](https://www.gocharting.com/blog/cumulative-volume-delta/cumulative-volume-delta) - Volume Delta is a common technical analysis method used by traders in the forex, stock, and cryptocu...

32. [Average True Range (ATR)](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr) - Average True Range (ATR) is the average of true ranges over the specified period. ATR measures volat...

