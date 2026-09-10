# SPEC-sizing-cap — one sizing basis for the paper funnel (2026-09-10)

Branch `feature/sizing-cap` (worktree `.worktrees/sizing-cap`; the main tree
stays checked out on `main` because the hourly task trades whatever is checked
out there). Seed: `docs/handoff/HANDOFF-2026-09-08-paper-record-sizing-cap.md`.
Paper only; live stays locked.

## 1. Scope

The paper cadence drafts a ticket at scan time and re-sizes it at
`thesis.submit`, and the two computations use DIFFERENT inputs, so the second
policy evaluation (binding, R-012) and the first (preview, R-005) deny most
entries. Measured on the digests 2026-09-07..10:

| tension | mechanism | observed |
|---|---|---|
| T1 R-005 | `size = equity*risk_pct/stop_pct`; any name with `2*ATR14 < 10%` of price sizes above the $50 paper cap | LINK $50.73, SOL $53.78, ETH ~$65 denied every hour; PAXG `killed_by=policy_verdict` |
| T2 R-012 | preview sizes at LIVE equity (`cadence._paper_equity_usd`, ~$497) and the ticket prices at the 1h close; `thesis.submit` sizes at the DIAL equity ($500) and the DAILY close; deviation = `|E_live/E_dial * p_1h/p_daily - 1|` | NEAR 0.117, 0.103, 0.046; AKT 0.047, 0.034; XRP 0.011 vs tolerance 0.01 — rejected at binding every hour |
| T4 (new) | every rejected binding attempt is an `ActionProposed(submit_order)` and R-007 counts proposals, not fills | R-007 "20 vs 20 / 21 / 22" from 15:00 UTC 09-09 — the paper account locked for the rest of the day by dead drafts |
| T3 | before `paper:alpha` existed, `broker.get` auto-vivified a $0 shell and `atr_position` raised on `equity <= 0`, swallowed as `killed_by=sizing` | two silent digests 09-07 |

Fix, in one sentence (**ASSUMPTIONS 182, to ratify**): both `mae.size_position`
call sites size from the SAME three inputs — **price = the ticket's limit price,
equity = `PolicyDials.paper_starting_equity_usd`, cap =
`PolicyDials.paper_max_position_usd`** — and `size_position` clips to the cap in
exact arithmetic, so the ticket notional equals the recorded `SizingComputed`
notional and never exceeds R-005's own limit. The policy side already uses the
dial for both R-005's cap and R-003 (`policy._context._paper_equity`,
ASSUMPTIONS 62); the scan preview was the odd one out. T4 disappears as a
consequence (no rejected drafts -> no dead proposals); R-007 itself is not
touched. T3 becomes a loud digest warning that also skips entries.

## Out of scope (explicit)

- `policy/_rules.py`, `policy/_context.py`, `policy/_evaluate.py`: no rule
  changes. R-007's "count proposals" semantics stays (never weaken an R-rule).
