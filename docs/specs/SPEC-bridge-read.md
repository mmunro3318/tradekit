# SPEC-bridge-read — UIA probe + driver read verbs + reconcile-aid CLI

> Feature 1+2 of docs/design/BRIDGE-UIA.md. Branch `feature/bridge-read`.
> READ-ONLY throughout: nothing in this feature clicks, types, or submits.
> Write verbs, UiaBroker, and the `prop:` routing are feature 3 (OUT).

## Scope

A read-only probe script that dumps Kraken Desktop's UIA tree and grades
its accessibility exposure (A/B/C, design U4), an element-map data format
pinned to that dump, a `tradekit.bridge` driver exposing the two read
verbs (`snapshot()`, `read_ticket()`) over an injectable `UiaSession`
seam, a parser turning raw panel text into typed Decimal readouts, and a
`tk bridge snapshot` CLI that serves as the standalone reconcile aid.

**Out of scope (feature 3+):** write verbs (`select_*`, `fill_ticket`,
`submit_ticket`, `read_confirmation`); `UiaBroker`/BrokerPort conformance;
`prop:` routing; `VenueAmbiguous`; caps/kill-switch/ttl;
`bridge_execution_enabled` dial; any ledger writes; fills/history mapping
(U5); the dry-run protocol.

## Interface pins

```python
# tradekit/bridge/_session.py — THE determinism seam (design §7)
class UiaNode(Protocol):
    @property
    def node_id(self) -> str: ...          # stable within one tree dump
    @property
    def role(self) -> str: ...             # UIA control type name
    @property
    def name(self) -> str: ...             # UIA Name property ("" if unset)
    @property
    def automation_id(self) -> str: ...    # "" if unset
    @property
    def value(self) -> str: ...            # Value/Text pattern text, "" if none
    def children(self) -> list["UiaNode"]: ...

class UiaSession(Protocol):
    def root(self) -> UiaNode: ...         # raises AppNotFound if app absent

# tradekit/bridge/_errors.py
class BridgeError(Exception): ...
class AppNotFound(BridgeError): ...            # Kraken Desktop not running
class ElementMapMiss(BridgeError): ...         # .selector: str, .hint: str
class AmbiguousElement(BridgeError): ...       # >1 match; .selector, .count
class PanelParseError(BridgeError): ...        # .field, .raw_text

# tradekit/bridge/__init__.py — public verbs (feature-2 surface)
def snapshot(*, session: UiaSession | None = None) -> PropPanelSnapshot
def read_ticket(*, session: UiaSession | None = None) -> TicketReadback
# session=None -> real pywinauto-backed session (Windows + extra "bridge"
# dependency group); injection is for tests/fixtures ONLY.

# tradekit/contracts/_bridge.py — payloads (FrozenModel; money Decimal)
class PropPositionRow(FrozenModel):
    symbol: str
    side: Literal["long", "short"]
    qty: Decimal
    entry_price: Decimal
    unrealized_pnl_usd: Decimal

class PropPanelSnapshot(FrozenModel):
    captured_at: AwareDatetime          # supplied by caller/CLI, not wall-clocked in the driver
    account_name: str                   # e.g. "Starter Eval 1"
    instrument: str                     # currently selected market
    balance_usd: Decimal
    equity_usd: Decimal | None          # None when panel doesn't show it
    mdl_remaining_usd: Decimal
    mdd_remaining_usd: Decimal
    target_remaining_usd: Decimal | None
    positions: tuple[PropPositionRow, ...]

class TicketReadback(FrozenModel):
    account_name: str
    instrument: str
    side: Literal["buy", "sell"] | None     # None = no side selected yet
    order_type: str                          # venue's own label, verbatim
    qty: Decimal | None
    limit_price: Decimal | None
    stop_price: Decimal | None
```

Element map: `src/tradekit/bridge/elementmaps/kraken-<app_version>.json`
— `{"app_version": str, "captured_utc": str, "selectors": {<logical>:
{"by": "automation_id" | "name" | "path", "value": str | list[str]}}}`.
Logical selector names are pinned constants in `_elementmap.py`
(`ACCOUNT_NAME`, `BALANCE`, `MDL_REMAINING`, `MDD_REMAINING`,
`TARGET_REMAINING`, `INSTRUMENT`, `POSITIONS_TABLE`, `TICKET_*`). The
probe artifact `docs/research/uia-probe-kraken-<date>.json` is the map's
derivation source and is committed.

Probe: `scripts/probe_uia_kraken.py [--out PATH]` — connects, dumps the
full tree (role/name/automation_id/value per node, recursive), writes
JSON artifact with `exposure_grade` field, prints grade + summary. Grade
rule (pinned): **A** = every `selectors` logical target resolvable by
`automation_id`; **B** = all resolvable but ≥1 only by `name`/`path`;
**C** = ≥1 target unresolvable (canvas/opaque) → STOP per design U4.

