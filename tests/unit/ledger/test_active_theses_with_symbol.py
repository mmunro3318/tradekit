"""`ledger.models.active_theses_with_symbol()` — SPEC-cadence T3 CTO
adjudication accessor (review round 22, fix F9). `_models.py`'s own
docstring already pins the behavior: `active_theses()` plus each row's
symbol, recovered from its own `ThesisDrafted` contract (the `theses`
projection carries no symbol column). The accessor itself predates this
fix round (`cadence.run_once` already consumes it) — this file is its own
dedicated coverage, missing until now; follows `test_models.py`'s existing
fixture/helper conventions (`ledger`/`make_event`).
"""

from __future__ import annotations

from tradekit.ledger._models import ActiveThesisWithSymbol


def _drafted(
    ledger, make_event, thesis_id: str, account_ref: str, strategy_tag: str, symbol: str
) -> None:
    ledger.append(
        make_event(
            type="ThesisDrafted",
            payload={
                "thesis_id": thesis_id,
                "contract": {
                    "account_ref": account_ref,
                    "strategy_tag": strategy_tag,
                    "asset": {"symbol": symbol},
                },
                "supersedes": None,
            },
        )
    )


def _to_active(ledger, make_event, thesis_id: str) -> None:
    ledger.append(make_event(type="ThesisSubmitted", payload={"thesis_id": thesis_id}))
    ledger.append(
        make_event(
            type="ReviewCompleted",
            payload={
                "thesis_id": thesis_id,
                "review_artifact_id": "rev-1",
                "passed": True,
                "kind": "thesis_review",
            },
        )
    )
    ledger.append(make_event(type="ThesisApproved", payload={"thesis_id": thesis_id}))
    ledger.append(
        make_event(type="ThesisActivated", payload={"thesis_id": thesis_id, "order_id": "ord-1"})
    )


def test_active_theses_with_symbol_returns_symbol_for_active_rows_only(ledger, make_event) -> None:
    _drafted(ledger, make_event, "th-active-1", "paper:alpha", "momo-breakout-v1", "ETH/USD")
    _to_active(ledger, make_event, "th-active-1")
    _drafted(ledger, make_event, "th-draft-only", "paper:alpha", "mean-rev-v1", "SOL/USD")
    ledger.rebuild()

    rows = ledger.models.active_theses_with_symbol()
    assert all(isinstance(row, ActiveThesisWithSymbol) for row in rows)
    ids = {row.thesis_id for row in rows}
    assert ids == {"th-active-1"}, "only the ACTIVE thesis is returned, never a bare draft"

    row = next(r for r in rows if r.thesis_id == "th-active-1")
    assert row.account_ref == "paper:alpha"
    assert row.strategy_tag == "momo-breakout-v1"
    assert row.symbol == "ETH/USD", (
        "symbol must be recovered from the thesis's own ThesisDrafted contract"
    )


def test_active_theses_with_symbol_empty_ledger_returns_empty_list(ledger) -> None:
    ledger.rebuild()
    assert ledger.models.active_theses_with_symbol() == []
