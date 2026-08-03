"""`PaperBroker`'s fill model (DESIGN §8.3, TD-7, TD-8) — SPRINT P3 batch B,
the sprint's pre-registered Opus review focus. `PaperBroker.submit`/
`order_status` are `NotImplementedError` stubs this batch
(`src/tradekit/broker/_paper.py`); every test below is RED for that reason —
assertions pin the EXACT arithmetic the dev pass must produce.

Freeze-gate arithmetic (venue=kraken, asset_class=crypto, ~$50 notional):
`tradekit.costs._TABLE[("kraken", "crypto")]` = (fee_rate=Decimal("0.0026"),
half_spread_rate=Decimal("0.0010")) — read directly off `src/tradekit/
costs.py` (TD-8, this is the ONE friction source, shared by PaperBroker/
backtester/metrics). At $50 notional, `_SLIPPAGE_FREE_NOTIONAL = Decimal(
"100")` means slippage is ALWAYS zero for these fixtures (50 <= 100) — the
derivations below never carry a slippage term.

Bar/clock fakes follow the house pattern (`thesis._grade_wiring`'s tests):
monkeypatch `"tradekit.mae._runtime.get_closed_bars"` / `"..._clock"` by
dotted STRING path so PaperBroker's real module-attribute call sees the
fake.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal

import pytest
from ulid import ULID

from tradekit.broker._paper import PaperBroker
from tradekit.broker._port import BrokerTokenRequired, NoQuoteAvailable
from tradekit.contracts import (
    AssetRef,
    Bar,
    BarSeries,
    Event,
    EventFilter,
    HaltClearedPayload,
    HaltSetPayload,
    OrderRequest,
    VerdictIssuedPayload,
    VerdictToken,
)
from tradekit.ledger import default_ledger

_ASSET = AssetRef(symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))
# In-kind-fee fixtures (SPEC-inkind-fees, AC-2..5) — venue MUST be alpaca:
# the in-kind withhold arithmetic is scoped to (venue="alpaca",
# asset_class="crypto") only; kraken keeps the USD-fee model (spec's
# "out of scope" list) and every _ASSET-based test above stays untouched.
_ALPACA_CRYPTO = AssetRef(
    symbol="ETH/USD", venue="alpaca", asset_class="crypto", tick_size=Decimal("0.01")
)
_ALPACA_EQUITY = AssetRef(
    symbol="AAPL", venue="alpaca", asset_class="equity", tick_size=Decimal("0.01")
)
_ACCOUNT_REF = "paper:fills-test"
_VERDICT = VerdictToken(verdict_id="v-1", policy_version_hash="0" * 64)
_T0 = datetime(2026, 1, 2, tzinfo=UTC)


def _seed_allow_verdict(
    account_ref: str = _ACCOUNT_REF,
    *,
    thesis_id: str | None = None,
    verdict_id: str = "v-1",
    ts_utc: datetime = _T0,
) -> None:
    """Earn the allow (CTO adjudication 2026-07-17, same class as P2 batch
    C's R-010 'the allow path must be earned' call): a `VerdictToken` is
    only valid because a REAL `VerdictIssued(allow=true)` event with a
    matching `verdict_id`/`policy_version_hash` sits on the ledger — batch
    C's pipeline is the normal producer; the harness appends it directly.

    `thesis_id` MUST match the order's own `thesis_id` (MED-2 thesis
    binding, P3 review fix) — callers pass the exact value the order under
    test will carry; `None` is a legitimate "no thesis" verdict (e.g. a
    reconcile-triggered action) but then only matches an order whose OWN
    `thesis_id` is also `None`."""
    default_ledger().append(
        Event(
            event_id=str(ULID()),
            ts_utc=ts_utc,
            type="VerdictIssued",
            actor="system:test-harness",
            run_id=None,
            schema_ver=1,
            payload=VerdictIssuedPayload(
                verdict_id=verdict_id,
                kind="submit_order",
                account_ref=account_ref,
                thesis_id=thesis_id,
                allow=True,
                policy_version_hash=_VERDICT.policy_version_hash,
            ).model_dump(mode="json"),
        )
    )


def _bars(bars: list[Bar], source: str = "fake-kraken"):
    def _get(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
        return BarSeries(asset=_ASSET, timeframe="1d", bars=bars, source=source)

    return _get


def _bar(ts_open: datetime, *, open_: str, high: str, low: str, close: str) -> Bar:
    return Bar(
        ts_open=ts_open,
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("100"),
    )


def _order(
    *,
    side: str,
    order_type: str = "market",
    qty: str = "0.001",
    limit_price: str | None = None,
) -> OrderRequest:
    return OrderRequest(
        thesis_id=f"TH-{side}-{order_type}",
        account_ref=_ACCOUNT_REF,
        asset=_ASSET,
        side=side,  # type: ignore[arg-type]
        order_type=order_type,  # type: ignore[arg-type]
        qty=Decimal(qty),
        limit_price=Decimal(limit_price) if limit_price is not None else None,
    )


# ---------------------------------------------------------------------------
# Market fills — arithmetic hand-derived from tradekit.costs._TABLE
# ---------------------------------------------------------------------------


def test_market_buy_fills_at_mid_plus_half_spread_with_fee_from_costs_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§8.3: market fill price = latest CLOSED bar close as mid, BUY pays UP.

    notional = mid * qty        = 50000.00 * 0.001 = 50.00
    fee      = fee_rate * notional        = 0.0026 * 50.00 = 0.1300
    fill     = mid * (1 + half_spread_rate) = 50000.00 * 1.0010 = 50050.00
    """
    bar = _bar(_T0, open_="50000", high="50500", low="49500", close="50000.00")
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _bars([bar]))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: _T0 + timedelta(days=1))

    _seed_allow_verdict(thesis_id="TH-buy-market")
    broker = PaperBroker(account_ref=_ACCOUNT_REF)
    broker.submit(_order(side="buy"), _VERDICT)

    fills = broker.fills(_T0)
    assert len(fills) == 1
    fill = fills[0]
    assert fill.price == Decimal("50050.00")
    assert fill.fees_usd == Decimal("0.13")
    assert fill.qty == Decimal("0.001")