Numeric text parse rule (pinned): optional `$`, thousands commas,
optional leading `-`, optional trailing `%` (rejected for money fields);
anything else — parentheses negatives, suffixed units, empty string —
raises `PanelParseError(field, raw_text)`. Decimal via `contracts.quantize`
(cent quantization for `*_usd` fields); never float.

## Acceptance criteria

- **AC-1** GIVEN a fixture tree with all logical selectors resolvable by
  automation_id WHEN `snapshot(session=fake)` runs THEN it returns a
  `PropPanelSnapshot` whose every `*_usd` field is a cent-quantized
  Decimal exactly matching the hand-transcribed golden for that fixture.
- **AC-2** GIVEN the app session raises AppNotFound WHEN `snapshot()`
  runs THEN `AppNotFound` propagates typed (never a bare COM/pywinauto
  error, never a fabricated snapshot).
- **AC-3** GIVEN a fixture tree missing the `BALANCE` selector WHEN
  `snapshot()` runs THEN `ElementMapMiss` is raised carrying
  `selector="BALANCE"` and a hint naming the nearest-role candidates —
  never a partial snapshot with a defaulted balance.
- **AC-4** GIVEN a fixture tree where the `BALANCE` selector matches two
  nodes WHEN `snapshot()` runs THEN `AmbiguousElement(selector, count=2)`
  is raised — first-match is never silently taken.
- **AC-5** GIVEN a balance cell reading `"$5,000.00"` THEN it parses to
  `Decimal("5000.00")`; GIVEN `"-$12.34"` or `"-12.34"` THEN
  `Decimal("-12.34")`; GIVEN `"(12.34)"` or `""` or `"5 000,00"` THEN
  `PanelParseError` naming the field and raw text.
- **AC-6** GIVEN a positions table with zero data rows THEN
  `snapshot().positions == ()` (empty, not an error); GIVEN two rows THEN
  rows appear in on-screen order with Decimal qty/prices.
- **AC-7** GIVEN a ticket with no side selected and empty qty THEN
  `read_ticket()` returns `side=None, qty=None` (empty-form is a valid
  readback, not an error) with `order_type` verbatim.
- **AC-8** GIVEN any fixture WHEN `snapshot()`/`read_ticket()` run THEN
  the session recording shows ONLY read operations — zero
  invoke/click/set/keyboard calls (read-only guarantee, enforced by the
  fake's call log).
- **AC-9** GIVEN Kraken Desktop absent WHEN `tk bridge snapshot` runs
  THEN exit code 2 with a one-line "Kraken Desktop not running" message;
  GIVEN a parse failure THEN exit 3 naming field + raw text; GIVEN
  success THEN exit 0 and the snapshot as JSON (Decimals as strings) on
  stdout, nothing else on stdout.
- **AC-10** GIVEN `tradekit.bridge` imported without the `bridge`
  dependency group installed (pywinauto absent) THEN importing the
  PACKAGE succeeds and constructing the REAL session raises
  `BridgeError` with the install hint (`uv sync --group bridge`);
  fixture-injected sessions work without pywinauto (CI/linux stay green).
- **AC-11** GIVEN a probe dump artifact WHEN the grade rule is applied
  THEN grade A/B/C follows the pinned rule exactly (one fixture per
  grade), and the artifact JSON round-trips (load → same tree).
- **AC-12** GIVEN an element map whose `app_version` differs from the
  connected app's version WHEN `snapshot()` runs THEN the snapshot still
  attempts resolution but the result's provenance warning is emitted via
  the CLI on stderr (map drift is visible, not fatal, for READ verbs).

## Test plan sketch

| AC | Kind | Notes |
|---|---|---|
| AC-1 | GOLDEN | derivation: committed probe artifact + hand transcription (CTO re-derives pre-freeze); until the real probe runs, the fixture is the SYNTHETIC tree from this spec's authoring, replaced by real-probe fixtures in the same batch that lands the artifact |
| AC-2/3/4 | BEHAVIOR | FakeUiaSession variants |
| AC-5 | GOLDEN | parse table, hand-derived |
| AC-6/7 | BEHAVIOR | fixture variants |
| AC-8 | SEAM | fake's call-log assertion |
| AC-9 | CONTRACT | CLI via typer runner |
| AC-10 | SEAM | import guard; monkeypatched absent module |
| AC-11 | BEHAVIOR + GOLDEN | grade rule fixtures |
| AC-12 | BEHAVIOR | stderr warning assertion |

## Unknowns register (feature-local)

| # | Question | Status |
|---|---|---|
| S1 | Real panel field labels/format (currency, MDL phrasing) | PARKED on probe artifact — parser rules pinned above are the contract; fixtures swap from synthetic to real in the probe-landing batch, goldens re-frozen through the golden gate. |
| S2 | Kraken app_version detection method | RESOLVED (fill-blanks): window title parse if present, else map's `app_version` echoed with a "unverified" provenance flag — never blocks a read. |
| S3 | Electron accessibility activation flag needed? | PARKED on probe: probe tries plain attach first, records whether a renderer-accessibility nudge was required, artifact notes it. |
