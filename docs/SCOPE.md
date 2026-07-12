# Agentic Trading Framework — Scope & Vision (Pass 1)

> Session: 2026-07-12 (Cowork, scoping). Status: draft for Mike's review.
> This doc is the top-level pass. Each subsystem gets its own deep-dive doc in the architecture session (Claude Code, high effort).

## 1. Vision

A toolkit that equips any capable AI model or agent (Claude, Codex, Gemini, LangGraph agents, subagents) with everything needed to research, hypothesize, simulate, and eventually execute trades — under deterministic gates it cannot bypass. Endgame: the agent funds its own subscription costs (~$22+/mo) from trading profit, measured as a monthly self-funding KPI.

**Design axiom:** deterministic core, thin LLM shell. All judgment calls happen in the model; all enforcement, math, and money-touching happens in boring, testable Python the model can only invoke through whitelisted verbs.

## 2. Locked Decisions

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| D1 | Repo home | New local folder + GitHub remote (early) | Sandbox↔host bugs; backup |
| D2 | Execution venue (MVP) | Alpaca (paper + live stocks + live crypto) | One account, one API, fractional, no PDT at size |
| D3 | Wallet infra | Coinbase CDP Server Wallets + AgentKit | TEE policy engine under our gates; Python SDK; free tier; US-legal. Runner-up: Privy |
| D4 | MVP done-gate | Pipeline proof: 3 live trades that execute, settle, reconcile vs ledger; P&L snapshot verified by non-Anthropic model | $N profit = luck at this size |
| D5 | Profit north star | Self-funding KPI: monthly net P&L ≥ subscription cost. Reported, never a per-trade gate | Avoids overtrading incentive |
| D6 | Autonomy model | Fully autonomous within gates + global dials; live access earned via paper-series promotion ladder | Mike's call; see §5 |
| D7 | No deception in harness | Stakes come from visible attempt statistics + strict promotion criteria, not fake "this is live" flags. Blind evaluation OK (withholding ≠ lying) | Deception corrupts calibration and trust |
| D8 | Analysis engine | MAE per "Comprehensive Design Document" (canonical), porting from older spec: MCP constraints (≤10 tools/server, terse-by-default), numeric thresholds (quarter-Kelly, ATR mult 1.5–3.0, overfit bands), on-chain module decision pending (Q below) |
| D9 | Language/shape | Python monorepo; pure-Python core; CLI first; FastMCP wrappers as thin decorators; skills as ~200-token descriptors | Callable by any model/agent type |
| D10 | State | SQLite append-only ledger (theses, trades, snapshots, grades, promotions) | Replayable by auditor agents |

## 3. System Map (subsystems, top-level)

```
┌─ LLM / Agent (any model) ──────────────────────────────────┐
│   skills (~200 tok each) → CLI or MCP tools                │
└──────┬─────────────────────────────────────────────────────┘
       ▼
┌─ Public verb surface ──────────────────────────────────────┐
│ MAE tools · thesis tools · account verbs · research tools  │
└──────┬─────────────────────────────────────────────────────┘
       ▼
┌─ Policy Engine (deterministic, non-bypassable) ────────────┐
│ gates · caps · allowlists · promotion state · kill switch  │
└──┬──────────┬───────────┬──────────┬───────────────────────┘
   ▼          ▼           ▼          ▼
 MAE       Thesis      Accounts    Ledger (SQLite, append-only)
 (data+    Registry    (Alpaca     
 analysis) (contracts) paper/live, 
                       CDP wallet)
```

