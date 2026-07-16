# Composio connector spike — D17 (timeboxed, connectors only)

> P1C close-out, 2026-07-17. ROADMAP M1.5's timeboxed spike. Question: should
> tradekit use Composio's managed connectors anywhere? Verdict below; no code.

## What Composio is (as of 2026-07)

Managed integration platform for AI agents: ~250+ app connectors with managed
auth (plus a much larger long-tail tool catalog), exposed via MCP or direct
API, with adapters for the popular agent frameworks. Its catalog includes some
finance-adjacent connectors — notably Alpaca (trading) and Alpha Vantage
(market data), plus a Nasdaq data toolkit.

## Verdict: NO for the data/broker core; MAYBE (P3+) for reporting side-channels

**Core data layer / execution path — do not adopt.**
1. Our providers are already built, conformance-tested, and reviewed (Kraken,
   Alpaca, CoinGecko, yfinance macro — 338 tests). A managed connector adds a
   third-party runtime dependency + auth indirection and removes none of our
   work: normalization to Decimal-via-str, aware-UTC bars, typed error
   taxonomy, rate limiting, and the closed-bar cache are OUR contracts;
   Composio provides raw tool calls, not those guarantees.
2. Determinism rules (zero-network tests, injected clocks, replayability from
   the ledger) get harder, not easier, behind a hosted connector layer.
3. The execution path (P3/P4) is exactly where DESIGN's gates demand the
   thinnest, most auditable surface — putting a general-purpose agent-tool
   platform between the policy engine and the broker contradicts TD-6/TD-15.

**Reporting/notification side-channels (P3+) — worth a second look.** When
review memos and daily reports land (P3), a Slack/Gmail push channel is the
kind of commodity integration Composio genuinely dedupes (managed OAuth, no
bespoke API code). Revisit ONLY for that, and only if Mike wants push
delivery; a plain SMTP/webhook script may still be simpler at our scale.

**MCP note:** tradekit's own MCP surface (canonical doc §4 `mcp_server.py`,
optional) is unaffected — we EXPOSE tools; Composio is for CONSUMING others'.

Sources: [Composio toolkits catalog](https://composio.dev/toolkits),
[Composio agent-connectors overview](https://composio.dev/content/agent-connectors),
[Nasdaq toolkit](https://composio.dev/toolkits/nasdaq),
[Merge.dev platform comparison](https://www.merge.dev/blog/ai-agent-integration-platforms).
