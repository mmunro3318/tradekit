"""`ledger.models` — typed read-model accessors (DESIGN §4.2, SPRINT P3
batch E). `LedgerModels`'s three methods are unconditional
`NotImplementedError` stubs (`ledger/_models.py`'s own docstring); every
test below describes REAL target behavior and is red for that reason alone
(never wrapped in `pytest.raises(NotImplementedError)`, same discipline as
every other red-phase file this sprint). `Ledger.models` itself (the
property construction) is REAL — `test_models_property_is_cheap_and_real`
below is a green control pinning that.
"""

from __future__ import annotations

from datetime import UTC, datetime

from tradekit.ledger._models import LedgerModels


def _drafted(ledger, make_event, thesis_id: str, account_ref: str, strategy_tag: str) -> None:
    ledger.append(
        make_event(
            type="ThesisDrafted",
            payload={
                "thesis_id": thesis_id,
                "contract": {"account_ref": account_ref, "strategy_tag": strategy_tag},
                "supersedes": None,
            },
        )
    )


def _to_active(ledger, make_event, thesis_id: str) -> None:
    ledger.append(make_event(type="ThesisSubmitted", payload={"thesis_id": thesis_id}))
    ledger.append(
        make_event(
            type="ReviewCompleted",
            payload={"thesis_id": thesis_id, "review_artifact_id": "rev-1",
                     "passed": True, "kind": "thesis_review"},
        )
    )
    ledger.append(make_event(type="ThesisApproved", payload={"thesis_id": thesis_id}))
    ledger.append(
        make_event(type="ThesisActivated", payload={"thesis_id": thesis_id, "order_id": "ord-1"})
    )


def _graded(ledger, make_event, thesis_id: str, outcome: str, pnl_usd: str | None, ts) -> None:
    ledger.append(
        make_event(
            type="ThesisGraded",
            ts=ts,
            payload={
                "thesis_id": thesis_id,
                "outcome": outcome,
                "measured": [],
                "ambiguous_bar": False,
                "pnl_usd": pnl_usd,
                "graded_ts": ts.isoformat(),
            },
        )
    )


def test_models_property_is_cheap_and_real(ledger) -> None:
    """Control (GREEN): `Ledger.models` constructs a `LedgerModels` bound to
    this ledger, with no side effects — the stub discipline applies to the
    METHODS, not the property access itself."""
    accessor = ledger.models
    assert isinstance(accessor, LedgerModels)
    assert ledger.models is not accessor, "fresh instance per access (no caching promise)"


def test_active_theses_returns_only_active_state_rows(ledger, make_event) -> None:
    _drafted(ledger, make_event, "th-active-1", "paper:alpha", "momo-breakout-v1")
    _to_active(ledger, make_event, "th-active-1")
    _drafted(ledger, make_event, "th-draft-only", "paper:alpha", "mean-rev-v1")
    ledger.rebuild()

    active = ledger.models.active_theses()
    ids = {t.thesis_id for t in active}
    assert ids == {"th-active-1"}, "only the ACTIVE thesis is returned, never a bare draft"
    row = next(t for t in active if t.thesis_id == "th-active-1")
    assert row.account_ref == "paper:alpha"
    assert row.strategy_tag == "momo-breakout-v1"


def test_active_theses_empty_ledger_returns_empty_list(ledger) -> None:
    ledger.rebuild()
    assert ledger.models.active_theses() == []


def test_account_refs_unions_accounts_table_and_thesis_account_refs(ledger, make_event) -> None:
    ledger.append(
        make_event(
            type="AccountCreated",
            payload={
                "account_ref": "paper:beta",
                "config": {"account_ref": "paper:beta", "principal_usd": "500"},
                "created_ts": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
            },
        )
    )
    # paper:alpha appears only via a thesis (P2's implicit-default-account
    # convention, TD-24) -- no AccountCreated event for it in this ledger.
    _drafted(ledger, make_event, "th-1", "paper:alpha", "momo-breakout-v1")
    ledger.rebuild()

    refs = ledger.models.account_refs()
    assert refs == sorted(refs), "deterministic (sorted) order"
    assert set(refs) == {"paper:alpha", "paper:beta"}


def test_account_refs_empty_ledger_returns_empty_list(ledger) -> None:
    ledger.rebuild()
    assert ledger.models.account_refs() == []


def test_latest_grades_returns_n_most_recent_by_graded_ts_desc(ledger, make_event) -> None:
    for i, (outcome, pnl) in enumerate(
        [("PASS", "12.50"), ("FAIL", "-5.00"), ("VOID", None), ("PASS", "3.00")]
    ):
        tid = f"th-grade-{i}"
        _drafted(ledger, make_event, tid, "paper:alpha", "momo-breakout-v1")
        _to_active(ledger, make_event, tid)
        _graded(ledger, make_event, tid, outcome, pnl, datetime(2026, 1, 1 + i, tzinfo=UTC))
    ledger.rebuild()

    latest = ledger.models.latest_grades(n=2)
    assert [g.thesis_id for g in latest] == ["th-grade-3", "th-grade-2"], (
        "most recently graded first (graded_ts descending)"
    )
    assert latest[0].outcome == "PASS"
    assert str(latest[0].pnl_usd) == "3.00"
    assert latest[1].outcome == "VOID"
    assert latest[1].pnl_usd is None, "a VOID/None-pnl grade stays None, never coerced to 0"
    assert latest[0].account_ref == "paper:alpha"


def test_latest_grades_default_n_is_ten(ledger, make_event) -> None:
    for i in range(12):
        tid = f"th-many-{i}"
        _drafted(ledger, make_event, tid, "paper:alpha", "momo-breakout-v1")
        _to_active(ledger, make_event, tid)
        _graded(ledger, make_event, tid, "PASS", "1.00", datetime(2026, 1, 1 + i, tzinfo=UTC))
    ledger.rebuild()

    assert len(ledger.models.latest_grades()) == 10


def test_latest_grades_empty_ledger_returns_empty_list(ledger) -> None:
    ledger.rebuild()
    assert ledger.models.latest_grades() == []
