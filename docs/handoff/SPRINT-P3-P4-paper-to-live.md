# SPRINT P3→P4 — Paper trading, review, reporting, memory, live proof

> Coarser than P1/P2 docs by design: by the time you're here, the patterns (ports, conformance suites, event-sourcing, adversarial replays) are established — copy them. Split into sessions along the story boundaries below. Executor: Sonnet; Opus for the fill model, the reconcile→halt path, and anything touching live keys. References: DESIGN §8, §11, §12, TD-6/7/8/19/21, G5/G6.

## P3 stories

### 3.1 BrokerPort + conformance suite
Port per DESIGN §8.1 (five methods; `submit` takes the VerdictToken). Write the conformance suite FIRST (`tests/contract/test_broker_port.py`) — every adapter passes the same suite; that's what makes venue swap safe (TD-18 ring 2).

### 3.2 PaperBroker (TD-7 — our own; Opus reviews the fill model)
- Named accounts = ledger projections (`paper:alpha`, …), seeded by a `tk account create-paper` verb + event.
- Market fills: latest cached quote mid ± half-spread from `tradekit.costs`, plus fee; quote snapshot stored ON the Fill (§8.3 — every fill auditable).
- Limit fills: bar must trade THROUGH the limit by ≥1 tick — exact touch is NOT a fill (G5). No partials. Deterministic: same cache ⇒ same fills (replay test).
- Known-optimism note (§8.3) stays true at ≤$25 notionals; do not gold-plate the microstructure.

### 3.3 `broker.execute_order` — the two-phase money pipeline (Opus)
Exactly §8.2: ActionProposed → policy.evaluate → VerdictIssued → (deny ⇒ exit 1 with Verdict) → adapter.submit(order, verdict_token) → OrderSubmitted/Ack → fill polling → FillRecorded → thesis activation. `tk order submit|status|cancel`. Adapters REFUSE without an allow-token. Reconcile (`tk account reconcile`): broker records vs ledger; ANY mismatch → ReconciliationRun(mismatch) + automatic HaltSet (§8.2 step 7). Test the halt path — it's the last line of §15.

