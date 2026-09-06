"""RED (SPRINT-PREVIEW-DEFER batch A): `hud._build.build_state`'s scan-time
policy preview against the REAL `policy.evaluate` (`evaluate_policy` seam
left at its DEFAULT in every test here — that is the entire point, per the
sprint doc's own "no tradekit-internal mocks" fence). `_default_evaluate_policy`
currently treats EVERY `fail` `RuleHit` as a deny, so an interim
(not-yet-ledgered) `thesis_id` always trips R-010/R-012's
`insufficient_context` fails and the funnel can never ticket anything —
the defect this batch's GREEN pass fixes in `hud._build.py` only.

Seams used (sanctioned, ASSUMPTIONS 157a/158/159 + this sprint's own pin):
`mae._runtime.get_closed_bars`/`mae._runtime.clock`, and three of the four
hud seams (`scan_setup`, `sizing_info`, `open_position_symbols`) —
`evaluate_policy` is NEVER patched in this file. `tradekit.policy`,
`tradekit.ledger`, and `tradekit.broker` are driven only via their real
public verbs (`broker.create_paper_account`, `policy.halt`, `policy.evaluate`
transitively) — no monkeypatch under any of those three modules.

`TK_DATA_DIR` isolation is the autouse `tests/conftest.py::
_tk_data_dir_isolation` fixture — no manual `monkeypatch.setenv` needed here.
`PolicyDials.load()` is left at its real file/code defaults throughout
(`default_account_ref="paper:alpha"`, `paper_starting_equity_usd=500`,
`max_position_pct_paper=0.10`) — the account created below matches that
default ref exactly, and R-005's paper cap reads `dials.paper_
starting_equity_usd` (`policy._context.assemble`), NOT `build_state`'s own
`equity_usd` argument, so no dial override is needed for T-A3's $50 cap
either.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradekit import broker, policy
from tradekit.contracts import (
    AccountConfig,
    AssetRef,
    Bar,
    BarSeries,
    EventFilter,
    OrderRequest,
    ProposedAction,
)
from tradekit.hud import build_state
from tradekit.ledger import default_ledger

_SYMBOL = "ETH/USD"
_THESIS_ID = "interim-thesis-eth-usd"  # build_state's own f"interim-thesis-{sym}" convention
_CAPTURED_AT = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
_PRICE = Decimal("100")
_MIN_BARS = 20  # hud._build._MIN_BARS


@dataclass(frozen=True)
class _FakeSetup:
    """Duck-typed `scan_setup` return (ASSUMPTIONS 157a/T5 addendum) — a
    trivially-passing setup so the funnel reaches the sizing/policy gates;
    `attrition_stages`/`strategy_key` default via `getattr(..., None) or []`
    in `build_state`, same convention `test_build_state.py::_PassingSetup`
    relies on."""

    signal_tags: list[str] = field(default_factory=lambda: ["fake_signal"])


@dataclass(frozen=True)
class _FakeSizing:
    """Duck-typed `sizing_info` return (ASSUMPTIONS 159a) — qty/stop/r-mult
    only, no real `mae.size_position` call."""

    qty: Decimal
    stop_distance_usd: Decimal
    r_multiple_target: Decimal


def _bars(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
    """`mae._runtime.get_closed_bars` seam: >= `_MIN_BARS` flat bars whose
    last close is `_PRICE` — build_state's `limit_price = bars.bars[-1].close`
    (line ~503), so this is the SAME price `_FakeSizing`'s notional below is
    computed against (the sprint doc's own bars/sizing-consistency trap)."""
    bars = [
        Bar(
            ts_open=_CAPTURED_AT - timedelta(hours=_MIN_BARS - i),
            open=_PRICE,
            high=_PRICE + Decimal("5"),
            low=_PRICE - Decimal("5"),
            close=_PRICE,
            volume=Decimal("1000"),
        )
        for i in range(_MIN_BARS)
    ]
    asset = AssetRef(
        symbol=symbol, venue="kraken", asset_class="crypto", tick_size=Decimal("0.01")
    )
    return BarSeries(
        asset=asset,
        timeframe=timeframe,
        bars=bars,
        source="fake-kraken",
    )


def _install_funnel_seams(
    monkeypatch: pytest.MonkeyPatch, *, qty: Decimal = Decimal("0.25")
) -> None:
    """Installs the three sanctioned hud seams + the mae bars/clock seams.
    `evaluate_policy` is deliberately left untouched (real `policy.evaluate`)
    — the whole point of this batch's tests. `qty=0.25` @ price 100 ->
    notional $25, inside every cap (T-A1/T-A2's "healthy" sizing); T-A3
    overrides `qty` to breach R-005's $50 paper cap on purpose."""
    import tradekit.hud._build as hud_build
    import tradekit.mae._runtime as mae_runtime

    monkeypatch.setattr(mae_runtime, "get_closed_bars", _bars)
    monkeypatch.setattr(mae_runtime, "clock", lambda: _CAPTURED_AT)
    monkeypatch.setattr(hud_build, "scan_setup", lambda symbol: _FakeSetup())
    monkeypatch.setattr(
        hud_build,
        "sizing_info",
        lambda symbol, limit_price, equity_usd: _FakeSizing(
            qty=qty, stop_distance_usd=Decimal("10"), r_multiple_target=Decimal("2")
        ),
    )
    monkeypatch.setattr(hud_build, "open_position_symbols", lambda: set())


def _create_default_paper_account() -> None:
    """Matches `PolicyDials.load().default_account_ref` ("paper:alpha",
    real code default — never overridden in this file) so
    `_make_proposal`'s `account_ref` resolves to an account that genuinely
    exists (R-002's tier-by-construction and R-003's balance check both
    read this)."""
    broker.create_paper_account(
        AccountConfig(
            account_ref="paper:alpha", principal_usd=Decimal("500.00"), max_trades_per_day=0
        )
    )


def _policy_verdict_gate(state, symbol: str = _SYMBOL):
    entry = next(e for e in state.report if e.symbol == symbol)
    return next(g for g in entry.gates if g.name == "policy_verdict")


def _verdict_issued_events_for_thesis(thesis_id: str) -> list:
    events = default_ledger().query(EventFilter(types=["VerdictIssued"]))
    return [e for e in events if e.payload.get("thesis_id") == thesis_id]


class TestTA1PreviewDeferralUnblocksTheDefect:
    def test_insufficient_context_r010_r012_deferred_at_preview_yields_one_allowed_ticket(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR (T-A1, the defect — SPRINT-PREVIEW-DEFER A2/A3/A4):
        real `policy.evaluate` denies solely on R-010/R-012
        `insufficient_context` (unledgered interim thesis) — today
        `_default_evaluate_policy` treats that as a hard deny (FAILS: zero
        tickets). After the GREEN fix defers exactly those two hits, the
        preview allows: one ticket, `policy_verdict` gate `passed=True`,
        rationale carrying the deferral audit substrings, and a `verdict_id`
        that is a REAL ledgered `VerdictIssued` event id (never fabricated,
        never None) for this thesis_id."""
        _create_default_paper_account()
        _install_funnel_seams(monkeypatch, qty=Decimal("0.25"))

        state = build_state([_SYMBOL], captured_at=_CAPTURED_AT, equity_usd=Decimal("500"))

        assert len(state.tickets) == 1, "T-A1: preview deferral must yield exactly one ticket"
        ticket = state.tickets[0]
        assert ticket.pair == _SYMBOL

        gate = _policy_verdict_gate(state)
        assert gate.passed is True, "T-A1: policy_verdict gate must pass once R-010/R-012 defer"
        assert "deferred at preview" in gate.rationale
        assert "R-010" in gate.rationale
        assert "R-012" in gate.rationale

        verdict_events = _verdict_issued_events_for_thesis(_THESIS_ID)
        assert verdict_events, "T-A1: a real VerdictIssued event must be ledgered for this thesis"
        most_recent = max(verdict_events, key=lambda e: e.ts_utc)
        assert ticket.verdict_id == most_recent.payload["verdict_id"]
        assert ticket.verdict_id, "T-A1: verdict_id must be a non-empty string, never fabricated"


class TestTA2DeferralIsNotABypass:
    def test_real_halt_still_denies_with_r001_even_with_deferrable_hits_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR (T-A2): a real `policy.halt(...)` (R-001, non-deferrable)
        must still deny at preview even though R-010/R-012 are ALSO failing
        with `insufficient_context` in the same verdict — deferral is
        strictly scoped to those two rule ids, never a general bypass.
        Pins CURRENT behavior too (today's undeferred `_default_evaluate_
        policy` already denies on ANY failing hit, R-001 included) — this
        test is expected to PASS both before and after the GREEN fix."""
        _create_default_paper_account()
        policy.halt("red test halt")
        _install_funnel_seams(monkeypatch, qty=Decimal("0.25"))

        state = build_state([_SYMBOL], captured_at=_CAPTURED_AT, equity_usd=Decimal("500"))

        assert len(state.tickets) == 0, "T-A2: a halt must still deny — deferral is not a bypass"
        gate = _policy_verdict_gate(state)
        assert gate.passed is False
        assert "R-001" in gate.rationale


class TestTA3NonDeferrableDenyStillNamesTheDeferredHits:
    def test_real_r005_breach_denies_and_rationale_still_names_r010_alongside_r005(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR (T-A3 / A6 audit-completeness): a genuine R-005 breach
        (notional $100 > 10%-of-$500 = $50 paper cap) is a real, non-
        insufficient-context fail — it must deny regardless of any deferral
        logic, AND (A6) the rationale must still name the deferred R-010 hit
        so the audit trail stays complete, never silently dropped once a
        non-deferrable rule also failed. Pins CURRENT behavior too (today's
        undeferred path already lists every failing hit) — expected to PASS
        both before and after the GREEN fix."""
        _create_default_paper_account()
        _install_funnel_seams(monkeypatch, qty=Decimal("1"))  # 1 * $100 = $100 notional > $50 cap

        state = build_state([_SYMBOL], captured_at=_CAPTURED_AT, equity_usd=Decimal("500"))

        assert len(state.tickets) == 0, "T-A3: a real R-005 breach must deny"
        gate = _policy_verdict_gate(state)
        assert gate.passed is False
        assert "R-005" in gate.rationale
        assert "R-010" in gate.rationale, "A6: the deferred hit must still be named alongside R-005"


class TestTA4DefaultEvaluatePolicyDefersAtTheFunctionBoundary:
    def test_deny_with_only_r010_r012_insufficient_context_returns_allowed_true(self) -> None:
        """CONTRACT (T-A4, T-A1 at the function boundary): a real
        `policy.evaluate` verdict whose only failing hits are R-010/R-012
        `insufficient_context` must make `_default_evaluate_policy` itself
        return `allowed=True` — no funnel, no bars, no monkeypatch at all;
        only a real ledger + a hand-built `ProposedAction`."""
        import tradekit.hud._build as hud_build

        _create_default_paper_account()
        asset = AssetRef(
            symbol=_SYMBOL, venue="kraken", asset_class="crypto", tick_size=Decimal("0.01")
        )
        order = OrderRequest(
            thesis_id=_THESIS_ID,
            account_ref="paper:alpha",
            asset=asset,
            side="buy",
            order_type="limit",
            qty=Decimal("0.25"),
            limit_price=_PRICE,
        )
        proposal = ProposedAction(
            kind="submit_order",
            account_ref="paper:alpha",
            requested_by="hud",
            thesis_id=_THESIS_ID,
            order=order,
        )

        decision = hud_build._default_evaluate_policy(proposal)

        assert decision.allowed is True