def test_market_sell_fills_at_mid_minus_half_spread_with_fee_from_costs_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SELL receives DOWN: fill = mid * (1 - half_spread_rate) =
    50000.00 * 0.9990 = 49950.00; fee identical to the buy case (same
    notional basis, symmetric table — tradekit.costs.price_friction's own
    docstring: "the current tables are symmetric")."""
    bar = _bar(_T0, open_="50000", high="50500", low="49500", close="50000.00")
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _bars([bar]))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: _T0 + timedelta(days=1))

    _seed_allow_verdict(thesis_id="TH-sell-market")
    broker = PaperBroker(account_ref=_ACCOUNT_REF)
    broker.submit(_order(side="sell"), _VERDICT)

    fills = broker.fills(_T0)
    assert len(fills) == 1
    fill = fills[0]
    assert fill.price == Decimal("49950.00")
    assert fill.fees_usd == Decimal("0.13")


def test_market_fill_quote_snapshot_matches_the_bar_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """§8.3: "quote snapshot stored ON the Fill — every paper fill
    auditable." Pinned minimum shape: `ts_open` (the deciding bar's open
    timestamp), `close` (the mid the fill priced off), `source` (provider
    name, matching `BarSeries.source`) — extra keys are not forbidden, only
    these three are asserted as the guaranteed floor."""
    bar = _bar(_T0, open_="50000", high="50500", low="49500", close="50000.00")
    monkeypatch.setattr(
        "tradekit.mae._runtime.get_closed_bars", _bars([bar], source="kraken-cache")
    )
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: _T0 + timedelta(days=1))

    _seed_allow_verdict(thesis_id="TH-buy-market")
    broker = PaperBroker(account_ref=_ACCOUNT_REF)
    broker.submit(_order(side="buy"), _VERDICT)

    fill = broker.fills(_T0)[0]
    snapshot = fill.quote_snapshot
    assert snapshot["ts_open"] == bar.ts_open.isoformat()
    assert Decimal(str(snapshot["close"])) == Decimal("50000.00")
    assert snapshot["source"] == "kraken-cache"


# ---------------------------------------------------------------------------
# Token gate — batch B scope: shape/existence only
# ---------------------------------------------------------------------------


def test_submit_raises_broker_token_required_for_a_none_verdict() -> None:
    """Batch-B pin: `None`/absent `verdict` -> `BrokerTokenRequired`, before
    any bar fetch or fill arithmetic (§8.2/§15's "structurally impossible"
    ordering guarantee is only real if the adapter refuses eagerly)."""
    broker = PaperBroker(account_ref=_ACCOUNT_REF)
    with pytest.raises(BrokerTokenRequired):
        broker.submit(_order(side="buy"), None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# No cached bars — typed error, never a guess-fill
# ---------------------------------------------------------------------------


def test_market_submit_with_no_cached_bars_raises_no_quote_available_and_appends_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CTO adjudication (ASSUMPTIONS Round-17 entry 111, pinned): a market
    order on a symbol with ZERO cached closed bars raises
    `NoQuoteAvailable` and appends ZERO events — a broker that invents a
    price is the exact fabrication class ASSUMPTIONS 71 exists to kill."""
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _bars([]))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: _T0)

    # Token verification runs FIRST (CTO adjudication, 2026-07-17) — the
    # verdict must be earned so this test measures the NoQuoteAvailable
    # refusal, not a token refusal. Seeded before the baseline count so the
    # no-op assertion below is unaffected.
    _seed_allow_verdict(thesis_id="TH-buy-market")
    events_before = len(default_ledger().query(EventFilter()))
    broker = PaperBroker(account_ref=_ACCOUNT_REF)
    with pytest.raises(NoQuoteAvailable):
        broker.submit(_order(side="buy"), _VERDICT)

    assert len(default_ledger().query(EventFilter())) == events_before, (
        "a NoQuoteAvailable refusal must be a true no-op on the ledger — no OrderSubmitted, "
        "no OrderAck, no FillRecorded"
    )


