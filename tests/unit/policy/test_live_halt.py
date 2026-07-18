"""Live-path no-auto-resume (SPRINT P4-PAPER batch B, addendum 2: "No-
auto-resume on the live path, structurally"): `HaltSetPayload.live_path`;
`broker._pipeline.reconcile` sets it true for a `"live:"`-prefixed
`account_ref`; `policy.resume()` refuses to clear a currently-unresolved
`live_path=True` halt unless called with `confirm_live=True` (typed
`policy.LiveHaltRequiresManualConfirm`, the CLI's `tk policy resume
--live-confirm`). Paper-path halts (every manual `policy.halt()`, and a
reconcile mismatch on a non-"live:" account) resume exactly as before —
regression-pinned by the last two tests in this file.

Status: RED this batch — `HaltSetPayload` has no `live_path` field,
`policy.resume()` accepts no `confirm_live` keyword, and
`policy.LiveHaltRequiresManualConfirm` does not exist yet. Every assertion
below describes the REAL target behavior the dev pass implements next
(same red-phase discipline as the rest of this sprint's red files).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tradekit import broker, policy
from tradekit.contracts import EventFilter, Fill, ProposedAction
from tradekit.ledger import default_ledger

_T0 = datetime(2026, 4, 1, tzinfo=UTC)


class _FakeBrokerPort:
    """Mirrors `BrokerPort`'s real shape (typed `Fill` instances) — same
    pattern `tests/unit/broker/test_reconcile.py::_FakeBrokerPort` uses to
    exercise `reconcile`'s mismatch branch (a real `PaperBroker`/
    `AlpacaBroker` can never disagree with its own ledger)."""

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


def _oob_fill(order_id: str) -> Fill:
    return Fill(
        order_id=order_id,
        thesis_id="TH-live-halt-1",
        ts_utc=_T0,
        price=Decimal("100"),
        qty=Decimal("0.01"),
        fees_usd=Decimal("0.10"),
    )


def _reconcile_mismatch(monkeypatch: pytest.MonkeyPatch, account_ref: str, order_id: str) -> None:
    fake = _FakeBrokerPort(account_ref, [_oob_fill(order_id)])
    monkeypatch.setattr("tradekit.broker.get", lambda ref: fake)
    broker.reconcile(account_ref)


def _mutating_action(account_ref: str) -> ProposedAction:
    return ProposedAction(
        kind="submit_order", account_ref=account_ref, requested_by="agent:test", order=None
    )


# ---------------------------------------------------------------------------
# HaltSetPayload.live_path — producer-side (broker._pipeline.reconcile)
# ---------------------------------------------------------------------------


def test_reconcile_mismatch_on_a_live_account_sets_halt_set_live_path_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_ref = "live:reconcile-mismatch-live-path"
    _reconcile_mismatch(monkeypatch, account_ref, "O-live-1")

    halts = list(default_ledger().query(EventFilter(types=["HaltSet"])))
    assert len(halts) == 1
    assert halts[0].payload["live_path"] is True


def test_reconcile_mismatch_on_a_paper_account_sets_halt_set_live_path_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression pin: a paper-tier reconcile mismatch is unaffected by the
    live_path addition — the field is additive, default False."""
    account_ref = "paper:reconcile-mismatch-live-path-regression"
    _reconcile_mismatch(monkeypatch, account_ref, "O-paper-1")

    halts = list(default_ledger().query(EventFilter(types=["HaltSet"])))
    assert len(halts) == 1
    assert halts[0].payload["live_path"] is False


def test_manual_policy_halt_never_sets_live_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """`policy.halt(reason)` carries no `account_ref` — it structurally
    cannot key `live_path` off of one, so a manual `tk policy halt` always
    appends `live_path=False` (the NARROW reading pinned by addendum 2's own
    wording: "reconcile sets it true when the account_ref is live-prefixed"
    — see this module's own docstring / ASSUMPTIONS for the broader FLAGGED
    alternative)."""
    policy.halt("manual kill switch")
    halts = list(default_ledger().query(EventFilter(types=["HaltSet"])))
    assert len(halts) == 1
    assert halts[0].payload["live_path"] is False


# ---------------------------------------------------------------------------
# resume() — refuses a live_path halt without confirm_live=True; the halt
# STANDS (R-001 keeps denying) on the refusal path.
# ---------------------------------------------------------------------------


def test_resume_refuses_a_live_path_halt_without_confirm_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_ref = "live:resume-refuse"
    _reconcile_mismatch(monkeypatch, account_ref, "O-live-2")

    with pytest.raises(policy.LiveHaltRequiresManualConfirm):
        policy.resume()

    # No HaltCleared was appended — the refusal is a true no-op on the ledger.
    assert list(default_ledger().query(EventFilter(types=["HaltCleared"]))) == []

    verdict = policy.evaluate(_mutating_action(account_ref))
    assert verdict.allow is False
    assert any(hit.rule_id == "R-001" and hit.outcome == "fail" for hit in verdict.rule_hits), (
        "the halt must STAND after a refused resume() — R-001 keeps denying"
    )


def test_resume_confirm_live_false_is_the_default_and_still_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_ref = "live:resume-refuse-default"
    _reconcile_mismatch(monkeypatch, account_ref, "O-live-3")

    with pytest.raises(policy.LiveHaltRequiresManualConfirm):
        policy.resume(confirm_live=False)


# ---------------------------------------------------------------------------
# resume(confirm_live=True) — the Mike-manual escape hatch clears it.
# ---------------------------------------------------------------------------


def test_resume_with_confirm_live_true_clears_a_live_path_halt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_ref = "live:resume-confirm"
    _reconcile_mismatch(monkeypatch, account_ref, "O-live-4")

    policy.resume(confirm_live=True)

    cleared = list(default_ledger().query(EventFilter(types=["HaltCleared"])))
    assert len(cleared) == 1

    verdict = policy.evaluate(_mutating_action(account_ref))
    assert not any(
        hit.rule_id == "R-001" and hit.outcome == "fail" for hit in verdict.rule_hits
    ), "resume(confirm_live=True) must actually clear the halt — R-001 must not still deny"


# ---------------------------------------------------------------------------
# Regression pin — paper-path halts resume normally, no confirm_live needed.
# ---------------------------------------------------------------------------


def test_resume_clears_a_manual_paper_path_halt_without_confirm_live_regression() -> None:
    policy.halt("manual paper halt")
    policy.resume()  # no confirm_live — must NOT raise LiveHaltRequiresManualConfirm

    verdict = policy.evaluate(_mutating_action("paper:alpha"))
    assert not any(hit.rule_id == "R-001" and hit.outcome == "fail" for hit in verdict.rule_hits)


def test_resume_clears_a_paper_reconcile_halt_without_confirm_live_regression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_ref = "paper:resume-regression"
    _reconcile_mismatch(monkeypatch, account_ref, "O-paper-2")

    policy.resume()  # no confirm_live — must NOT raise LiveHaltRequiresManualConfirm

    verdict = policy.evaluate(_mutating_action(account_ref))
    assert not any(hit.rule_id == "R-001" and hit.outcome == "fail" for hit in verdict.rule_hits)
