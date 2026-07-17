"""`broker.create_paper_account` (TD-24, SPRINT P3 batch A) — real this
batch: validates an `AccountConfig`, refuses a duplicate `account_ref`, and
ledgers `AccountCreated`. `TK_DATA_DIR` isolation is the autouse
`_tk_data_dir_isolation` fixture (tests/conftest.py).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tradekit import broker
from tradekit.contracts import AccountConfig, EventFilter
from tradekit.ledger import default_ledger


def _config(**overrides: object) -> AccountConfig:
    base: dict[str, object] = {
        "account_ref": "paper:new-account",
        "principal_usd": Decimal("500.00"),
        "max_trades_per_day": 0,
    }
    base.update(overrides)
    return AccountConfig(**base)  # type: ignore[arg-type]


def test_create_paper_account_appends_account_created_and_returns_the_ref() -> None:
    account_ref = broker.create_paper_account(_config())
    assert account_ref == "paper:new-account"

    events = default_ledger().query(EventFilter(types=["AccountCreated"]))
    assert len(events) == 1
    assert events[0].payload["account_ref"] == "paper:new-account"
    assert events[0].payload["config"]["principal_usd"] == "500.00"


def test_create_paper_account_refuses_a_duplicate_account_ref() -> None:
    broker.create_paper_account(_config())
    with pytest.raises(broker.AccountAlreadyExists) as exc_info:
        broker.create_paper_account(_config())
    assert exc_info.value.account_ref == "paper:new-account"

    # No second AccountCreated event — the refusal must be a true no-op.
    events = default_ledger().query(EventFilter(types=["AccountCreated"]))
    assert len(events) == 1


def test_create_paper_account_allows_two_distinct_account_refs() -> None:
    broker.create_paper_account(_config(account_ref="paper:one"))
    broker.create_paper_account(_config(account_ref="paper:two"))
    events = default_ledger().query(EventFilter(types=["AccountCreated"]))
    assert {e.payload["account_ref"] for e in events} == {"paper:one", "paper:two"}