# ---------------------------------------------------------------------------
# Limit fills — through-by-tick boundary triple (G5)
#
# Design note (FLAGGED, ASSUMPTIONS round-17): a resting limit order can
# only be evaluated against bars that close AFTER the order was placed, so
# these tests submit at T0 (no fill — nothing has traded through yet) then
# call `order_status(order_id)` at a LATER clock/bar-set as the polling
# trigger that appends `FillRecorded` (mirrors §8.2 step 6: "tk order
# status polling -> FillRecorded"). Inferred, not explicitly pinned by
# §8.3's prose — the dev pass may instead evaluate resting limits inside a
# different internal poll; if so, this suite's `order_status` call sites
# are the contract to preserve, not the mechanism.
# ---------------------------------------------------------------------------

_LIMIT = Decimal("50000.00")
_TICK = Decimal("0.01")  # _ASSET.tick_size


def _submit_resting_buy_limit(monkeypatch: pytest.MonkeyPatch) -> tuple[PaperBroker, str]:
    quiet_bar = _bar(_T0, open_="50200", high="50300", low="50100", close="50200.00")
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _bars([quiet_bar]))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: _T0)

    _seed_allow_verdict(thesis_id="TH-buy-limit")
    broker = PaperBroker(account_ref=_ACCOUNT_REF)
    ack = broker.submit(_order(side="buy", order_type="limit", limit_price=str(_LIMIT)), _VERDICT)
    assert ack.status == "accepted"
    assert broker.order_status(ack.order_id).status == "open", (
        "no bar has traded through the limit yet — must not fill prematurely"
    )
    return broker, ack.order_id


def test_limit_buy_fills_at_the_limit_price_when_a_later_bar_trades_through_by_exactly_one_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G5: buy limit L fills when a LATER bar's low <= L - tick. Through-by-
    exactly-1-tick: low = 49999.99 = 50000.00 - 0.01. Fill price is the
    LIMIT price (50000.00), never the through price (49999.99) — §8.3's
    conservative "assume worst price within the bar" rule for the taker,
    inverted for a resting limit: the counterparty gives no better than the
    order's own limit."""
    broker, order_id = _submit_resting_buy_limit(monkeypatch)

    through_ts = _T0 + timedelta(days=1)
    through_bar = _bar(through_ts, open_="50100", high="50150", low="49999.99", close="50050")
    monkeypatch.setattr(
        "tradekit.mae._runtime.get_closed_bars",
        _bars([_bar(_T0, open_="50200", high="50300", low="50100", close="50200.00"), through_bar]),
    )
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: through_ts + timedelta(hours=1))

    status = broker.order_status(order_id)
    assert status.status == "filled"
    assert status.filled_qty == Decimal("0.001")

    fills = broker.fills(_T0)
    assert len(fills) == 1
    assert fills[0].price == _LIMIT, "limit fills price AT the limit, not the through price"


def test_limit_buy_exact_touch_is_not_a_fill(monkeypatch: pytest.MonkeyPatch) -> None:
    """G5: an EXACT touch (bar.low == L) is explicitly NOT a fill — the
    spread never swept through, per §8.3's retail-limit-rests-unexecuted
    rationale."""
    broker, order_id = _submit_resting_buy_limit(monkeypatch)

    touch_ts = _T0 + timedelta(days=1)
    touch_bar = _bar(touch_ts, open_="50100", high="50150", low=str(_LIMIT), close="50050")
    monkeypatch.setattr(
        "tradekit.mae._runtime.get_closed_bars",
        _bars([_bar(_T0, open_="50200", high="50300", low="50100", close="50200.00"), touch_bar]),
    )
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: touch_ts + timedelta(hours=1))

    status = broker.order_status(order_id)
    assert status.status == "open", "exact touch must never be treated as a fill (G5)"
    assert broker.fills(_T0) == []


