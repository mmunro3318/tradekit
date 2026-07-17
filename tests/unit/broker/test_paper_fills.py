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
from decimal import Decimal

import pytest

from tradekit.broker._paper import PaperBroker
from tradekit.broker._port import BrokerTokenRequired, NoQuoteAvailable
from tradekit.contracts import AssetRef, Bar, BarSeries, EventFilter, OrderRequest, VerdictToken
from tradekit.ledger import default_ledger

_ASSET = AssetRef(symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))
_ACCOUNT_REF = "paper:fills-test"
_VERDICT = VerdictToken(verdict_id="v-1", policy_version_hash="0" * 64)
_T0 = datetime(2026, 1, 2, tzinfo=UTC)


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

    broker = PaperBroker(account_ref=_ACCOUNT_REF)
    broker.submit(_order(side=side), _VERDICT)

    fill_price = broker.fills(_T0)[0].price
    lower_bound = Decimal(low) * (1 - r)
    upper_bound = Decimal(high) * (1 + r)
    assert lower_bound <= fill_price <= upper_bound
