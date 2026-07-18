"""Shared harness for `tests/unit/review/*` (SPRINT P3 batch D).

`review.run_review`/`verify_claim` read thesis state off the LEDGER
(`ThesisDrafted`/`ThesisSubmitted`/`SizingComputed` events), never a fresh
call to `thesis.draft`/`submit` plus mocked market data -- the auto-fail
short-circuit tests specifically need ENGINEERED mismatches (a size that
disagrees with `SizingComputed`, an empty `success_criteria` list) that the
real `thesis.submit` verb would refuse to produce honestly (it validates
sizing/EV tolerance itself). So this harness constructs the three
producer-side events DIRECTLY through their typed payload models
(ASSUMPTIONS 10's "producer pattern": validate through the model, then
`model_dump(mode="json")` into the ledger) -- the SAME technique
`test_void_verb.py::_append_void_signoff` uses for its own harness action,
just applied one level earlier in the lifecycle.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from ulid import ULID

from tradekit.contracts import (
    Event,
    EventFilter,
    SizingComputedPayload,
    ThesisContract,
    ThesisDraftedPayload,
    ThesisSubmittedPayload,
)
from tradekit.ledger import default_ledger

SUBMIT_TS = datetime(2026, 3, 1, tzinfo=UTC)


def _seed_submitted_thesis(
    thesis_kwargs: dict[str, Any],
    make_event,
    *,
    ev_usd: Decimal | None = None,
    success_criteria: list[dict[str, Any]] | None = None,
    size_usd: Decimal | None = None,
    recommended_size_usd: Decimal | None = None,
) -> str:
    """Seed a thesis at the `submitted` state (drafted+submitted+sized) by
    appending the three real producer-side events directly -- see module
    docstring for why this bypasses `thesis.draft`/`submit` themselves.
    Every override defaults to an HONEST value (matches what a real submit
    would have produced) so a test overriding exactly ONE knob engineers
    exactly ONE auto-fail condition, never several at once."""
    kw = dict(thesis_kwargs)
    if success_criteria is not None:
        kw["success_criteria"] = success_criteria
    if ev_usd is not None:
        kw["ev_block"] = {**kw["ev_block"], "ev_usd": str(ev_usd)}
    if size_usd is not None:
        kw["size_usd"] = size_usd
    contract = ThesisContract(**kw)

    ledger = default_ledger()
    ledger.append(
        make_event(
            type="ThesisDrafted",
            ts=SUBMIT_TS,
            payload=ThesisDraftedPayload(
                thesis_id=contract.thesis_id,
                contract=contract.model_dump(mode="json"),
            ).model_dump(mode="json"),
        )
    )
    ledger.append(
        make_event(
            type="ThesisSubmitted",
            ts=SUBMIT_TS,
            payload=ThesisSubmittedPayload(
                thesis_id=contract.thesis_id,
                market_snapshot_id=contract.market_snapshot_id,
                resolved_target_price=contract.target_price,
                resolved_stop_price=contract.stop_price,
                resolved_success_criteria=[
                    p.model_dump(mode="json") if hasattr(p, "model_dump") else p
                    for p in contract.success_criteria
                ],
                resolved_failure_criteria=[
                    p.model_dump(mode="json") if hasattr(p, "model_dump") else p
                    for p in contract.failure_criteria
                ],
                ev_stated_usd=contract.ev_block.ev_usd,
                ev_recomputed_usd=contract.ev_block.ev_usd,
            ).model_dump(mode="json"),
        )
    )
    ledger.append(
        make_event(
            type="SizingComputed",
            ts=SUBMIT_TS,
            payload=SizingComputedPayload(
                thesis_id=contract.thesis_id,
                symbol=contract.asset.symbol,
                account_equity_usd=Decimal("500.00"),
                sizing={
                    "recommended_size_usd": str(
                        recommended_size_usd
                        if recommended_size_usd is not None
                        else contract.size_usd
                    )
                },
            ).model_dump(mode="json"),
        )
    )
    return contract.thesis_id


@pytest.fixture
def seed_submitted_thesis(thesis_kwargs, make_event):
    """Factory fixture wrapping `_seed_submitted_thesis` — bound to THIS
    test's own `thesis_kwargs`/`make_event`, so a test calls it with only
    the override kwargs it cares about."""

    def _seed(**overrides: Any) -> str:
        return _seed_submitted_thesis(thesis_kwargs, make_event, **overrides)

    return _seed


@pytest.fixture
def thesis_events():
    """Factory: events of `event_type` whose payload references `thesis_id`."""

    def _get(event_type: str, thesis_id: str) -> list[Event]:
        return [
            e
            for e in default_ledger().query(EventFilter(types=[event_type]))
            if e.payload.get("thesis_id") == thesis_id
        ]

    return _get


@pytest.fixture
def fresh_thesis_id() -> str:
    return str(ULID())