def test_limit_buy_never_reached_stays_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bar low stays strictly above the limit forever (in this fixture's
    window) -> the order never fills, no partials, status stays `open`."""
    broker, order_id = _submit_resting_buy_limit(monkeypatch)

    far_ts = _T0 + timedelta(days=1)
    far_bar = _bar(far_ts, open_="50100", high="50150", low="50050.00", close="50075")
    monkeypatch.setattr(
        "tradekit.mae._runtime.get_closed_bars",
        _bars([_bar(_T0, open_="50200", high="50300", low="50100", close="50200.00"), far_bar]),
    )
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: far_ts + timedelta(hours=1))

    status = broker.order_status(order_id)
    assert status.status == "open"
    assert status.filled_qty == Decimal("0")
    assert broker.fills(_T0) == []


# ---------------------------------------------------------------------------
# No partials
# ---------------------------------------------------------------------------


def test_limit_fill_is_never_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    """§8.3: "no partial fills in MVP" — a filled limit order's `FillRecorded`
    carries the FULL order qty in one event, and `order_status` reports
    `filled_qty == qty` / `remaining_qty == 0`, never `"partially_filled"`."""
    broker, order_id = _submit_resting_buy_limit(monkeypatch)

    through_ts = _T0 + timedelta(days=1)
    through_bar = _bar(through_ts, open_="50100", high="50150", low="49999.99", close="50050")
    monkeypatch.setattr(
        "tradekit.mae._runtime.get_closed_bars",
        _bars([_bar(_T0, open_="50200", high="50300", low="50100", close="50200.00"), through_bar]),
    )
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: through_ts + timedelta(hours=1))

    status = broker.order_status(order_id)
    assert status.status == "filled"
    assert status.filled_qty == Decimal("0.001")
    assert status.remaining_qty in (Decimal("0"), None)
    assert len(broker.fills(_T0)) == 1, "exactly one FillRecorded — no partial-fill sequence"


# ---------------------------------------------------------------------------
# Determinism — same cache/bars -> byte-for-byte identical fills (replay)
# ---------------------------------------------------------------------------


def test_market_fill_replay_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    """TD-18 ring 3 / §8.3: running the SAME fill evaluation twice against
    the SAME fixture bars produces identical price/fees — two DISTINCT
    PaperBroker instances (own account_refs, so no cross-account bleed)
    fed the identical order shape and bar fixture must land on the exact
    same Decimal fill price and fee."""
    bar = _bar(_T0, open_="50000", high="50500", low="49500", close="50000.00")
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _bars([bar]))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: _T0 + timedelta(days=1))

    # Both brokers resolve default_ledger() under the same TK_DATA_DIR tmp
    # isolation, so one seeded VerdictIssued serves both submits — each
    # broker's ledger (the shared one) carries the earned allow.
    _seed_allow_verdict("paper:replay-a", thesis_id="TH-buy-market")
    broker_a = PaperBroker(account_ref="paper:replay-a")
    broker_b = PaperBroker(account_ref="paper:replay-b")
    broker_a.submit(_order(side="buy"), _VERDICT)
    broker_b.submit(_order(side="buy"), _VERDICT)

    fill_a = broker_a.fills(_T0)[0]
    fill_b = broker_b.fills(_T0)[0]
    assert fill_a.price == fill_b.price
    assert fill_a.fees_usd == fill_b.fees_usd
    assert fill_a.qty == fill_b.qty


# ---------------------------------------------------------------------------
# Property: market fill price envelope
#
# Derived, not invented: for a BUY, fill = close * (1 + r) where
# low <= close <= high (Bar's own OHLC invariant) and r = half_spread_rate
# >= 0, so fill lies in [low * (1 + r), high * (1 + r)] subset [low, high *
# (1 + r)]. For a SELL, fill = close * (1 - r) in [low * (1 - r), high *
# (1 - r)] subset [low * (1 - r), high]. The only guarantee that holds for
# EITHER side is the union: fill in [low * (1 - r), high * (1 + r)]. This is
# the property pinned below — NOT a claim that limit fills obey it (a
# resting limit's fill price is the limit itself, which may sit anywhere
# relative to the triggering bar's range, per the through-by-tick tests
# above).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("low", "high", "close", "side"),
    [
        ("49000.00", "51000.00", "49500.00", "buy"),
        ("49000.00", "51000.00", "50900.00", "sell"),
        ("100.00", "100.00", "100.00", "buy"),  # degenerate flat bar
    ],
)
def test_market_fill_price_stays_within_the_spread_adjusted_bar_envelope(
    monkeypatch: pytest.MonkeyPatch, low: str, high: str, close: str, side: str
) -> None:
    r = Decimal("0.0010")  # kraken/crypto half_spread_rate, tradekit.costs._TABLE
    bar = _bar(_T0, open_=close, high=high, low=low, close=close)
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _bars([bar]))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: _T0 + timedelta(days=1))

    _seed_allow_verdict(thesis_id=f"TH-{side}-market")
    broker = PaperBroker(account_ref=_ACCOUNT_REF)
    broker.submit(_order(side=side), _VERDICT)

    fill_price = broker.fills(_T0)[0].price
    lower_bound = Decimal(low) * (1 - r)
    upper_bound = Decimal(high) * (1 + r)
    assert lower_bound <= fill_price <= upper_bound


# ---------------------------------------------------------------------------
# MED-1 (P3 review, CTO-pinned fix) — halt bypass via resting-limit fill.
#
# `order_status` is the poll point that appends a resting limit's
# `FillRecorded` (§8.3). Before this fix it did so unconditionally, so a
# limit resting BEFORE a `HaltSet` could still fill AFTER the halt via a
# later `tk order status` poll -- a halt bypass. Fix: `order_status` folds
# `HaltSet`/`HaltCleared` (the SAME derivation `policy._context._halt_state`
# uses, duplicated here without importing `policy` -- see `_paper.py`'s
# `_is_halted` docstring) and refuses to append a fill while halted; the
# order simply stays "open" and a LATER poll, after `HaltCleared`, may fill
# normally (ledger determinism is event-based, so replay reproduces).
# ---------------------------------------------------------------------------


def test_order_status_does_not_fill_a_resting_limit_while_halted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker, order_id = _submit_resting_buy_limit(monkeypatch)

    through_ts = _T0 + timedelta(days=1)
    through_bar = _bar(through_ts, open_="50100", high="50150", low="49999.99", close="50050")
    monkeypatch.setattr(
        "tradekit.mae._runtime.get_closed_bars",
        _bars([_bar(_T0, open_="50200", high="50300", low="50100", close="50200.00"), through_bar]),
    )
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: through_ts + timedelta(hours=1))

    default_ledger().append(
        Event(
            event_id=str(ULID()),
            ts_utc=through_ts,
            type="HaltSet",
            actor="system:test-harness",
            run_id=None,
            schema_ver=1,
            payload=HaltSetPayload(
                reason="test-halt", scope="all", set_by="system:test-harness"
            ).model_dump(mode="json"),
        )
    )

    status = broker.order_status(order_id)
    assert status.status == "open", "a halted account must not fill a resting limit"
    assert broker.fills(_T0) == [], (
        "zero FillRecorded while halted, even though the bar traded through"
    )

    fill_events = [
        e
        for e in default_ledger().query(EventFilter(types=["FillRecorded"]))
        if e.payload.get("order_id") == order_id
    ]
    assert fill_events == []


def test_order_status_fills_a_resting_limit_after_halt_cleared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broker, order_id = _submit_resting_buy_limit(monkeypatch)

    through_ts = _T0 + timedelta(days=1)
    through_bar = _bar(through_ts, open_="50100", high="50150", low="49999.99", close="50050")
    monkeypatch.setattr(
        "tradekit.mae._runtime.get_closed_bars",
        _bars([_bar(_T0, open_="50200", high="50300", low="50100", close="50200.00"), through_bar]),
    )
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: through_ts + timedelta(hours=1))

    halt_ts = through_ts
    default_ledger().append(
        Event(
            event_id=str(ULID()),
            ts_utc=halt_ts,
            type="HaltSet",
            actor="system:test-harness",
            run_id=None,
            schema_ver=1,
            payload=HaltSetPayload(
                reason="test-halt", scope="all", set_by="system:test-harness"
            ).model_dump(mode="json"),
        )
    )
    assert broker.order_status(order_id).status == "open"
    assert broker.fills(_T0) == []

    clear_ts = through_ts + timedelta(minutes=30)
    default_ledger().append(
        Event(
            event_id=str(ULID()),
            ts_utc=clear_ts,
            type="HaltCleared",
            actor="system:test-harness",
            run_id=None,
            schema_ver=1,
            payload=HaltClearedPayload(
                reason="test-clear", halt_event_id=None, cleared_by="system:test-harness"
            ).model_dump(mode="json"),
        )
    )

    status = broker.order_status(order_id)
    assert status.status == "filled", "after HaltCleared, a later poll must fill normally"
    assert broker.fills(_T0)[0].price == _LIMIT


# ---------------------------------------------------------------------------
# MED-2 (P3 review, CTO-pinned fix) — token gate narrower than the written
# pin. §8.2/§15 pins "existence + thesis match + no newer deny"; batch B/C's
# `_verify_token` only checked existence + allow + hash. This section pins
# the two missing checks: (a) thesis binding — the presented VerdictToken's
# `VerdictIssued` event must reference the SAME thesis_id as the order being
# submitted; (b) no-newer-deny — a LATER `VerdictIssued` for the same
# thesis_id with `allow=False` invalidates an earlier allow, even though the
# earlier allow event itself is untouched.
# ---------------------------------------------------------------------------


def test_submit_refuses_a_token_minted_for_a_different_thesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bar = _bar(_T0, open_="50000", high="50500", low="49500", close="50000.00")
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _bars([bar]))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: _T0 + timedelta(days=1))

    _seed_allow_verdict(thesis_id="TH-A", verdict_id="v-thesis-a")
    order_for_thesis_b = OrderRequest(
        thesis_id="TH-B",
        account_ref=_ACCOUNT_REF,
        asset=_ASSET,
        side="buy",
        order_type="market",
        qty=Decimal("0.001"),
    )
    token = VerdictToken(verdict_id="v-thesis-a", policy_version_hash=_VERDICT.policy_version_hash)

    broker = PaperBroker(account_ref=_ACCOUNT_REF)
    with pytest.raises(BrokerTokenRequired):
        broker.submit(order_for_thesis_b, token)


def test_submit_refuses_an_allow_token_superseded_by_a_later_deny_for_the_same_thesis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bar = _bar(_T0, open_="50000", high="50500", low="49500", close="50000.00")
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _bars([bar]))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: _T0 + timedelta(days=1))

    _seed_allow_verdict(thesis_id="TH-X", verdict_id="v-allow-1", ts_utc=_T0)
    default_ledger().append(
        Event(
            event_id=str(ULID()),
            ts_utc=_T0 + timedelta(hours=1),
            type="VerdictIssued",
            actor="system:test-harness",
            run_id=None,
            schema_ver=1,
            payload=VerdictIssuedPayload(
                verdict_id="v-deny-1",
                kind="submit_order",
                account_ref=_ACCOUNT_REF,
                thesis_id="TH-X",
                allow=False,
                policy_version_hash=_VERDICT.policy_version_hash,
            ).model_dump(mode="json"),
        )
    )
    order = OrderRequest(
        thesis_id="TH-X",
        account_ref=_ACCOUNT_REF,
        asset=_ASSET,
        side="buy",
        order_type="market",
        qty=Decimal("0.001"),
    )
    token = VerdictToken(verdict_id="v-allow-1", policy_version_hash=_VERDICT.policy_version_hash)

    broker = PaperBroker(account_ref=_ACCOUNT_REF)
    with pytest.raises(BrokerTokenRequired):
        broker.submit(order, token)


def test_submit_accepts_an_allow_token_when_a_later_verdict_is_also_an_allow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later `VerdictIssued(allow=True)` for the same thesis does NOT
    invalidate an earlier allow — only a later DENY does."""
    bar = _bar(_T0, open_="50000", high="50500", low="49500", close="50000.00")
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _bars([bar]))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: _T0 + timedelta(days=1))

    _seed_allow_verdict(thesis_id="TH-Y", verdict_id="v-allow-1", ts_utc=_T0)
    _seed_allow_verdict(thesis_id="TH-Y", verdict_id="v-allow-2", ts_utc=_T0 + timedelta(hours=1))
    order = OrderRequest(
        thesis_id="TH-Y",
        account_ref=_ACCOUNT_REF,
        asset=_ASSET,
        side="buy",
        order_type="market",
        qty=Decimal("0.001"),
    )
    token = VerdictToken(verdict_id="v-allow-1", policy_version_hash=_VERDICT.policy_version_hash)

    broker = PaperBroker(account_ref=_ACCOUNT_REF)
    broker.submit(order, token)

    fills = broker.fills(_T0)
    assert len(fills) == 1, "the earlier allow token is still valid — no newer DENY exists"


