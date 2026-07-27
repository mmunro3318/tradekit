# HANDOFF — StratchPad (charting workbench SPA over our own data)

> Seed for a fresh session. Mode: new-product brainstorm → design → build.
> START WITH tk-brainstorm (interview Mike — this doc is his wishlist, not a
> spec; several items need scoping conversations). Written 2026-07-27 by CTO
> session; zero conversation context assumed.

## Mike's vision (his wishlist, faithfully recorded)

A quick-and-dirty TradingView-style SPA — local, personal, free — that:
1. Charts assets with toggleable indicators (add/hide/remove), multi-tab
   watchlists, fast navigation.
2. Serves as a portal to OUR data: tick + 3-venue order-book parquet on
   D:\tradekit-data (ticks\, books\<venue>\) — data TradingView paywalls,
   we now record ourselves.
3. Lets him practice concepts from YouTube (e.g. mark a manipulation candle,
   place a stop over it) — annotation + what-if, possibly pushing a marked
   level "through live" data as it streams.
4. **(a) Add NOVEL indicators** and **(b) compose strategies/edges as
   algorithms** — the two features he flagged as hardest to visualize. His
   instinct: LLM-assisted authoring; wants a chat panel wired to DeepSeek
   (his preferred cheap technical model) with hooks/API into the chart
   state.
5. Later: benchmark various LLMs on chart-pattern recognition; web3/
   blockchain ecosystem visual explorers (nodes, on-chain data).

## CTO's scoping guidance (from this session — carry it in)

- **MVP cut**: local FastAPI (or plain http.server) backend reading the
  parquet trees + Kraken OHLC cache, TradingView's open-source
  `lightweight-charts` (free, canonical, tiny) on the front. Candles +
  volume + our verified indicators (rsi/macd/bollinger/atr/keltner/
  volume_ratio from `tradekit.mae._indicators` — do NOT reimplement in JS;
  serve computed series from Python so numbers match the scanner exactly:
  one source of truth).
- **Novel indicators (4a)**: an indicator = a Python function
  `list[Bar] -> list[float|None]` dropped in a plugins dir; backend
  hot-loads and serves it. LLM writes the function; the plugin contract is
  the "hook."
- **Strategy composer (4b)**: strategies = the same filter-dict vocabulary
  the scanner already speaks (GLOSSARY.md is the source of truth) — the
  composer UI builds filter dicts, and `scan()` (audit="exhaustive") is the
  execution engine. This keeps StratchPad and the real funnel semantically
  identical — a strategy that looks good here IS the config the bot runs.
- **DeepSeek chat**: fine as a bolt-on panel (Mike supplies API key); give
  it read access to chart state + plugin dir writes, nothing else. It never
  touches tradekit src/ or money paths.
- **Red lines**: StratchPad is READ-ONLY vs markets — no order routing,
  ever (advisory-HUD doctrine; execution lives in the gated pipeline only).
  Keep it out of `src/tradekit/` — separate top-level `stratchpad/` dir or
  its own repo; it must not couple to money-path code review requirements.
- Kraken Desktop UIA is a dead end (probed, GRADE C, 2026-07-20) — do not
  plan any "sync with Kraken's app" feature.
- hud already renders a tabbed advisory HTML (docs/hud/) — steal its funnel
  plumbing patterns, but StratchPad is a different product (exploration vs
  execution advisory); don't merge them prematurely.

## Suggested build order

brainstorm (pin MVP scope with Mike) → walking skeleton: one pair, candles
from our data, one indicator toggle → indicator plugin contract → strategy
composer bridging to scan() → tick/book visualizations (depth heat, trade
tape) → DeepSeek panel → (much later) LLM benchmarks, web3 explorers.

## Data facts the builder needs

- Tick schema: trades-<HH>.parquet = ts/price/qty/side/ord_type (hourly,
  per pair-dir per date-dir). Book schema: ts + bid/ask_price/qty_1..20.
- OHLC beyond 90d is capped by Kraken (720 candles/interval). For deep
  history, candles can be AGGREGATED FROM OUR OWN TICKS (that's the moat).
- Collectors are supervised by a 15-min watchdog scheduled task; don't
  assume files are quiescent — hourly files are append-rewritten while hot.
