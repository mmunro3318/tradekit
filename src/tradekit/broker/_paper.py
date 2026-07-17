"""`PaperBroker` — our own deterministic paper-fill adapter (DESIGN §8.3,
TD-7, SPRINT P3 batch B, Opus-gated fill model). Implements `BrokerPort`
(`_port.py`) structurally (no inheritance needed — the Protocol is
`runtime_checkable` and duck-typed).

State discipline (CTO pin, binding): a `PaperBroker` instance holds NO
mutable trading state of its own — `account_ref` and a `Ledger` handle are
the only instance attributes. Every other value (`account()`, `positions()`,
`fills()`) is a projection computed FRESH from ledger events
(`AccountCreated` for principal, `FillRecorded` history for realized cash/
positions) on every call — the same "ledger events only" discipline as
`thesis`/`policy`'s read verbs, so two `PaperBroker(account_ref=...)`
instances pointed at the same ledger always agree, and replaying the event
log reproduces identical state (§8.3's determinism pin, TD-18 ring 3).

Fill model (§8.3, the sprint's pre-registered Opus review focus — pinned
here for the batch-B dev pass; `tests/unit/broker/test_paper_fills.py` is
the executable spec, `test_paper_account_state.py` covers the ledger-
projection arithmetic):

  MARKET orders — price = the latest CLOSED cached bar's `close` (fetched
  via `mae._runtime.get_closed_bars`, the module-attribute form, same
  sanctioned-seam discipline as `thesis._grade_wiring`) as the venue MID,
  adjusted by the half-spread from `tradekit.costs.price_friction(venue,
  asset_class, notional_usd, side)` — BUY pays UP (`mid * (1 +
  half_spread_rate)`), SELL receives DOWN (`mid * (1 - half_spread_rate)`).
  `notional_usd` for the friction lookup is `mid * qty` (the pre-adjustment
  notional — friction prices OFF the mid, not off its own output, avoiding
  circularity). The SAME `Friction.fee_usd` is charged as a separate fee
  field (never folded into the fill price). The quote snapshot
  (`ts_open`/`close`/`source` of the bar that priced the fill) is stored ON
  the `FillRecordedPayload` — every paper fill auditable (§8.3).

  LIMIT orders — rest until a LATER closed bar trades THROUGH the limit by
  >= 1 tick: a buy limit `L` fills when `bar.low <= L - tick_size`; a sell
  limit `L` fills when `bar.high >= L + tick_size`. An exact touch
  (`bar.low == L` / `bar.high == L`) is NEVER a fill (G5). Fill price is the
  LIMIT price itself, not the bar's through price (conservative — no
  assumption of favorable execution). No partial fills in MVP: an order
  either fills its full `qty` in one `FillRecorded` event or stays
  `OrderStatus(status="open")` forever (until canceled, out of scope this
  batch). Evaluation trigger (ASSUMPTIONS round-17 entry 110, CTO-ratified):
  `order_status(order_id)` is the poll point — it re-derives the resting
  order's terms from its own `OrderSubmitted` event, fetches closed bars,
  and appends `FillRecorded` the first time a LATER bar (one whose
  `ts_open` is strictly after the order's own submission `ts_utc`) trades
  through; earlier bars (including the one live at submission time) never
  count, so a limit can't fill against the quote it was placed against.

  Unknown symbol / no cached bars: a market evaluation that cannot fetch ANY
  closed bars for `order.asset.symbol` raises `broker._port.
  NoQuoteAvailable` (CTO adjudication, ASSUMPTIONS Round-17 entry 111 —
  pinned, no longer open) and appends ZERO events — never a guess-fill; a
  broker that invents prices is the exact fabrication class ASSUMPTIONS 71
  exists to kill. Checked BEFORE any `OrderSubmitted`/`OrderAck` write, so
  the refusal is a true no-op on the ledger.

Token gate (§8.2/§15 — REAL verification, CTO adjudication 2026-07-17,
pulled forward from batch C): the originally-planned batch-B "shape-only"
check was proven dishonest by the conformance suite itself — no string-
shape property separates a registered token from an unregistered one — so
`_verify_token` verifies against the LEDGER now. A token is valid iff this
broker's ledger contains a `VerdictIssued` event whose payload
`verdict_id == token.verdict_id` AND `allow` is true AND
`policy_version_hash` matches the token's. Missing/`None` token, a
well-shaped-but-unregistered token, and a registered-but-deny verdict all
raise the ONE refusal type (`BrokerTokenRequired`) with the reason in the
message. Verification runs FIRST, before any bar fetch or ledger write —
an invalid token can never reach the quote path (`NoQuoteAvailable` is
strictly second in the check order; pinned by the conformance suite's
unregistered-token case, which supplies no bar fixture at all). Batch C's
two-phase pipeline (`policy.evaluate` -> `VerdictIssued` ->
`execute_order` -> `adapter.submit`) is the normal producer of these
events; test fixtures seed them directly (the earned-allow rule — same
class of adjudication as P2 batch C's R-010 "the allow path must be
earned" call). `_verify_token` below is the documented seam batch C may
further harden (consumption/no-later-deny/thesis linkage); it must not be
reimplemented ad hoc elsewhere.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from ulid import ULID

from tradekit import costs
from tradekit.broker._port import BrokerTokenRequired, NoQuoteAvailable
from tradekit.contracts import (
    AccountState,
    AssetRef,
    Bar,
    Event,
    EventFilter,
    Fill,
    FillRecordedPayload,
    OrderAck,
    OrderAckPayload,
    OrderRequest,
    OrderStatus,
    OrderSubmittedPayload,
    Position,
    VerdictToken,
)
from tradekit.ledger import Ledger, default_ledger
from tradekit.mae import _runtime as _mae_runtime

# 'agent:<model>' | 'mike' | 'system:<job>' — a paper fill is a machine-
# derived ledger append, same actor convention as tradekit.broker's
# create_paper_account / tradekit.thesis's _ACTOR.
_ACTOR = "system:paper-broker"

# get_closed_bars(symbol, timeframe, lookback_days) — PaperBroker always
# prices off daily bars, matching the sprint's own hand-derived fixtures
# (mid=50000.00 etc. read as daily closes). lookback_days is generous
# because bar fakes in tests ignore it entirely; a real provider only needs
# enough history to have SOME closed bar.
_TIMEFRAME = "1d"
_LOOKBACK_DAYS = 30


class PaperBroker:
    """One named paper account (`"paper:alpha"`, `"paper:conformance-
    suite"`, ...), a ledger projection — see module docstring for the "no
    mutable broker state" discipline and the fill model this batch pins."""

    def __init__(self, account_ref: str, ledger: Ledger | None = None) -> None:
        self.account_ref = account_ref
        self._ledger = ledger if ledger is not None else default_ledger()

    # ------------------------------------------------------------------
    # Read verbs — pure projections over ledger events (no mutable state).
    # ------------------------------------------------------------------

    def account(self) -> AccountState:
        """`AccountState` from `AccountCreated.principal_usd` + realized
        `FillRecorded` history (settled cash = principal + Sigma(sell
        proceeds - buy cost - fees), §8.1/TD-24)."""
        principal = self._principal_usd()
        cash = principal
        for fill in self._fill_events():
            notional = fill["price"] * fill["qty"]
            if fill["side"] == "buy":
                cash -= notional + fill["fees_usd"]
            else:
                cash += notional - fill["fees_usd"]
        # No margin modeled in MVP (ASSUMPTIONS round-17 entry 108,
        # CTO-ratified): a cash-settled paper account's buying power and
        # equity both collapse to settled cash.
        return AccountState(
            account_ref=self.account_ref,
            equity_usd=cash,
            settled_cash_usd=cash,
            buying_power_usd=cash,
        )

    def positions(self) -> list[Position]:
        """Position qty/avg_price per symbol, derived from `FillRecorded`
        history for this `account_ref` (§8.1). A symbol whose net fill qty
        nets to zero is OMITTED (ASSUMPTIONS round-17 entry 109,
        CTO-ratified) — never returned as a zero-qty row."""
        by_symbol: dict[str, tuple[Decimal, Decimal]] = {}
        for fill in self._fill_events():
            symbol = fill["symbol"]
            qty, avg_price = by_symbol.get(symbol, (Decimal("0"), Decimal("0")))
            if fill["side"] == "buy":
                new_qty = qty + fill["qty"]
                avg_price = (
                    fill["price"]
                    if qty == 0
                    else (qty * avg_price + fill["qty"] * fill["price"]) / new_qty
                )
                qty = new_qty
            else:
                qty = qty - fill["qty"]
            by_symbol[symbol] = (qty, avg_price)

        return [
            Position(account_ref=self.account_ref, symbol=symbol, qty=qty, avg_price=avg_price)
            for symbol, (qty, avg_price) in by_symbol.items()
            if qty != 0
        ]

    def fills(self, since: datetime) -> list[Fill]:
        """`FillRecorded` events at/after `since` for this `account_ref`,
        ASCENDING by `ts_utc` (§8.1's conformance pin)."""
        out = []
        for event in self._ledger.query(EventFilter(types=["FillRecorded"], since=since)):
            payload = event.payload
            if payload.get("account_ref") != self.account_ref:
                continue
            out.append(
                Fill(
                    order_id=payload["order_id"],
                    thesis_id=payload["thesis_id"],
                    ts_utc=payload["ts_utc"],
                    price=Decimal(str(payload["price"])),
                    qty=Decimal(str(payload["qty"])),
                    fees_usd=Decimal(str(payload["fees_usd"])),
                    quote_snapshot=payload.get("quote_snapshot", {}),
                )
            )
        out.sort(key=lambda f: f.ts_utc)
        return out

    # ------------------------------------------------------------------
    # Write verbs.
    # ------------------------------------------------------------------

    def submit(self, order: OrderRequest, verdict: VerdictToken) -> OrderAck:
        """Validate `verdict` via `_verify_token` (shape-only this batch,
        see module docstring), then evaluate the market fill model (§8.3)
        and append `OrderSubmitted`/`OrderAck`/`FillRecorded`, or — for a
        limit order — leave it resting (`OrderSubmitted`/`OrderAck` only,
        until a later `order_status` check trades through it)."""
        self._verify_token(verdict)

        now = _mae_runtime.clock()

        if order.order_type == "market":
            bar_series = _mae_runtime.get_closed_bars(
                order.asset.symbol, _TIMEFRAME, _LOOKBACK_DAYS
            )
            if not bar_series.bars:
                raise NoQuoteAvailable(
                    f"no cached closed bars for symbol={order.asset.symbol!r} — refusing to "
                    "guess a fill price (ASSUMPTIONS round-17 entry 111)"
                )
            bar = bar_series.bars[-1]

            order_id = str(ULID())
            self._append_order_submitted(order, order_id, now)
            self._append_order_ack(order_id, now)
            self._evaluate_and_record_market_fill(
                order=order, order_id=order_id, bar=bar, source=bar_series.source, now=now
            )
            return OrderAck(order_id=order_id, status="accepted", ts_utc=now)

        # Limit (and stop/stop_limit, treated as resting-limit this batch —
        # no test exercises stop orders yet): record intent, evaluate later.
        order_id = str(ULID())
        self._append_order_submitted(order, order_id, now)
        self._append_order_ack(order_id, now)
        return OrderAck(order_id=order_id, status="accepted", ts_utc=now)

    def order_status(self, order_id: str) -> OrderStatus:
        """Current lifecycle status of a previously-submitted order —
        `"filled"` immediately for a market order (§8.3: no partials, fills
        synchronously at `submit()` time against the latest closed bar),
        `"open"` for a limit order until a later closed bar trades through
        it — THIS call is the polling point that evaluates and appends the
        fill (ASSUMPTIONS round-17 entry 110, CTO-ratified)."""
        submitted = self._order_submitted_event(order_id)
        if submitted is None:
            return OrderStatus(order_id=order_id, status="rejected")

        existing_fill = self._fill_for_order(order_id)
        if existing_fill is not None:
            return OrderStatus(
                order_id=order_id,
                status="filled",
                filled_qty=existing_fill["qty"],
                remaining_qty=Decimal("0"),
            )

        payload = submitted.payload
        qty = Decimal(str(payload["qty"]))
        if payload["order_type"] != "limit" or payload.get("limit_price") is None:
            # Market orders fill synchronously at submit() time; anything
            # else without a limit_price has nothing further to evaluate.
            return OrderStatus(order_id=order_id, status="open", remaining_qty=qty)

        asset = AssetRef.model_validate(payload["asset"])
        limit_price = Decimal(str(payload["limit_price"]))
        side = payload["side"]
        submitted_ts = _as_datetime(payload["ts_utc"])

        bar_series = _mae_runtime.get_closed_bars(asset.symbol, _TIMEFRAME, _LOOKBACK_DAYS)
        later_bars = sorted(
            (b for b in bar_series.bars if b.ts_open > submitted_ts), key=lambda b: b.ts_open
        )
        for bar in later_bars:
            if self._limit_trades_through(side, limit_price, asset.tick_size, bar):
                self._record_limit_fill(
                    order_id=order_id,
                    thesis_id=payload["thesis_id"],
                    asset=asset,
                    side=side,
                    qty=qty,
                    limit_price=limit_price,
                    bar=bar,
                    source=bar_series.source,
                )
                return OrderStatus(
                    order_id=order_id, status="filled", filled_qty=qty, remaining_qty=Decimal("0")
                )

        return OrderStatus(order_id=order_id, status="open", remaining_qty=qty)

    def _verify_token(self, verdict: VerdictToken | None) -> None:
        """Documented seam (§8.2/§15): REAL ledger-side verification (CTO
        adjudication 2026-07-17, batch C's hardening pulled forward — the
        conformance suite proved a shape-only check dishonest). A token is
        valid iff this ledger contains a `VerdictIssued` event whose payload
        `verdict_id == verdict.verdict_id` AND `allow` is true AND
        `policy_version_hash` matches the token's. Missing/None,
        unregistered, hash-mismatched, and registered-but-deny all raise the
        ONE refusal type, `BrokerTokenRequired`, with the reason in the
        message. Batch C may harden further (consumption, no-later-deny,
        thesis linkage) WITHOUT changing this method's name or call site."""
        if verdict is None:
            raise BrokerTokenRequired(
                f"PaperBroker({self.account_ref!r}).submit(...): no VerdictToken supplied "
                "(§8.2/§15 — an order without a preceding allow-verdict is structurally "
                "impossible)"
            )
        saw_verdict_id = False
        for event in self._ledger.query(EventFilter(types=["VerdictIssued"])):
            payload = event.payload
            if payload.get("verdict_id") != verdict.verdict_id:
                continue
            saw_verdict_id = True
            if (
                payload.get("allow") is True
                and payload.get("policy_version_hash") == verdict.policy_version_hash
            ):
                return
        if saw_verdict_id:
            raise BrokerTokenRequired(
                f"PaperBroker({self.account_ref!r}).submit(...): VerdictIssued "
                f"verdict_id={verdict.verdict_id!r} exists but is not a matching allow "
                "(deny verdict or policy_version_hash mismatch)"
            )
        raise BrokerTokenRequired(
            f"PaperBroker({self.account_ref!r}).submit(...): no VerdictIssued event on the "
            f"ledger for verdict_id={verdict.verdict_id!r} — token does not reference a real "
            "allow-verdict (§8.2/§15)"
        )

    # ------------------------------------------------------------------
    # Internal helpers.
    # ------------------------------------------------------------------

    def _append(self, event_type: str, payload: dict[str, Any], ts: datetime) -> str:
        event = Event(
            event_id=str(ULID()),
            ts_utc=ts,
            type=event_type,  # type: ignore[arg-type]
            actor=_ACTOR,
            run_id=None,
            schema_ver=1,
            payload=payload,
        )
        return self._ledger.append(event)

    def _append_order_submitted(self, order: OrderRequest, order_id: str, ts: datetime) -> None:
        payload = OrderSubmittedPayload(
            order_id=order_id,
            thesis_id=order.thesis_id,
            account_ref=order.account_ref,
            asset=order.asset.model_dump(mode="json"),
            side=order.side,
            order_type=order.order_type,
            qty=order.qty,
            limit_price=order.limit_price,
            ts_utc=ts,
        )
        self._append("OrderSubmitted", payload.model_dump(mode="json"), ts)

    def _append_order_ack(self, order_id: str, ts: datetime) -> None:
        payload = OrderAckPayload(order_id=order_id, status="accepted", ts_utc=ts)
        self._append("OrderAck", payload.model_dump(mode="json"), ts)

    def _evaluate_and_record_market_fill(
        self, *, order: OrderRequest, order_id: str, bar: Bar, source: str, now: datetime
    ) -> None:
        mid = bar.close
        notional_usd = mid * order.qty
        friction = costs.price_friction(
            order.asset.venue, order.asset.asset_class, notional_usd, order.side
        )
        half_spread_per_unit = friction.half_spread_usd / order.qty
        if order.side == "buy":
            fill_price = mid + half_spread_per_unit
        else:
            fill_price = mid - half_spread_per_unit

        self._append_fill(
            order_id=order_id,
            thesis_id=order.thesis_id,
            symbol=order.asset.symbol,
            side=order.side,
            price=fill_price,
            qty=order.qty,
            fees_usd=friction.fee_usd,
            quote_snapshot={
                "ts_open": bar.ts_open.isoformat(),
                "close": str(bar.close),
                "source": source,
            },
            ts=now,
        )

    def _record_limit_fill(
        self,
        *,
        order_id: str,
        thesis_id: str,
        asset: AssetRef,
        side: str,
        qty: Decimal,
        limit_price: Decimal,
        bar: Bar,
        source: str,
    ) -> None:
        notional_usd = limit_price * qty
        friction = costs.price_friction(asset.venue, asset.asset_class, notional_usd, side)  # type: ignore[arg-type]
        now = _mae_runtime.clock()
        self._append_fill(
            order_id=order_id,
            thesis_id=thesis_id,
            symbol=asset.symbol,
            side=side,
            price=limit_price,
            qty=qty,
            fees_usd=friction.fee_usd,
            quote_snapshot={
                "ts_open": bar.ts_open.isoformat(),
                "close": str(bar.close),
                "source": source,
            },
            ts=now,
        )

    def _append_fill(
        self,
        *,
        order_id: str,
        thesis_id: str,
        symbol: str,
        side: str,
        price: Decimal,
        qty: Decimal,
        fees_usd: Decimal,
        quote_snapshot: dict[str, Any],
        ts: datetime,
    ) -> None:
        payload = FillRecordedPayload(
            order_id=order_id,
            thesis_id=thesis_id,
            account_ref=self.account_ref,
            ts_utc=ts,
            price=price,
            qty=qty,
            fees_usd=fees_usd,
            side=side,  # type: ignore[arg-type]
            quote_snapshot=quote_snapshot,
            symbol=symbol,
        )
        self._append("FillRecorded", payload.model_dump(mode="json"), ts)

    @staticmethod
    def _limit_trades_through(
        side: str, limit_price: Decimal, tick_size: Decimal, bar: Bar
    ) -> bool:
        """G5: an exact touch is NEVER a fill — through-by->=1-tick only."""
        if side == "buy":
            return bar.low <= limit_price - tick_size
        return bar.high >= limit_price + tick_size

    def _principal_usd(self) -> Decimal:
        for event in self._ledger.query(EventFilter(types=["AccountCreated"])):
            if event.payload.get("account_ref") == self.account_ref:
                return Decimal(str(event.payload["config"]["principal_usd"]))
        return Decimal("0")

    def _fill_events(self) -> list[dict[str, Any]]:
        """This account's `FillRecorded` payloads, ASCENDING by `ts_utc`,
        as plain dicts with money fields normalized to `Decimal`."""
        rows = []
        for event in self._ledger.query(EventFilter(types=["FillRecorded"])):
            payload = event.payload
            if payload.get("account_ref") != self.account_ref:
                continue
            rows.append(
                {
                    "ts_utc": payload["ts_utc"],
                    "price": Decimal(str(payload["price"])),
                    "qty": Decimal(str(payload["qty"])),
                    "fees_usd": Decimal(str(payload["fees_usd"])),
                    "side": payload["side"],
                    "symbol": payload["symbol"],
                }
            )
        rows.sort(key=lambda r: r["ts_utc"])
        return rows

    def _order_submitted_event(self, order_id: str) -> Event | None:
        for event in self._ledger.query(EventFilter(types=["OrderSubmitted"])):
            if event.payload.get("order_id") == order_id:
                return event
        return None

    def _fill_for_order(self, order_id: str) -> dict[str, Any] | None:
        for event in self._ledger.query(EventFilter(types=["FillRecorded"])):
            if event.payload.get("order_id") == order_id:
                payload = event.payload
                return {
                    "price": Decimal(str(payload["price"])),
                    "qty": Decimal(str(payload["qty"])),
                    "fees_usd": Decimal(str(payload["fees_usd"])),
                }
        return None


def _as_datetime(value: Any) -> datetime:
    """`Event.payload` round-trips timestamps as ISO-8601 strings
    (`model_dump(mode="json")`) — normalize back to `datetime` for
    comparison against `Bar.ts_open`."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


__all__ = ["PaperBroker"]