# ---------------------------------------------------------------------------
# In-kind crypto fee physics (SPEC-inkind-fees, AC-2..5) — venue=alpaca,
# asset_class=crypto ONLY (kraken/equity keep the OLD USD-fee model, out of
# scope). `FillRecordedPayload.fee_asset_qty` does not exist on the model
# yet, so every assertion below that reads it off the raw ledger payload
# (subscript, not `.get(..., default)`) fails with a KeyError until the
# dev pass adds the field — the RIGHT reason for red here.
# ---------------------------------------------------------------------------


def _last_fill_payload(account_ref: str) -> dict:
    """This account's most-recently-appended `FillRecorded` payload, as the
    RAW ledger dict (not the `contracts.Fill` projection, which never
    carries `fee_asset_qty` — only `FillRecordedPayload`, the producer-side
    contract, does per the SPEC's interface pins)."""
    events = [
        e
        for e in default_ledger().query(EventFilter(types=["FillRecorded"]))
        if e.payload.get("account_ref") == account_ref
    ]
    assert events, f"no FillRecorded event for account_ref={account_ref!r}"
    return events[-1].payload


def test_market_buy_alpaca_crypto_withholds_fee_in_kind_and_cash_delta_is_exact_notional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-2 (SPEC-inkind-fees), market path: mid=1883.57 (2026-07-26
    live-receipt mid), qty=0.002602483 (same live-receipt buy).
        half_spread_rate (alpaca/crypto, costs._TABLE) = 0.0010
        fill_price = mid * 1.0010 = 1885.45357
        fee_asset_qty = ceil9(0.0025 * 0.002602483) = 0.000006507
        fees_usd = fee_asset_qty * fill_price   (USD valuation only)
    Cash delta must be EXACTLY -(qty * fill_price) — no separate fee
    deduction; the withhold is embodied in the RECEIVED qty, not cash."""
    mid = Decimal("1883.57")
    qty = Decimal("0.002602483")
    bar = _bar(_T0, open_="1883.57", high="1900.00", low="1870.00", close=str(mid))
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _bars([bar]))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: _T0 + timedelta(days=1))

    _seed_allow_verdict(thesis_id="TH-buy-alpaca-market")
    order = OrderRequest(
        thesis_id="TH-buy-alpaca-market",
        account_ref=_ACCOUNT_REF,
        asset=_ALPACA_CRYPTO,
        side="buy",
        order_type="market",
        qty=qty,
    )
    broker = PaperBroker(account_ref=_ACCOUNT_REF)
    broker.submit(order, _VERDICT)

    expected_fee_asset_qty = (Decimal("0.0025") * qty).quantize(
        Decimal("1e-9"), rounding=ROUND_CEILING
    )
    assert expected_fee_asset_qty == Decimal("0.000006507"), (
        "sanity check on the hand-derived rounding-up (spec's own measured example)"
    )
    expected_fill_price = mid * (Decimal("1") + Decimal("0.0010"))
    expected_fees_usd = expected_fee_asset_qty * expected_fill_price

    payload = _last_fill_payload(_ACCOUNT_REF)
    assert Decimal(str(payload["fee_asset_qty"])) == expected_fee_asset_qty
    assert Decimal(str(payload["fees_usd"])) == expected_fees_usd

    account = PaperBroker(account_ref=_ACCOUNT_REF).account()
    assert account.settled_cash_usd == -(qty * expected_fill_price), (
        "AC-2: cash delta is EXACTLY -(qty * fill_price) — no principal seeded, so the "
        "account's whole settled cash IS the delta"
    )


def test_limit_buy_alpaca_crypto_withholds_fee_in_kind_and_cash_delta_is_exact_notional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-2 (SPEC-inkind-fees), limit path (`_record_limit_fill`) — same
    physics as the market path, fill price is the LIMIT price itself.
        limit=2000.00, qty=0.001
        fee_asset_qty = ceil9(0.0025 * 0.001) = 0.0000025 (exact, no
            rounding-up needed at this qty — the market-path test above
            covers the non-exact-boundary rounding case)
        fees_usd = fee_asset_qty * limit_price = 0.0000025 * 2000.00 = 0.005
    """
    limit_price = Decimal("2000.00")
    qty = Decimal("0.001")
    quiet_bar = _bar(_T0, open_="2010", high="2020", low="2005", close="2010.00")
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _bars([quiet_bar]))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: _T0)

    _seed_allow_verdict(thesis_id="TH-buy-alpaca-limit")
    order = OrderRequest(
        thesis_id="TH-buy-alpaca-limit",
        account_ref=_ACCOUNT_REF,
        asset=_ALPACA_CRYPTO,
        side="buy",
        order_type="limit",
        qty=qty,
        limit_price=limit_price,
    )
    broker = PaperBroker(account_ref=_ACCOUNT_REF)
    ack = broker.submit(order, _VERDICT)
    assert broker.order_status(ack.order_id).status == "open"

    through_ts = _T0 + timedelta(days=1)
    through_bar = _bar(through_ts, open_="2005", high="2010", low="1999.99", close="2001")
    monkeypatch.setattr(
        "tradekit.mae._runtime.get_closed_bars",
        _bars([quiet_bar, through_bar]),
    )
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: through_ts + timedelta(hours=1))
    status = broker.order_status(ack.order_id)
    assert status.status == "filled"

    expected_fee_asset_qty = (Decimal("0.0025") * qty).quantize(
        Decimal("1e-9"), rounding=ROUND_CEILING
    )
    assert expected_fee_asset_qty == Decimal("0.0000025")
    expected_fees_usd = expected_fee_asset_qty * limit_price
    assert expected_fees_usd == Decimal("0.000005"), "0.0000025 * 2000.00 = 0.005"

    payload = _last_fill_payload(_ACCOUNT_REF)
    assert Decimal(str(payload["fee_asset_qty"])) == expected_fee_asset_qty
    assert Decimal(str(payload["fees_usd"])) == expected_fees_usd

    account = PaperBroker(account_ref=_ACCOUNT_REF).account()
    assert account.settled_cash_usd == -(qty * limit_price), (
        "AC-2: cash delta is EXACTLY -(qty * limit_price), no separate fee deduction"
    )