1. **MAE (Market Analysis Engine)** — per canonical doc. Data: Kraken + Binance Futures public (crypto market data, no keys), Alpaca (equities + crypto bars), CoinGecko, yfinance (macro). Tools: scan_markets, get_regime (HMM), get_derivatives_context, compute_strategy_metrics, size_position, get_correlation_matrix. Full API coverage designed now; implemented incrementally.
2. **Thesis Registry** — the spine. Every position begins as a *thesis contract*: structured YAML/JSON with asset, direction, entry conditions, expected move + horizon, invalidation conditions, position size, and explicit numeric success/failure criteria. Grading = pure arithmetic vs market data. Statuses: draft → reviewed → approved → active → graded (pass/fail/invalidated) or rejected.
3. **Adversarial Review** — every thesis passes attack/defense before approval: a non-Anthropic model (Codex default, Gemini alt, via gstack skills in Claude Code) attacks the thesis; the proposing agent defends; reviewer output is scored against a rubric; unresolved attacks block approval. Review artifacts stored with the thesis.
4. **Policy Engine** — deterministic gate layer every money-touching verb passes through: sufficient balance, position-size caps, per-asset allowlist, daily trade count, max drawdown circuit breaker, promotion-tier check, kill switch. Rules codified in a versioned `rules/` module + human-readable RULES doc where each rule carries its WHY inline. Defense in depth: CDP's TEE policy engine and Alpaca-side guards sit beneath ours.
5. **Accounts** — Alpaca wrapper (paper + live; agent gets verbs, never keys) and CDP Server Wallet wrapper (same pattern; testnet/tiny funds in MVP). Multiple named paper accounts supported (the agent can spin up paper accounts to study distributions/strategies).
6. **Paper Sim & Promotion Ladder** — see §5.
7. **Academic Research Loop** — daily scheduled research on trading strategies, market structure, and under-studied topics; outputs concise notes into `docs/wiki/` knowledge base with a status (candidate / simulating / rejected+why / adopted). Feeds thesis generation.
8. **Reporting** — one-page daily decision report (hypothesis, strategy, justification, risk, expected loss, gate status); template to be researched against practitioner standards (e.g., hedge-fund one-pagers). Plus Kanban artifact + `cc-dev-log.md` for dev progress.
9. **Verification layer** — every MVP claim (trade executed, P&L snapshot) reconciled against broker records and confirmed by a second, non-Anthropic model.
10. **Memory & Experiment Registry (D15)** — the living/learning layer. Ledger records every trade, thesis, strategy-performance metric, decision-time market snapshot, and per-run harness metadata (model, framework, system/seed prompt verbatim + hash). Session bootstrap emits a memory brief (recent + high-salience); a search verb exposes the full archive (FTS5 first, RAG later). Distilled lessons live in the wiki; the registry makes agents, prompts, and strategies all comparable experiments over time.
11. **Advisory mode (D16)** — same pipeline, human hands: thesis contracts and recommendations for Mike's Kraken (~$2.7k, read-only API tracking) and Cash App (~$6.4k, manual tracking) holdings; Mike executes approved trades manually and logs fills via a manual-entry verb, so advisory positions are graded identically. Also reviews Mike's own theses through the standard attack/defense pipeline.

## 4. Workflow (task 1 mapping)

scan/research → **hypothesis** (thesis contract draft) → **adversarial review** (attack + defense, rubric-scored) → gate check (metrics thresholds from MAE) → **approve → simulate** (paper) or **reject** (logged with why) → paper grading vs contract → promotion ladder → live execution → **in-the-wild grading**: asset tracked vs thesis expectations on explicit deterministic metrics; grade written to ledger.

## 5. Promotion Ladder (autonomy earned, dials tunable)

- Tier 0 — research only. Tier 1 — paper trading, unlimited. Tier 2 — live, small caps. Tier 3+ — raised caps (future).
- Promotion T1→T2: **3 clean paper series out of the last 4, most recent clean** (perfect-streak requirement rejected: incentivizes do-nothing conservatism). "Clean" = thesis graded pass AND process-compliant (no gate violations), not merely profitable.
- On promotion: agent produces the one-page readiness report (hypothesis/strategy/justification/risk/expected loss + attempt statistics); Mike flips `sim-only → live`; agent gets a **max-3-trade live sequence**, then auto-reverts to review.
- Attempt statistics always visible to the agent (stakes without deception, per D7).
- Demotion: drawdown breach, gate violation, or failed live grading drops tier automatically.

## 6. Phasing (top-down, not linear — each pass deepens all sections)

- **Pass A (this doc):** system map, locked decisions, open questions.
- **Pass B (next session, Claude Code, high effort):** full architecture doc — module trees, schemas (thesis contract, ledger DDL, report template), rules catalog with WHYs, API contracts, promotion state machine, test strategy. Ends with `ROADMAP.md` (phases → milestones → epics/stories, all checkboxed).
- **Pass C:** implementation per ROADMAP. MVP slice: MAE core (Alpaca+Kraken data, indicators, metrics, sizing) → thesis registry + grading → policy engine + Alpaca paper wrapper → paper account with $5k crypto + $5k stocks base distribution + long-term thesis and per-asset justifications → promotion ladder → 3 reconciled live trades → verified snapshot.
- Deferred (designed now, built later): CDP wallet with real funds, on-chain data module, Binance/Kraken execution, MCP server hardening (sse), self-skill-honing loop, A/B testing of agent's own skills.

## 7. Batch-2 Decisions (resolved 2026-07-12)

| # | Decision | Choice |
|---|----------|--------|
| D11 | Repo home | `C:\Users\admin\dev\tradekit` — short path, no OneDrive sync, GitHub remote early |
| D12 | Live bankroll | $50–100 (Mike comfortable at $20–50; up to $100 acceptable). Configurable dial. |
| D13 | On-chain data | Design interface now; implement later by **rolling our own oracle** from free sources (Etherscan free, DeFiLlama, Dune free, direct RPC) — doubles as a sellable product for other agents/bots. No paid Glassnode/Nansen. |
| D14 | Research loop | Cowork scheduled task (not created yet — script/prompt content first). Architecture: **lead researcher (Sonnet)** starts fresh each run, reads wiki state, picks topics + records why, dispatches **3+ Haiku scout agents**; each scout returns a 2-paragraph review (summary + justification/relevance, or rejection: permanent vs partial/promising-but-not-now). Lead grades scout output and may run meta-research on scout prompt/context engineering. All output → `docs/wiki/`. |

