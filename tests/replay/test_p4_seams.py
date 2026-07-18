"""Ring-3 seam scenarios (DESIGN §16 ring 3; SPRINT P4-PAPER batch B,
addendum 2, "P4-paper batch B: seam hardening (review-round-6 process
note)"). Each scenario drives REAL verbs end-to-end through the pipeline —
never a canned Verdict, never a hand-built ledger row standing in for what
a real verb would have produced — and asserts on the resulting ledger.

Three scenarios:

  (a) submit-time halt END-TO-END THROUGH THE PIPELINE: an earned thesis
      whose `policy.evaluate` allows, then a `HaltSet` lands (harness,
      simulating a concurrent process — e.g. another agent's `tk policy
      halt` or an in-flight `reconcile` racing this one) strictly BETWEEN
      the allow verdict and the adapter's `submit()` call; the SHARED
      verifier's halt check (`broker._tokens.verify_token`, already real
      since SPRINT P4-PAPER batch A) refuses at `submit()` — zero
      `Order*`/`FillRecorded` events survive the halt. NOTE (honest
      accounting): the production code this scenario exercises
      (`broker._tokens.is_halted`) already landed in batch A — this test is
      NEW-GREEN, not a new red-to-green implementation change, and is
      counted that way in the batch report.

  (b) advisory reconcile x phantom fill -> auto-halt -> everything denies:
      an `"advisory:*"` account (mirroring `ManualBroker`'s real shapes,
      per `broker._manual.py`'s own docstring) whose broker-side record
      reports a fill the ledger never saw (the exact out-of-band-fill shape
      `broker._pipeline.reconcile`'s forward-mismatch branch is built to
      catch) triggers the SAME automatic `HaltSet` path a paper/live
      mismatch does — `policy.evaluate` then denies for EVERY account
      (`scope="all"`), not just the advisory one.

  (c) token x demotion window: a confirmed-T2 `"live:"` account is
      `Demoted` (harness event, mirroring `policy.promotion_status`'s own
      machine-evaluated demotion path) BEFORE `execute_order` runs —
      `execute_order` re-evaluates policy FRESH at call time (it never
      caches a verdict across calls), so the now-stale T2 assumption is
      re-checked and R-002 denies; zero `Order*` events.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradekit import broker, policy, thesis
from tradekit.broker._pipeline import PipelineDenied
from tradekit.broker._port import BrokerTokenRequired
from tradekit.contracts import (
    AssetRef,
    Bar,
    BarSeries,
    Event,
    EventFilter,
    Fill,
    HaltSetPayload,
    ProposedAction,
)
from tradekit.ledger import default_ledger

_ASSET = AssetRef(symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))
_SUBMIT_BAR_START = datetime(2026, 1, 1, tzinfo=UTC)
_N_SUBMIT_BARS = 20


def _flat_atr10_price100_bars(n: int = _N_SUBMIT_BARS) -> BarSeries:
    """Same proven-safe fixture as `tests/unit/broker/test_pipeline.py`
    (flat ATR(14)=10 @ price 100 -> a $25 recommended size, inside every
    money-path rule's cap) — reused verbatim rather than hand-derived
    (FIXTURE-FREEZE)."""
    bars = [
        Bar(
            ts_open=_SUBMIT_BAR_START + timedelta(days=i),
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("95"),
            close=Decimal("100"),
            volume=Decimal("1000"),
        )
        for i in range(n)
    ]
    return BarSeries(asset=_ASSET, timeframe="1d", bars=bars, source="fake-kraken")


def _fake_submit_get_closed_bars(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
    return _flat_atr10_price100_bars()


def _fake_submit_clock() -> datetime:
    return _SUBMIT_BAR_START + timedelta(days=_N_SUBMIT_BARS + 5)  # 2026-01-25


def _market_entry_kwargs(thesis_kwargs: dict, **overrides: object) -> dict:
    kw = dict(thesis_kwargs)
    kw["entry"] = {"order_type": "market", "valid_until": "2026-02-01T00:00:00Z"}
    kw.update(overrides)
    return kw


def _build_approved_thesis(
    thesis_kwargs, monkeypatch: pytest.MonkeyPatch, make_event, **kwargs_overrides: object
) -> str:
    """Reach `approved` via the REAL draft/submit/approve verbs — mirrors
    `tests/unit/broker/test_pipeline.py::_build_approved_thesis` verbatim
    (same harness pattern, reused rather than re-derived)."""
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_submit_get_closed_bars)
    monkeypatch.setattr("tradekit.mae._runtime._clock", _fake_submit_clock)
    kw = _market_entry_kwargs(thesis_kwargs, **kwargs_overrides)
    thesis_id = thesis.draft(kw)
    thesis.submit(thesis_id)
    default_ledger().append(
        make_event(
            type="ReviewCompleted",
            payload={"thesis_id": thesis_id, "review_artifact_id": "rev-1", "passed": True},
        )
    )
    thesis.approve(thesis_id)
    return thesis_id


def _events_of_type(thesis_id: str, event_type: str) -> list[Event]:
    return [
        e
        for e in default_ledger().query(EventFilter(types=[event_type]))
        if e.payload.get("thesis_id") == thesis_id
    ]


def _zero_money_path_events(thesis_id: str) -> None:
    for event_type in ("OrderSubmitted", "OrderAck", "FillRecorded", "ThesisActivated"):
        assert _events_of_type(thesis_id, event_type) == [], (
            f"expected zero {event_type} events for thesis_id={thesis_id!r} on a denied/"
            "refused path — the money path is structurally unreachable past the refusal point"
        )


# ---------------------------------------------------------------------------
# (a) submit-time halt end-to-end through the pipeline
# ---------------------------------------------------------------------------


def test_submit_time_halt_end_to_end_refuses_at_the_shared_verifier(
    thesis_kwargs, monkeypatch: pytest.MonkeyPatch, make_event
) -> None:
    thesis_id = _build_approved_thesis(thesis_kwargs, monkeypatch, make_event)

    real_evaluate = policy.evaluate

    def _evaluate_then_concurrent_halt(action: ProposedAction):
        # policy.evaluate() itself runs for real (a genuine allow verdict —
        # this is NOT a canned Verdict), THEN — simulating a concurrent
        # process (another agent's `tk policy halt`, or an in-flight
        # reconcile racing this call) — a HaltSet lands strictly between
        # the allow verdict and the adapter's submit() call below.
        verdict = real_evaluate(action)
        if verdict.allow:
            default_ledger().append(
                make_event(
                    type="HaltSet",
                    payload=HaltSetPayload(
                        reason="concurrent halt landing between verdict and submit",
                        scope="all",
                        set_by="system:test-harness-concurrent-process",
                    ).model_dump(mode="json"),
                )
            )
        return verdict

    # Module-attribute monkeypatch — `_pipeline.execute_order` resolves
    # `policy.evaluate` through `from tradekit import policy` at call time,
    # so patching `tradekit.policy.evaluate` (the module object both paths
    # resolve through) is what the pipeline's own module docstring pins as
    # the sanctioned seam.
    monkeypatch.setattr("tradekit.policy.evaluate", _evaluate_then_concurrent_halt)

    with pytest.raises(BrokerTokenRequired) as excinfo:
        broker.execute_order(thesis_id)
    assert "halted" in str(excinfo.value).lower()

    # The allow verdict itself IS on the ledger (intent + verdict survive —
    # DESIGN §8.2's own ordering guarantee) — only the broker call refused.
    verdict_issued = _events_of_type(thesis_id, "VerdictIssued")
    assert len(verdict_issued) == 1
    assert verdict_issued[0].payload["allow"] is True

    _zero_money_path_events(thesis_id)
    assert thesis._machine.derive_state(default_ledger(), thesis_id) == "approved", (
        "a halt-refused submit must never activate the thesis"
    )

    halts = list(default_ledger().query(EventFilter(types=["HaltSet"])))
    assert len(halts) == 1, "exactly the one harness-appended concurrent HaltSet"


# ---------------------------------------------------------------------------
# (b) advisory reconcile x phantom fill -> auto-halt -> everything denies
# ---------------------------------------------------------------------------


class _FakeAdvisoryBrokerPort:
    """Fake `BrokerPort` mirroring `ManualBroker`'s real shapes (typed
    `contracts.Fill` instances, `"advisory:*"` account_ref convention) — the
    only way to exercise `reconcile`'s mismatch branch against an advisory
    account, since a real `ManualBroker.fills()` derives FROM the same
    ledger `reconcile` reads and can never disagree with itself (mirrors
    `tests/unit/broker/test_reconcile.py::_FakeBrokerPort`'s own rationale,
    applied to the advisory tier this scenario is pinned to)."""

    def __init__(self, account_ref: str, fills: list[Fill]) -> None:
        self.account_ref = account_ref
        self._fills = fills

    def account(self):  # pragma: no cover - unused by reconcile
        raise NotImplementedError

    def positions(self):  # pragma: no cover - unused by reconcile
        raise NotImplementedError

    def submit(self, order, verdict):  # pragma: no cover - unused by reconcile
        raise NotImplementedError

    def order_status(self, order_id):  # pragma: no cover - unused by reconcile
        raise NotImplementedError

    def fills(self, since):
        return [f for f in self._fills if f.ts_utc >= since]


def test_advisory_reconcile_phantom_fill_auto_halts_and_then_everything_denies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_ref = "advisory:kraken"
    phantom_ts = datetime(2026, 3, 1, tzinfo=UTC)
    phantom_fill = Fill(
        order_id="O-advisory-phantom-1",
        thesis_id="TH-advisory-phantom-1",
        ts_utc=phantom_ts,
        price=Decimal("50000"),
        qty=Decimal("0.001"),
        fees_usd=Decimal("0"),
    )
    # The advisory account's broker-side record (Mike's Kraken read-only
    # balance feed, per §8.4) reports a fill the ledger never saw — no
    # broker.record_manual_fill was ever called for this order_id.
    fake = _FakeAdvisoryBrokerPort(account_ref, [phantom_fill])
    monkeypatch.setattr("tradekit.broker.get", lambda ref: fake)

    broker.reconcile(account_ref)

    runs = [
        e
        for e in default_ledger().query(EventFilter(types=["ReconciliationRun"]))
        if e.payload.get("account_ref") == account_ref
    ]
    assert len(runs) == 1
    assert runs[0].payload["result"] == "mismatch"

    halts = list(default_ledger().query(EventFilter(types=["HaltSet"])))
    assert len(halts) == 1
    assert halts[0].payload["scope"] == "all"

    # "everything denies" — scope="all" means EVERY account, not just the
    # advisory one that triggered it (both a mutating action ON the
    # advisory account, and an UNRELATED paper account, deny via R-001).
    for probe_account_ref in (account_ref, "paper:alpha", "live:unrelated-account"):
        verdict = policy.evaluate(
            ProposedAction(
                kind="submit_order",
                account_ref=probe_account_ref,
                requested_by="agent:test",
                order=None,
            )
        )
        assert verdict.allow is False, (
            f"account_ref={probe_account_ref!r} must be denied — a scope=all HaltSet denies "
            "every account, not just the one that triggered it"
        )
        assert any(hit.rule_id == "R-001" and hit.outcome == "fail" for hit in verdict.rule_hits)


# ---------------------------------------------------------------------------
# (c) token x demotion window: a post-demotion execute_order re-evaluates
# and denies via R-002 — zero Order* events.
# ---------------------------------------------------------------------------


def test_execute_order_after_demotion_reevaluates_and_denies_via_r002(
    thesis_kwargs, monkeypatch: pytest.MonkeyPatch, make_event
) -> None:
    account_ref = "live:token-demotion-window"
    thesis_id = _build_approved_thesis(
        thesis_kwargs, monkeypatch, make_event, account_ref=account_ref
    )

    # This account WAS confirmed T2 (the earned-thesis, real-promotion
    # shape) ...
    default_ledger().append(
        make_event(
            type="PromotionConfirmed",
            payload={
                "account_ref": account_ref,
                "to_tier": "T2",
                "granted_event_id": "grant-demotion-window",
                "live_sequence_remaining": 3,
                "confirmed_by": "mike",
            },
            ts=_SUBMIT_BAR_START,
        )
    )
    # ... but was THEN demoted (harness event, mirroring
    # `policy.promotion_status`'s own machine-evaluated demotion path) —
    # strictly AFTER the PromotionConfirmed, and BEFORE execute_order runs.
    default_ledger().append(
        make_event(
            type="Demoted",
            payload={
                "account_ref": account_ref,
                "from_tier": "T2",
                "to_tier": "T1",
                "trigger": "gate_violation",
                "detail": "R-009 (fabricated-for-scenario)",
            },
            ts=_SUBMIT_BAR_START + timedelta(hours=1),
        )
    )

    with pytest.raises(PipelineDenied) as excinfo:
        broker.execute_order(thesis_id)

    assert excinfo.value.verdict.allow is False
    assert any(hit.rule_id == "R-002" for hit in excinfo.value.verdict.rule_hits), (
        "execute_order must RE-EVALUATE policy fresh at call time — the demotion that "
        "happened after the earlier PromotionConfirmed must be reflected in THIS verdict, "
        "denying via R-002 (insufficient tier for a live: order)"
    )

    _zero_money_path_events(thesis_id)
    assert thesis._machine.derive_state(default_ledger(), thesis_id) == "approved", (
        "a denied order must never activate the thesis"
    )
    assert _events_of_type(thesis_id, "ActionProposed"), "intent must still be recorded"
    assert _events_of_type(thesis_id, "VerdictIssued"), "the deny verdict must still be recorded"