def test_market_sell_alpaca_crypto_fee_asset_qty_is_zero_and_sell_physics_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-3 (SPEC-inkind-fees): a SELL never withholds in-kind (the fee
    comes out of USD proceeds, exactly like before) — `fee_asset_qty == 0`
    and `fees_usd`/cash delta follow the UNCHANGED `price_friction` sell
    physics (the same formula this file's kraken sell test already pins)."""
    mid = Decimal("1882.03")
    qty = Decimal("0.002595976")
    bar = _bar(_T0, open_="1882.03", high="1900.00", low="1870.00", close=str(mid))
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _bars([bar]))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: _T0 + timedelta(days=1))

    _seed_allow_verdict(thesis_id="TH-sell-alpaca-market")
    order = OrderRequest(
        thesis_id="TH-sell-alpaca-market",
        account_ref=_ACCOUNT_REF,
        asset=_ALPACA_CRYPTO,
        side="sell",
        order_type="market",
        qty=qty,
    )
    broker = PaperBroker(account_ref=_ACCOUNT_REF)
    broker.submit(order, _VERDICT)

    fill_price = mid * (Decimal("1") - Decimal("0.0010"))
    notional_usd = mid * qty  # friction prices off the PRE-adjustment mid (module docstring)
    expected_fees_usd = Decimal("0.0025") * notional_usd

    payload = _last_fill_payload(_ACCOUNT_REF)
    assert Decimal(str(payload["fee_asset_qty"])) == Decimal("0"), (
        "AC-3: sells never withhold in-kind"
    )
    assert Decimal(str(payload["fees_usd"])) == expected_fees_usd

    account = PaperBroker(account_ref=_ACCOUNT_REF).account()
    assert account.settled_cash_usd == (qty * fill_price) - expected_fees_usd, (
        "AC-3: cash delta == +(qty * fill_price) - fees_usd, unchanged sell physics"
    )


