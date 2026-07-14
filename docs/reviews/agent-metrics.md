# Agent metrics — producing-agent assessments per review round

Accumulating register: one section per review round. Defect counts are those
attributable to the agent's own scope (a test gap that fails to catch an
implementation bug counts against BOTH agents).

## Round 1 — 2026-07-12 — P0 M0.2/M0.3 (commits d446ffb, 5f93f15)

Reviewer: code-reviewer agent. Verification: `uv run pytest` (49 passed),
`uv run ruff check .` (clean), `uv run mypy` (clean, 15 files). All defects
below were confirmed by executing reproduction scripts, not by inspection alone.

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| tdd-p0 | tests/ (38 test fns), ASSUMPTIONS.md | 1 (shared) | 1 (shared) | 3 | B+ | Exemplary assumption-pinning discipline and assertion messages; but the golden-path bias let the one HIGH through — quantize tested only on power-of-ten ticks, tamper tests cover only 2 of 7 hashed columns. |
| dev-p0 | src/tradekit/{contracts,ledger} | 1 | 3 | 3 | B | Clean architecture, deep-module discipline honored, FTS/hash/retry mechanics solid; but the G2 quantize guarantee is falsified for non-power-of-ten ticks, and two silent-coercion paths (naive datetimes, Decimal payloads) violate TD-17/ASSUMPTIONS-10 quietly. |

Shared defects: D1 (quantize grid — dev wrote the bug, tdd's tick coverage
missed it); D2 (EventFilter naive-datetime — ASSUMPTIONS never pinned
awareness on filters, impl inherited the hole).

Out-of-scope carried risk noted for the M0.1 producer (prior round, ungraded):
pyproject.toml claims deep-module import enforcement but
`ban-relative-imports = "parents"` does not ban cross-module absolute imports
of `_internals` (probe-verified). DESIGN §1 requires this lint "from day one".

## Round 2 — 2026-07-14 — P1A data layer (commits 7643c29..e85e083)

Reviewer: code-reviewer agent (Opus). Verification: `uv run pytest` (165
passed), `uv run ruff check .` (clean), `uv run mypy` (clean, 31 files).
Alpaca crypto response shape confirmed against Alpaca's own OpenAPI spec
(MultiBarsResponse: `bars` is an object keyed by symbol, not a list); cache
mixed-range behavior confirmed by executing a probe. Verdict: FIX-FIRST.

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| tdd-p1a (Sonnet) | stories 3-5 tests (cache, kraken, ratelimit) + ASSUMPTIONS 27-31 | 1 (shared) | 1 (shared) | 0 | B- | Kraken/ratelimit unit pins are exemplary (real Kraken body shape, fake-clock discipline, no-real-sleep structural pin). But the cache suite never tests a MIXED closed+live range — exactly story 3's headline "only the live bar refetches" — so the write-only-in-production gap shipped green; and ratelimit is pinned only in isolation, nothing asserts it is wired into any provider, letting the orphan through. |
| dev-p1a (Sonnet) | stories 3-5 src (cache.py, kraken.py, ratelimit.py, errors.py, port.py) | 1 (shared) | 3 | 1 | B- | Kraken normalization (pair-spelling split, epoch→aware-UTC, Decimal-via-str) is clean and the range-guard-before-HTTP is correct. But ratelimit.py is dead code (no provider imports it), the cache serves cached closed bars only when `end` lands exactly on a bar boundary (D-cache), Kraken maps every non-200 → ProviderUnavailable so HTTP 4xx never becomes ProviderRequestError despite its own docstring (D-taxonomy), and malformed 200 bodies raise untyped KeyError/InvalidOperation despite the docstring promising ProviderUnavailable (D-malformed). |
| tdd-p1a-2 (Sonnet) | stories 6-8 tests (alpaca, coingecko, port conformance) | 1 (shared) | 1 (shared) | 1 | C | The Alpaca crypto fixture uses a flat `{"bars":[...]}` list for BOTH equity and crypto, but the multi-symbol crypto endpoint returns `bars` keyed by symbol — the test pins the mock, not reality, and hid a live-API-breaking bug behind green (D-alpaca-crypto). The conformance suite also can't catch Decimal-from-float noise (the contract coerces float→Decimal, so the isinstance check always passes) and never asserts stale is False. Auth/env/pagination/taxonomy pins are otherwise strong. |
| dev-p1a-2 (Sonnet) | stories 6-8 src (alpaca_data.py, coingecko.py) | 1 (shared) | 2 (shared) | 0 | C+ | Equity path, env-var guards, timeframe map, and Decimal(str(x)) precision handling are correct. But the crypto path iterates `body.get("bars", [])` as a list; against the real symbol-keyed dict it raises TypeError on the first row — the crypto half of story 6 does not work outside the fixture (D-alpaca-crypto), and both providers inherit the non-200→ProviderUnavailable (D-taxonomy) and untyped-malformed-body (D-malformed) holes from the story-4 pattern. |

Shared defects: D-alpaca-crypto (HIGH — dev-p1a-2 coded the flat-list parse,
tdd-p1a-2's fixture shape hid it); D-ratelimit-orphan (HIGH — dev-p1a left the
module uncalled, tdd-p1a pinned it only in isolation); D-taxonomy /
D-malformed (MED — cross-provider, seeded by the story-4 Kraken pattern and
copied into Alpaca/CoinGecko).