### 3.4 Review module (TD-21)
`LLMReviewerPort` → subprocess adapters (Codex CLI default, Gemini alt — both exist on Mike's machine via gstack). Attack/defense as structured JSON exchanges; rubric scoring DETERMINISTIC in Python (`prompts/rubric-thesis-v1.md` — write it with Mike); unresolved attack ≥ threshold blocks approval. Auto-fail short-circuits BEFORE spending tokens: missing numeric EV, no falsifiable catalyst, size ≠ SizingComputed. Artifacts ledgered. Tests: fake reviewer adapter (canned JSON) — never a real LLM call in tests. VOID sign-off (`verify_claim`) rides the same port.

### 3.5 ManualBroker + advisory mode (D16)
`submit` raises `AdvisoryOnly`; `tk fill record` writes Fills with `actor=mike`; Kraken read-only key drives balance tracking (needs Mike's key). R-009/R-014 already enforced by policy — advisory accounts just flow through.

### 3.6 Memory + reporting (`tradekit.memory`, `tradekit.report`)
`tk brief` (≤ ~1.5k tokens: promotion state + attempt stats (D7), open positions, active theses, last 10 grades, halts, top-salience lessons); `tk search` (ledger FTS + wiki front-matter; decide multi-word semantics — phrase vs AND — and PIN it in ASSUMPTIONS, it was left open in P0); `tk wiki add`; daily memo + readiness report + pnl snapshot templates per DESIGN §12.3/SME §3. Research-loop lead/scout prompts (D14) into `prompts/` — Sonnet drafts, Mike approves tone/shape.

### 3.7 P3 done-gate
End-to-end replay: scan → thesis → review (fake adapter) → gates → order → paper fill → grade → memo, reproducible from the event log. Seed the $5k/$5k paper distribution with long-term theses (SCOPE Pass C).

## P4 stories (live proof — D4; every step pairs with Mike)

1. Alpaca PAPER dress rehearsal through the real API (order lifecycle parity vs PaperBroker conformance).
2. Mike: live keys + $50–100. Keys enter `.env` only; never echoed, never committed (TD-19).
3. Real promotion: readiness report → `tk promote confirm` → 3-trade budget.
4. 3-trade live sequence (long-only, liquid large-caps/BTC/ETH per R-004) → `reconcile` green after each → auto-revert to T1 (R-011).
5. `tk report snapshot` → `verify_claim` with a non-Anthropic model confirms trades/settlement/P&L vs broker records. **That's the MVP done-gate. Stop, celebrate, retro in the dev log.**

## Traps

- Paper determinism dies if fills read the LIVE quote at call time — fills read the CACHED quote referenced by the order event, so replays reproduce.
- Reviewer subprocesses: timeouts + max-token caps + treat stdout as untrusted data (parse JSON strictly; a chatty model must not crash the pipeline).
- `tk brief` token budget is a hard cap — truncate by salience, never silently overflow (it's every agent's first read).
- P4 live keys: if anything reconciles wrong, HALT stays set until Mike manually clears — no auto-resume on the live path, ever.

## Addendum — CTO design pins (session P3, 2026-07-17)

Binding on TDD/dev agents. DESIGN wins on conflict — flag, don't improvise.
All P2 standing rules apply (freeze gate, path seams, module-attribute calls
for monkeypatchable deps, flag-for-ratification, typed payloads, strict mypy
for broker/ too — add to the pyproject override).

### TD-24 lands in batch A (Mike-signed 2026-07-17)

- `AccountConfig` contract (contracts, additive): `account_ref`,
  `principal_usd` (Decimal, quantized to cents), `max_trades_per_day`
  (int; 0 = paper/sim only per Mike's sketch), `max_daily_drawdown` /
  `max_lifetime_drawdown` / `max_daily_profit` (fraction Decimals or None),
  `consistency_rule` (opaque str or None). **None = rule DISABLED** (never
  ±Infinity). `AccountCreated` event + `accounts` projection;
  `tk account create-paper --config file.json` (defaults from config.toml
  when fields absent).
- Dial resolution order: AccountConfig field → config.toml default → code
  default. R-005 live → 5% of principal; R-006 → 20% of principal; R-014
  threshold → 40% of principal (was $200/$500); **R-008 stays absolute $10**
  (fee-noise floor — CTO exception Mike accepted).
- New rules (additive IDs, enforced ONLY when configured, disabled=None
  passes without a RuleHit... NO — emits a RuleHit with outcome "not_configured"
  so audit shows the rule was consulted): **R-017 max_daily_drawdown**,
  **R-018 max_lifetime_drawdown** (both vs principal, from pnl_daily).
  `max_daily_profit`/`consistency_rule` are ACCEPTED config slots with NO
  enforcement rule in P3 (Mike undecided) — document in RULES.md footer.
- P2's default account (`paper:alpha`) gets an implicit AccountConfig from
  config.toml defaults — existing tests must keep passing unchanged except
  where a dial's VALUE legitimately moved (enumerate every such test in the
  red report; the percent values are chosen to keep $500-account behavior
  IDENTICAL: 10% paper position cap unchanged, etc.).

### Batch plan (four-stage per batch; pre-registered Opus review focus in caps)

- **A:** BrokerPort protocol + AccountState/Position/OrderStatus contracts +
  conformance suite skeleton + TD-24 (AccountConfig, R-017/R-018, dial
  migration, create-paper verb).
- **B:** PaperBroker (OPUS FOCUS: FILL MODEL) — named accounts; market fills
  = latest CLOSED cached bar close mid ± half-spread from tradekit.costs +
  fee, quote snapshot ON the Fill (typed FillRecordedPayload lands here,
  replacing P2's harness convention — includes fill-time pnl attribution
  migration per ASSUMPTIONS round-9); limit fills = through by ≥1 tick,
  exact touch is NOT a fill (G5), no partials; deterministic replay.
- **C:** execute_order two-phase pipeline + reconcile→auto-halt (OPUS FOCUS:
  TOKEN GATE + HALT PATH) — adapters refuse without allow-VerdictToken
  (structural: submit REQUIRES the token argument and validates hash/ttl);
  ThesisActivated emitted on first fill; live-tier context wiring
  (promotion_state tier + live_sequence_remaining into _context — the P2
  fail-closed carve-out ends here); R-011 decrement on live fills.
- **D:** review module (LLMReviewerPort, subprocess adapters Codex/Gemini,
  deterministic rubric, auto-fail short-circuits, ReviewCompleted emission
  incl. void_signoff via verify_claim) + ManualBroker/advisory + `tk fill
  record`. Tests use FAKE adapters only (canned JSON; subprocess boundary
  tested with a stub executable via tmp_path).
- **E:** memory + report (tk brief hard token cap, salience truncation;
  tk search — PIN multi-word semantics: implicit AND of terms, phrase via
  quotes, record in ASSUMPTIONS; wiki add; daily memo/readiness/pnl
  templates) + the 3.7 end-to-end replay done-gate + SeriesClosed event +
  ledger.models read accessors + strategy-tag registry (ASSUMPTIONS 57f)
  + close-out (ROADMAP P3, dev-log, agent-metrics, Mike primer, P4 seed).
- Deferred WITH Mike flags: research-loop prompts tone (Sonnet drafts, Mike
  approves); rubric-thesis-v1.md shape (draft for his edit).

### Cross-cutting pins

- broker/ layout: __init__ verbs exactly per §4.2 (get, execute_order,
  reconcile, record_manual_fill) + internals _pipeline.py/_paper.py/
  _manual.py/_alpaca.py (alpaca adapter = P4, stub now).
- VerdictToken: policy.evaluate's allow Verdict carries a token =
  sha256(verdict_id + policy hash); broker.submit validates token against
  the ledgered VerdictIssued event (existence + thesis match + no newer
  deny) — out-of-band submission impossible through the verb surface.
- Quotes: PaperBroker reads bars ONLY via mae._runtime.get_closed_bars
  (extend the sanctioned-consumer note: thesis + broker are the two
  permitted cross-module internal consumers until the marketdata leaf
  extraction — still a Mike-signoff TD change, still deferred).
- Reviewer subprocess: hard timeout dial (default 120s), max-output cap,
  strict JSON parse with schema (a chatty model = ReviewFailed artifact,
  never a crash); adapter binaries resolved from dials, tests NEVER invoke
  real CLIs.
- All new file-writers get path seams; all clocks via existing seams.