def test_market_buy_alpaca_equity_fee_asset_qty_is_zero_byte_identical_to_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-4 (SPEC-inkind-fees): the in-kind withhold arithmetic is scoped to
    (venue="alpaca", asset_class="crypto") only — an alpaca EQUITY buy gets
    `fee_asset_qty == 0` (fee_rate("alpaca","equity") == 0 anyway) and
    behavior identical to today's zero-commission equity physics."""
    mid = Decimal("190.00")
    qty = Decimal("1")
    bar = _bar(_T0, open_="190.00", high="192.00", low="188.00", close=str(mid))
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _bars([bar]))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: _T0 + timedelta(days=1))

    _seed_allow_verdict(thesis_id="TH-buy-alpaca-equity")
    order = OrderRequest(
        thesis_id="TH-buy-alpaca-equity",
        account_ref=_ACCOUNT_REF,
        asset=_ALPACA_EQUITY,
        side="buy",
        order_type="market",
        qty=qty,
    )
    broker = PaperBroker(account_ref=_ACCOUNT_REF)
    broker.submit(order, _VERDICT)

    payload = _last_fill_payload(_ACCOUNT_REF)
    assert Decimal(str(payload["fee_asset_qty"])) == Decimal("0")
    assert Decimal(str(payload["fees_usd"])) == Decimal("0"), "zero-commission equities"

    fill_price = mid * (Decimal("1") + Decimal("0.0001"))  # alpaca/equity half_spread_rate
    account = PaperBroker(account_ref=_ACCOUNT_REF).account()
    assert account.settled_cash_usd == -(qty * fill_price)