- `broker/_pipeline.py::_entry_price` (ASSUMPTIONS round-18: market entries
  execute at the snapshot's daily `last_close`). Unchanged — at execute time
  `qty = recorded/entry_price`, so R-012 is satisfied there by construction.
- `hud.DEFAULT_SYMBOLS` widening (pin B3 of SPRINT-PREVIEW-DEFER) — separate
  CTO decision after this lands.
- `tk hud --equity N`: still sizes at N (Mike's manual tool). Unknown U2.
- Live/advisory account sizing: `max_position_usd` is passed for `paper:`
  account refs only; every other ref keeps today's uncapped behavior.
- Kelly inputs, risk_pct, ATR multiplier: untouched.
- Wiring `pnl_daily` into the paper equity basis (ASSUMPTIONS 62): still
  deferred; when it lands it must land on BOTH sides (see U1).

## 2. Interface pins (copy into the PIN stage verbatim)

### P1 `mae.size_position` — two keyword-only inputs, one warning, one echo
```python
def size_position(
    symbol: str,
    account_equity_usd: Decimal,
    risk_pct_per_trade: float = 0.01,
    atr_multiplier: float = 2.0,
    kelly_win_rate: float | None = None,
    kelly_payoff_ratio: float | None = None,
    kelly_fraction: float = 0.25,
    *,
    price: Decimal | None = None,
    max_position_usd: Decimal | None = None,
) -> dict[str, Any]:
```
- `price`: the sizing price. `None` -> the last closed daily bar's close
  (today's behavior, byte-identical output). Given -> replaces
  `current_price` everywhere it is used (`atr_position(price=...)`, hence
  `stop_pct` and `size_usd`, and `recommended_units`). ATR(14) still comes
  from `_runtime.get_daily_bars(symbol, lookback_days=30)`. `price <= 0` ->
  `ValueError` (already raised by `_sizing.atr_position`; do not pre-check).
- `max_position_usd`: `None` -> no clip (today's behavior). Given and
  `<= 0` -> `ValueError("max_position_usd must be positive — a non-positive
  cap sizes nothing and is a caller bug")`. Given and
  `recommended_size_usd > float(max_position_usd)` -> the clip:
  ```python
  units = (max_position_usd / price_dec).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
  recommended_units = float(units)
  recommended_size_usd = float(units * price_dec)   # <= max_position_usd exactly
  warnings.append("capped_by_max_position")
  ```
  where `price_dec = price if price is not None else Decimal(str(current_price))`.
  The clip applies AFTER the min(ATR, Kelly) choice; `atr_position_size_usd`
  and `kelly_position_size_usd` keep their uncapped values (audit trail).
- Output dict gains exactly one key: `"max_position_usd": float | None` (the
  cap as passed, `None` when not passed). No other key changes shape.
  `"current_price"` is `float(price)` when `price` was given.
- TD-11 purity holds: both inputs are market/cap facts, not P&L history.
  `mae` still imports nothing from `policy`.

### P2 `PolicyDials.paper_max_position_usd` — the ONE derivation of the paper cap
```python
# src/tradekit/policy/_dials.py, on PolicyDials
@property
def paper_max_position_usd(self) -> Decimal:
    """R-005's paper limit basis (`max_position_pct_paper * paper_starting_
    equity_usd`) exposed for the two `mae.size_position` call sites so the
    cap they clip to is the cap R-005 will measure against (ASSUMPTIONS 182)."""
    return self.max_position_pct_paper * self.paper_starting_equity_usd
```
Default dials -> `Decimal("50.00")`. `_check_r005` is NOT refactored to use it
(policy/ rule code untouched); AC-6 pins the equality behaviorally instead.

### P3 `hud._build._default_sizing_info` — passes what it already receives
Signature unchanged: `(symbol: str, limit_price: Decimal, equity_usd: Decimal)
-> SizingInfo` (it is a sanctioned seam; `test_build_state*.py` patch it by
that shape). Body:
```python
from tradekit.policy._dials import PolicyDials   # dials-only import, same fence thesis uses
dials = PolicyDials.load()
cap = dials.paper_max_position_usd if dials.default_account_ref.startswith("paper:") else None
result = mae.size_position(symbol, account_equity_usd=equity_usd, price=limit_price, max_position_usd=cap)
```
Quantization of `qty` to 8dp ROUND_DOWN stays (a no-op when the clip already
produced 8dp units).

### P4 `thesis._submit.build_submit_payloads` — reference price + cap
```python
entry = contract["entry"]
reference_price = (
    Decimal(str(entry["limit_price"])) if entry.get("limit_price") is not None else last_close
)
account_ref = str(contract["account_ref"])
dials = PolicyDials.load()
cap = dials.paper_max_position_usd if account_ref.startswith("paper:") else None
sizing = mae.size_position(
    symbol,
    account_equity_usd=dials.paper_starting_equity_usd,
    price=reference_price,
    max_position_usd=cap,
)
```
`last_close` is the existing quantized daily close used for the snapshot —
so a contract whose entry carries no `limit_price` sizes exactly as today.
`SizingComputedPayload` shape unchanged (`sizing` is the raw dict, which now
carries `max_position_usd` and possibly the warning — recorded verbatim).

### P5 `cadence._confirm_entry` — the market entry keeps its reference price
```python
contract["entry"] = {
    "order_type": "market",
    "limit_price": contract["entry"]["limit_price"],   # the ticket's limit price, unchanged
    "valid_until": contract["entry"]["valid_until"],
}
```
`EntrySpec.limit_price: Decimal | None` already permits this on a market
order; `_pipeline._entry_price` only reads it for `order_type == "limit"`, so
execution is unaffected (out of scope above).

### P6 `cadence.run_once` — dial equity for sizing; loud + skip on a dead account
```python
equity_usd, equity_warnings = _paper_equity_usd(account_ref)      # live: cash + marks (unchanged)
sizing_equity_usd = dials.paper_starting_equity_usd               # the basis policy uses
state = build_state(list(DEFAULT_SYMBOLS), captured_at=now, equity_usd=sizing_equity_usd)
...
if equity_usd <= 0:
    equity_warnings.append(
        f"{account_ref}: equity ${equity_usd} <= 0 — no AccountCreated on the ledger "
        "or cash exhausted; entries skipped this run (create it: tk account create-paper)"
    )
    entries, entry_warnings = [], []
else:
    entries, entry_warnings = _run_entries(ledger, state, skip_symbols)
```
Exits still run. The digest still writes. The `Drought` section still renders
(zero entries). `_paper_equity_usd` is unchanged.

### Files-touched set
`src/tradekit/mae/__init__.py`, `src/tradekit/policy/_dials.py` (property
only — policy/ touch => review round mandatory before the green commit),
`src/tradekit/hud/_build.py`, `src/tradekit/thesis/_submit.py`,
`src/tradekit/cadence/__init__.py`, `tests/ASSUMPTIONS.md` (182), tests below.

## 3. Acceptance criteria

Dial defaults throughout unless stated: `paper_starting_equity_usd=500`,
`max_position_pct_paper=0.10` (cap $50), `sizing_tolerance_pct=0.01`,
`min_notional_usd=10`, `default_account_ref="paper:alpha"`,
`risk_pct_per_trade=0.01`, `atr_multiplier=2.0`.

Two fixtures, named so tests can cite them:
- **F-TIGHT** (T1 shape): 30 daily bars flat `open=close=100, high=101,
  low=99` -> ATR(14)=2, stop_distance=4. At price 100: stop_pct 4%,
  risk $5, uncapped units 1.25, uncapped size $125.
- **F-WIDE** (T2 shape): 30 daily bars flat `open=close=100, high=110,
  low=90` -> ATR(14)=20, stop_distance=40. At price 105: units 0.125,
  size $13.125 (under the cap, over the $10 floor). At price 100: $12.50.

### `mae.size_position` (P1)
- **AC-1** GIVEN F-WIDE daily bars WHEN `size_position("ETH/USD",
  Decimal("500"), price=Decimal("105"))` THEN `current_price == 105.0`,
  `stop_pct == pytest.approx(40/105)`, `recommended_units ==
  pytest.approx(0.125)`, `recommended_size_usd == pytest.approx(13.125)`,
  `max_position_usd is None`, `"capped_by_max_position" not in warnings`.
- **AC-2** GIVEN F-WIDE WHEN called WITHOUT `price` THEN the output dict is
  key-for-key equal to today's (`current_price == 100.0`, size 12.5) except
  for the new `max_position_usd: None` key. (Regression pin — the existing
  `test_size_position_verb.py` suite must pass unchanged.)
- **AC-3** GIVEN F-TIGHT WHEN `size_position(..., price=Decimal("100"),
  max_position_usd=Decimal("50"))` THEN `recommended_units == 0.5`,
  `recommended_size_usd == 50.0`, `atr_position_size_usd ==
  pytest.approx(125.0)` (uncapped audit value kept), `max_position_usd ==
  50.0`, `"capped_by_max_position" in warnings`.
- **AC-4** (exact-arithmetic boundary) GIVEN F-TIGHT WHEN
  `price=Decimal("3")`, `max_position_usd=Decimal("50")` THEN
  `Decimal(str(recommended_units)) == Decimal("16.66666666")` and
  `Decimal(str(recommended_units)) * Decimal("3") <= Decimal("50")`. Repeat
  for `price=Decimal("266.00")` and `price=Decimal("0.00007")`: the product
  of the 8dp units and the price never exceeds the cap.
- **AC-5** GIVEN F-WIDE WHEN `max_position_usd=Decimal("50")` (cap not
  binding: $13.125) THEN output equals AC-1's except `max_position_usd ==
  50.0`; no warning.
- **AC-6a** WHEN `max_position_usd=Decimal("0")` or `Decimal("-1")` THEN
  `ValueError` whose message contains `"max_position_usd"`; no bars are
  fetched? — not required; only the raise is pinned.
- **AC-6b** WHEN `price=Decimal("0")` THEN `ValueError` (the existing
  `atr_position` message).

### `PolicyDials.paper_max_position_usd` (P2)
- **AC-7** GIVEN default dials THEN `paper_max_position_usd ==
  Decimal("50.00")`; GIVEN `paper_starting_equity_usd=1000,
  max_position_pct_paper=0.05` THEN `Decimal("50.00")` too (product, not a
  constant).
- **AC-8** (equality with the rule, BEHAVIOR through the real engine) GIVEN
  a real paper account for the default ref and a `submit_order` proposal
  WHEN `policy.evaluate` runs THEN the R-005 `RuleHit.limit` parses to a
  `Decimal` equal to `PolicyDials.load().paper_max_position_usd`.

### `hud.build_state` preview (P3) — `sizing_info` seam LEFT REAL
Seams allowed: `mae._runtime.get_daily_bars` (F-TIGHT/F-WIDE),
`mae._runtime.get_closed_bars` (the 1h bars the funnel prices the ticket
from; last close = the ticket price), `mae._runtime.clock`, `scan_setup`
(trivially passing), `open_position_symbols`. `evaluate_policy` and
`sizing_info` stay at their defaults. Real `broker.create_paper_account`.
- **AC-9** (T1 at preview) GIVEN F-TIGHT daily bars and 1h bars closing at
  100 WHEN `build_state(["ETH/USD"], ...)` THEN exactly one ticket;
  `ticket.quantity == Decimal("0.5")`; `ticket.limit_price ==
  Decimal("100")`; the `policy_verdict` gate `passed` is True. (Today: zero
  tickets, R-005 `50.73`-style deny — the test must fail on `main`.)
- **AC-10** (price basis is the 1h close) GIVEN F-WIDE daily bars and 1h
  bars closing at 105 THEN one ticket with `quantity == Decimal("0.125")`
  and `limit_price == Decimal("105")`; ticket `sl_price == 105 - 40 = 65`
  (stop distance from ATR, unchanged convention).
- **AC-11** (default_account_ref not paper -> no cap; CONTRACT on the seam
  default) GIVEN F-TIGHT WHEN `tradekit.hud._build.sizing_info("ETH/USD",
  Decimal("100"), Decimal("500"))` (the module-level seam name, at its
  default) is called with `PolicyDials.load()` returning
  `default_account_ref="advisory:kraken"` THEN `SizingInfo.qty ==
  Decimal("1.25")` (uncapped); with the default `"paper:alpha"` THEN
  `qty == Decimal("0.5")`, `stop_distance_usd == Decimal("4")`. Patch dials
  the way `test_run_once.py::_patch_dials` does (`PolicyDials.load`), never
  the rule engine.

### `thesis.submit` (P4)
Harness: `tests/unit/thesis/test_submit.py`'s style — real ledger under
`TK_DATA_DIR` isolation, `thesis.draft(contract)` then `thesis.submit`,
read the `SizingComputed` event back.
- **AC-12** GIVEN F-WIDE daily bars and a `paper:alpha` contract whose entry
  is `{"order_type": "market", "limit_price": "105", "valid_until": ...}`
  WHEN submitted THEN `SizingComputed.sizing.current_price == 105.0`,
  `recommended_size_usd == pytest.approx(13.125)`, `max_position_usd ==
  50.0`, `account_equity_usd == Decimal("500")`; `MarketSnapshotTaken.
  last_close` is still the DAILY close `100` (snapshot semantics unchanged).
- **AC-13** GIVEN the same contract with NO `limit_price` on the entry
  (`{"order_type": "market", "valid_until": ...}`) THEN `current_price ==
  100.0` and `recommended_size_usd == pytest.approx(12.5)` (today's
  behavior, pinned).
- **AC-14** GIVEN F-TIGHT and a limit entry at `100` THEN
  `recommended_size_usd == 50.0`, `recommended_units == 0.5`,
  `"capped_by_max_position" in sizing["warnings"]`.

### `cadence.run_once` (P5, P6) — real `build_state`, real `thesis`, real
`policy`, real `broker`; seams only `mae._runtime.get_daily_bars` /
`get_closed_bars` / `clock` and `hud._build.scan_setup`. Mirror
`test_run_once.py::test_run_once_with_real_build_state_opens_one_paper_position`.
- **AC-15** (the T2 reproduction) GIVEN F-WIDE daily bars, 1h bars closing
  at `105`, a fresh `paper:alpha` account (principal 500) WHEN `run_once`
  THEN exactly one paper position opens for the symbol; the run's digest
  section has NO `entry denied by policy` line; the ledger has exactly one
  `ThesisDrafted` and zero `ThesisRejected` for that symbol; the drafted
  contract's `entry` is `{"order_type": "market", "limit_price": "105",
  "valid_until": <iso>}` (P5). Must FAIL on `main` (R-012 deviation 0.05).
- **AC-16** (the T1 reproduction) GIVEN F-TIGHT daily bars and 1h close 100
  THEN one position opens; its `qty == Decimal("0.5")`... NOTE the executed
  qty is `recorded_size / entry_price` where `entry_price` is the SNAPSHOT
  daily close (100 here, equal to the 1h close by fixture design) — assert
  `qty == Decimal("0.5")` and notional `== Decimal("50")`; R-005 allowed.
  Must FAIL on `main` (no ticket at preview).
- **AC-17** (sizing basis is the dial, not live cash) GIVEN F-WIDE, 1h close
  105, and `paper:alpha` created with `principal_usd=400` THEN the opened
  position's `SizingComputed.account_equity_usd == Decimal("500")` and
  `recommended_size_usd == pytest.approx(13.125)` (would be $10.50 at $400).
- **AC-18** (T3, dead account is loud and skips entries) GIVEN F-WIDE, a
  passing setup, and NO `AccountCreated` for `paper:alpha` WHEN `run_once`
  THEN the digest section's `### Warnings` contains a line containing all
  of `paper:alpha`, `<= 0`, `no AccountCreated`, and `tk account
  create-paper`; the ledger has ZERO `ThesisDrafted` events; the section
  still carries `### Drought`; `run_once` does not raise.
- **AC-19** (T3 does not fire on a live account) GIVEN a created account
  with principal 500 THEN no warning line contains `no AccountCreated`.

## 4. Test plan sketch

| AC | kind | file | note |
|---|---|---|---|
| 1-6 | CONTRACT (+ GOLDEN for AC-4: independent derivation = hand Decimal math in the test, `Decimal("50")/Decimal("3")` quantized) | `tests/unit/mae/test_size_position_cap.py` | seam `tradekit.mae._runtime.get_daily_bars` (dotted string, as `test_get_regime_verb.py`) |
| 7 | CONTRACT | `tests/unit/policy/test_dials.py` (extend) | pure |
| 8 | BEHAVIOR | `tests/unit/policy/test_dials.py` (extend) | real `policy.evaluate`, paper account via `broker.create_paper_account` |
| 9-11 | BEHAVIOR | `tests/unit/hud/test_build_state_sizing_basis.py` (new) | harness of `test_build_state_preview_policy.py` MINUS the `sizing_info` patch; `_bars` seam must branch on timeframe (`"1d"` -> fixture daily bars via `get_daily_bars`, `"1h"` -> flat bars at the ticket price) |
| 12-14 | BEHAVIOR | `tests/unit/thesis/test_submit_sizing_basis.py` (new) | read `SizingComputed` back via `ledger.query(EventFilter(types=[...]))` |
| 15-19 | SEAM/BEHAVIOR | `tests/unit/cadence/test_run_once_sizing.py` (new) | copy the harness of `test_run_once_with_real_build_state_opens_one_paper_position`; digest under `tmp_path` |

Discriminating requirement: AC-9, AC-15, AC-16 MUST fail on `main` (run
them once against the parent commit in the red stage and record the
failure text in the red commit message). AC-2/AC-13 are the "nothing else
moved" pins.

Banned here (tk-tdd): mocking `policy.evaluate`, `thesis.submit`, or
`mae.size_position`; asserting on `_deferrable_at_preview` or any private;
a test whose fixture price equals the daily close on the T2 tests (it would
pass on `main`).

## 5. Unknowns register

- **U1 (parked, CTO)** When `pnl_daily` finally feeds `_paper_equity`
  (ASSUMPTIONS 62), the sizing basis must move with it on both sides —
  `cadence.run_once` (`sizing_equity_usd`) and `thesis._submit`. Record in
  ASSUMPTIONS 182 as a forward pin; no code now.
- **U2 (parked)** `tk hud --equity N` with `N != 500` sizes at N, then the
  hud-ack confirm path submits at the dial -> the same R-012 mismatch this
  spec fixes for the cadence. Manual path, Mike's hands, not the record.
  Recommend a later one-liner: `--equity` defaults to the dial. Not this
  sprint.
- **U3 (accepted)** The two `size_position` calls in one cadence run can
  straddle a daily bar close (00:00 UTC run starts at :00:03; both calls
  land within the same second in practice). If it ever bites, the binding
  R-012 deny is loud in the digest. No pin.
- **U4 (parked, decision for Mike/CTO)** R-007 counts `ActionProposed`
  including denied binding attempts. Conservative for live; for paper it
  turned a sizing bug into a daily lockout. Leave as is; revisit only if
  denied-at-binding drafts reappear after this lands.
- **U5 (filled, tk-fill-blanks)** Cap applies to `paper:` refs only.
  Reason: R-005's live leg is `5% * principal`, a different basis; passing
  the paper cap to a live-ref sizing would be a silent live-path change.
  Live is locked anyway; when P4 probation arrives, `size_position` gets
  the live cap from the same property pattern (`live_max_position_usd`
  needs the principal, which lives in the ledger -> a broker-side derivation
  then).