### Batch-3 Decisions (resolved 2026-07-12, second review)

| # | Decision | Choice |
|---|----------|--------|
| D15 | Memory & Experiment Registry (new subsystem, MVP-required) | Everything is recorded: all paper/live trades, strategies used + their performance metrics, market snapshots at decision time, AND the harness metadata per run — model/framework (Claude Cowork vs Codex CLI vs DeepSeek...), system/seed prompt (stored verbatim + hashed) — so agent configurations themselves are comparable experiments. Session bootstrap = auto-generated **memory brief** (recent + high-salience items surfaced immediately) + a **search verb** over the full archive. MVP search: SQLite FTS5 keyword search (deterministic, zero infra); embeddings/RAG upgrade designed now, built later. Wiki (`docs/wiki/`) holds distilled knowledge; ledger holds raw history. |
| D16 | Capital pools & advisory mode | Three pools: (1) **Bot bankroll** — $100 experiment capital, drip-fed further only as graded performance justifies; fully automated via Alpaca. (2) **Kraken Pro ~$2.7k crypto** and (3) **Cash App ~$6.4k stocks** — **advisory-only**: framework produces thesis contracts + recommendations; Mike executes manually if he approves, then logs fills via a manual-entry verb so advisory positions are graded identically to bot positions. Kraken gets a read-only API key for balance/position tracking; Cash App (no API) is tracked purely from Mike's manual entries. The framework also serves as **adversarial reviewer of Mike's own theses** — he submits a thesis contract, it runs the same attack/defense + gate pipeline. |
| D17 | Data-access exploration | "Own oracle" confirmed feasible — it's the MAE data layer (aggregate + normalize + cache free APIs) packaged as a service; productizing is a later phase, not new tech. Explore list for Pass B: **Composio** (integration/tool platform; Mike has credit — evaluate for connectors, not core market data), Pionex (bot exchange — likely pass), Binance public endpoints (already in stack; US access via binance.us or data-only). Direct free APIs remain the default; no core dependency on paid middlemen. |

### Self-funding realism (for D5/D12 context)
Return scales with capital: a $100 bankroll returning an *excellent* 5%/mo earns $5/mo; covering the $22/mo subscription at 5%/mo needs ~$440 deployed, at a more realistic 1–2%/mo needs ~$1,100–2,200. So the self-funding KPI is a **capital-growth milestone**, not something the MVP bankroll can hit. Ladder: prove pipeline ($50–100) → prove edge on paper at scale → grow live capital only as fast as graded performance justifies.

## 8. Next-Session Kickoff Checklist (Pass B — Claude Code, high effort)

Mike's hands (before or during):
- [ ] Create `C:\Users\admin\dev\tradekit`; open Claude Code there (or connect the folder in Cowork).
- [ ] Alpaca account: sign up, generate paper API keys (live keys + funding deferred to promotion time).
- [ ] CoinGecko Demo API key (free). Kraken/Binance public need no keys.
- [ ] Kraken Pro: create a **read-only** API key (Query Funds/Orders only — no trade permission) for advisory-mode tracking.
- [ ] Coinbase CDP developer account (deferred OK — wallet phase).
- [ ] Create empty GitHub repo `tradekit`.

Agent's first moves (fresh context):
- [ ] Read SCOPE.md + canonical MAE doc (copy both into `docs/`), check cc-dev-log.md (won't exist yet — create).
- [ ] Produce full architecture doc set: module tree, thesis-contract schema, ledger DDL (incl. experiment-registry tables per D15), memory-brief generator + search verb design, rules catalog (each rule with WHY inline), promotion state machine, advisory-mode flow (manual-entry verb, D16), report template (research practitioner one-pager formats first), research-loop prompts (lead + scout), test strategy.
- [ ] Evaluate Composio / other explore-list items (D17) with a quick spike, not a commitment.
- [ ] Adversarial review of the architecture via gstack second-opinion (Codex; Gemini alt) before writing ROADMAP.md.
- [ ] ROADMAP.md: phases → milestones → epics/stories, all checkboxed. Then implement.

## 9. Standing Caveats

- Not financial advice; the live bankroll is tuition money, sized to lose.
- Live-account creation, KYC, and funding are Mike's hands only.
- All file work on host via file tools (sandbox bugs); GitHub remote early.