def test_positions_after_alpaca_crypto_buy_reflects_the_net_in_kind_held_qty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-5 (SPEC-inkind-fees): `PaperBroker.positions()` qty derivation is
    `sum(buy.qty - buy.fee_asset_qty) - sum(sell.qty)` — the position must
    show the NET held amount (Q - W), not the gross filled qty Q, matching
    the live-receipt held amount 0.002595976 (dev-log 07-26b)."""
    mid = Decimal("1883.57")
    qty = Decimal("0.002602483")
    bar = _bar(_T0, open_="1883.57", high="1900.00", low="1870.00", close=str(mid))
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _bars([bar]))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: _T0 + timedelta(days=1))

    _seed_allow_verdict(thesis_id="TH-buy-alpaca-positions")
    order = OrderRequest(
        thesis_id="TH-buy-alpaca-positions",
        account_ref=_ACCOUNT_REF,
        asset=_ALPACA_CRYPTO,
        side="buy",
        order_type="market",
        qty=qty,
    )
    broker = PaperBroker(account_ref=_ACCOUNT_REF)
    broker.submit(order, _VERDICT)

    expected_fee_asset_qty = (Decimal("0.0025") * qty).quantize(
        Decimal("1e-9"), rounding=ROUND_CEILING
    )
    expected_held_qty = qty - expected_fee_asset_qty
    assert expected_held_qty == Decimal("0.002595976"), (
        "matches the 2026-07-26 live receipt's held ETH amount"
    )

    positions = broker.positions()
    assert len(positions) == 1
    assert positions[0].qty == expected_held_qty


def test_positions_flat_after_selling_exactly_the_net_in_kind_held_qty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-5 round trip: selling EXACTLY the net held qty (Q - W, never the
    original filled qty Q — a full-qty sell would be rejected/leave dust
    per the live smoke run, spec's out-of-scope note) leaves the account
    flat, same zero-qty-row-omitted representation as today."""
    buy_mid = Decimal("1883.57")
    buy_qty = Decimal("0.002602483")
    buy_bar = _bar(_T0, open_="1883.57", high="1900.00", low="1870.00", close=str(buy_mid))
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _bars([buy_bar]))
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: _T0 + timedelta(days=1))

    _seed_allow_verdict(thesis_id="TH-roundtrip-alpaca")
    broker = PaperBroker(account_ref=_ACCOUNT_REF)
    broker.submit(
        OrderRequest(
            thesis_id="TH-roundtrip-alpaca",
            account_ref=_ACCOUNT_REF,
            asset=_ALPACA_CRYPTO,
            side="buy",
            order_type="market",
            qty=buy_qty,
        ),
        _VERDICT,
    )

    expected_fee_asset_qty = (Decimal("0.0025") * buy_qty).quantize(
        Decimal("1e-9"), rounding=ROUND_CEILING
    )
    held_qty = buy_qty - expected_fee_asset_qty

    sell_ts = _T0 + timedelta(days=2)
    sell_bar = _bar(sell_ts, open_="1882.03", high="1890.00", low="1875.00", close="1882.03")
    monkeypatch.setattr(
        "tradekit.mae._runtime.get_closed_bars", _bars([buy_bar, sell_bar])
    )
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: sell_ts + timedelta(hours=1))
    broker.submit(
        OrderRequest(
            thesis_id="TH-roundtrip-alpaca",
            account_ref=_ACCOUNT_REF,
            asset=_ALPACA_CRYPTO,
            side="sell",
            order_type="market",
            qty=held_qty,
        ),
        _VERDICT,
    )

    assert broker.positions() == [], (
        "AC-5: selling exactly the net post-fee held qty must leave the account flat"
    )
