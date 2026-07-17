"""`broker.reconcile` — broker records vs ledger, mismatch -> automatic halt
(DESIGN §8.2 step 7, §15's "out-of-band detection" row; SPRINT P3 batch C,
pre-registered Opus review focus: HALT PATH).

Status: RED this batch — `broker._pipeline.reconcile` is an unconditional
`NotImplementedError` stub. Every assertion below describes the REAL
behavior the dev pass implements next.

A REAL `PaperBroker`'s `fills()` derives FROM the SAME ledger `reconcile`
reads (`_paper.py`'s own "no mutable broker state" discipline) — it can
never disagree with itself, so the mismatch branch is only reachable
through a FAKE `BrokerPort` here (ASSUMPTIONS round-18: "mocks mirror real
shapes" — the fake returns real `contracts.Fill` instances, never ad hoc
dicts).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from ulid import ULID

from tradekit import broker, policy
from tradekit.contracts import (
    Event,
    EventFilter,
    Fill,
    ProposedAction,
)
from tradekit.ledger import default_ledger

_T0 = datetime(2026, 1, 2, tzinfo=UTC)


class _FakeBrokerPort:
    """Mirrors `BrokerPort`'s real shape (typed `Fill` instances) — the only
    way to exercise `reconcile`'s mismatch branch, since a real
    `PaperBroker` can never disagree with its own ledger."""

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


def _seed_fill_recorded(account_ref: str, *, order_id: str, ts: datetime, qty: str) -> None:
    default_ledger().append(
        Event(
            event_id=str(ULID()),
            ts_utc=ts,
            type="FillRecorded",
            actor="system:test-harness",
            run_id=None,
            schema_ver=1,
            payload={
                "order_id": order_id,
                "thesis_id": "TH-recon-1",
                "account_ref": account_ref,
                "ts_utc": ts.isoformat(),
                "price": "100.00",
                "qty": qty,
                "fees_usd": "0.10",
                "side": "buy",
                "quote_snapshot": {},
                "symbol": "BTC/USD",
            },
        )
    )


def _fill(*, order_id: str, ts: datetime, qty: str) -> Fill:
    return Fill(
        order_id=order_id,
        thesis_id="TH-recon-1",
        ts_utc=ts,
        price=Decimal("100.00"),
        qty=Decimal(qty),
        fees_usd=Decimal("0.10"),
    )


def test_reconcile_ok_when_every_broker_fill_matches_the_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_ref = "paper:reconcile-ok"
    _seed_fill_recorded(account_ref, order_id="O-1", ts=_T0, qty="0.001")
    fake = _FakeBrokerPort(account_ref, [_fill(order_id="O-1", ts=_T0, qty="0.001")])
    monkeypatch.setattr("tradekit.broker.get", lambda ref: fake)

    broker.reconcile(account_ref)

    runs = [
        e
        for e in default_ledger().query(EventFilter(types=["ReconciliationRun"]))
        if e.payload.get("account_ref") == account_ref
    ]
    assert len(runs) == 1
    assert runs[0].payload["result"] == "ok"

    halts = list(default_ledger().query(EventFilter(types=["HaltSet"])))
    assert halts == []


def test_reconcile_mismatch_appends_reconciliation_run_and_halts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    account_ref = "paper:reconcile-mismatch"
    # Ledger has NO FillRecorded for this account — the broker reports one
    # anyway (an out-of-band trade, §15's own threat-model row).
    fake = _FakeBrokerPort(account_ref, [_fill(order_id="O-oob-1", ts=_T0, qty="0.005")])
    monkeypatch.setattr("tradekit.broker.get", lambda ref: fake)

    broker.reconcile(account_ref)

    runs = [
        e
        for e in default_ledger().query(EventFilter(types=["ReconciliationRun"]))
        if e.payload.get("account_ref") == account_ref
    ]
    assert len(runs) == 1
    assert runs[0].payload["result"] == "mismatch"
    assert runs[0].payload["mismatches"], "the unmatched broker fill must be named in the payload"

    halts = list(default_ledger().query(EventFilter(types=["HaltSet"])))
    assert len(halts) == 1
    reason = halts[0].payload["reason"]
    assert "O-oob-1" in reason or "reconcil" in reason.lower()


def test_reconcile_mismatch_then_evaluate_denies_everything_via_r001(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    account_ref = "paper:reconcile-mismatch-halt"
    fake = _FakeBrokerPort(account_ref, [_fill(order_id="O-oob-2", ts=_T0, qty="0.005")])
    monkeypatch.setattr("tradekit.broker.get", lambda ref: fake)

    broker.reconcile(account_ref)
    assert list(default_ledger().query(EventFilter(types=["HaltSet"])))

    verdict = policy.evaluate(
        ProposedAction(
            kind="submit_order", account_ref=account_ref, requested_by="agent:test", order=None
        )
    )
    assert verdict.allow is False
    assert any(hit.rule_id == "R-001" for hit in verdict.rule_hits)


def test_reconcile_does_not_match_fills_across_different_order_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Match key is `(order_id, ts_utc, qty)` (ASSUMPTIONS round-18, pinned
    exact-triple match, no fuzzy tolerance) — a ledger fill with a
    DIFFERENT order_id than the broker's, even with identical ts/qty, must
    still count as a mismatch."""

    account_ref = "paper:reconcile-order-id-mismatch"
    _seed_fill_recorded(account_ref, order_id="O-ledger-1", ts=_T0, qty="0.001")
    fake = _FakeBrokerPort(account_ref, [_fill(order_id="O-broker-1", ts=_T0, qty="0.001")])
    monkeypatch.setattr("tradekit.broker.get", lambda ref: fake)

    broker.reconcile(account_ref)

    runs = [
        e
        for e in default_ledger().query(EventFilter(types=["ReconciliationRun"]))
        if e.payload.get("account_ref") == account_ref
    ]
    assert runs[0].payload["result"] == "mismatch"


def test_reconcile_ok_seeds_verdict_payload_for_a_seeded_policy_evaluate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clean reconcile never halts — a subsequent `policy.evaluate` for
    the same account is unaffected by R-001 (still may deny for OTHER
    reasons, e.g. insufficient context — this test asserts only that R-001
    itself does not fire)."""

    account_ref = "paper:reconcile-clean-no-halt"
    _seed_fill_recorded(account_ref, order_id="O-clean-1", ts=_T0, qty="0.001")
    fake = _FakeBrokerPort(account_ref, [_fill(order_id="O-clean-1", ts=_T0, qty="0.001")])
    monkeypatch.setattr("tradekit.broker.get", lambda ref: fake)

    broker.reconcile(account_ref)

    verdict = policy.evaluate(
        ProposedAction(
            kind="submit_order", account_ref=account_ref, requested_by="agent:test", order=None
        )
    )
    assert not any(hit.rule_id == "R-001" and hit.outcome == "fail" for hit in verdict.rule_hits)
