"""tradekit.broker — two-phase execution pipeline + venue adapters (DESIGN
§8, §4.2, TD-24).

Deep interface: `get(account_ref)` · `execute_order(thesis_id)` ·
`reconcile(account_ref)` · `record_manual_fill(...)` (§4.2's pinned four
verbs — batches B/C/D land their real bodies; every one is an unconditional
`NotImplementedError` stub THIS batch, each naming the batch that implements
it). `create_paper_account` is TD-24's additive fifth verb (Mike-signed
2026-07-17) — real THIS batch, same "contracts/declarative data are cheap"
status as `policy._rules.RULES`/`policy._dials.PolicyDials`: it validates an
`AccountConfig`, checks for a duplicate `account_ref` (a typed
`AccountAlreadyExists`, never a silent overwrite), and ledgers
`AccountCreated`. Internals (`_pipeline.py`/`_paper.py`/`_manual.py`/
`_alpaca.py`, §8's adapter split) land with their producing batches.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from ulid import ULID

from tradekit.broker._port import BrokerPort
from tradekit.contracts import (
    AccountConfig,
    AccountCreatedPayload,
    Event,
    EventFilter,
    Fill,
    OrderAck,
)
from tradekit.ledger import Ledger, default_ledger
from tradekit.mae import _runtime as _mae_runtime

# 'agent:<model>' | 'mike' | 'system:<job>' — account creation is a machine-
# derived ledger append, same actor convention as tradekit.thesis's _ACTOR.
_ACTOR = "system:broker"


class AccountAlreadyExists(Exception):
    """Raised by `create_paper_account` when `account_ref` already has an
    `AccountCreated` event on the ledger (TD-24: no silent duplicate/
    overwrite — a second `create-paper` for the same account_ref is a caller
    error, not a re-seed)."""

    def __init__(self, account_ref: str) -> None:
        self.account_ref = account_ref
        super().__init__(f"account_ref={account_ref!r} already exists")


def get(account_ref: str) -> BrokerPort:
    """`"paper:alpha"` -> PaperBroker, `"live:alpaca"` -> AlpacaBroker,
    `"advisory:*"` -> ManualBroker (§8.1). STUB — batch B (PaperBroker),
    batch D (ManualBroker/AlpacaBroker stub)."""
    raise NotImplementedError(
        f"tradekit.broker.get({account_ref!r}): batch B (PaperBroker) / batch D "
        "(ManualBroker, AlpacaBroker stub) land the adapter resolution"
    )


def execute_order(thesis_id: str) -> OrderAck:
    """The two-phase money pipeline (§8.2): ActionProposed -> policy.evaluate
    -> VerdictIssued -> (deny -> exit) -> adapter.submit -> OrderSubmitted/
    OrderAck -> fill polling -> FillRecorded -> thesis.activate. STUB —
    batch C."""
    raise NotImplementedError(
        f"tradekit.broker.execute_order({thesis_id!r}): batch C (two-phase pipeline, "
        "§8.2) lands this"
    )


def reconcile(account_ref: str) -> None:
    """Broker records vs ledger; any mismatch -> ReconciliationRun(mismatch)
    + automatic HaltSet (§8.2 step 7, D4). STUB — batch C."""
    raise NotImplementedError(
        f"tradekit.broker.reconcile({account_ref!r}): batch C (reconcile -> auto-halt "
        "path) lands this"
    )


def record_manual_fill(
    thesis_id: str,
    price: Decimal,
    qty: Decimal,
    fees_usd: Decimal,
) -> Fill:
    """`tk fill record` — advisory/manual fills, `actor=mike` (D16, §8.4).
    STUB — batch D (ManualBroker)."""
    raise NotImplementedError(
        f"tradekit.broker.record_manual_fill({thesis_id!r}, ...): batch D "
        "(ManualBroker/advisory mode, D16) lands this"
    )


def _append(ledger: Ledger, event_type: str, payload: dict[str, Any]) -> str:
    event = Event(
        event_id=str(ULID()),
        ts_utc=_mae_runtime.clock(),
        type=event_type,  # type: ignore[arg-type]  # narrowed by callers below
        actor=_ACTOR,
        run_id=None,
        schema_ver=1,
        payload=payload,
    )
    return ledger.append(event)


def _account_exists(ledger: Ledger, account_ref: str) -> bool:
    return any(
        event.payload.get("account_ref") == account_ref
        for event in ledger.query(EventFilter(types=["AccountCreated"]))
    )


def create_paper_account(config: AccountConfig) -> str:
    """TD-24's `tk account create-paper` verb (real this batch — declarative
    validation + one ledger append, same "contracts are cheap" status as the
    policy registries). Duplicate `account_ref` -> `AccountAlreadyExists`
    (typed, no silent overwrite — CLI wraps it into a clean nonzero exit).
    Returns the created `account_ref`."""
    ledger = default_ledger()
    if _account_exists(ledger, config.account_ref):
        raise AccountAlreadyExists(config.account_ref)

    now: datetime = _mae_runtime.clock()
    payload = AccountCreatedPayload(
        account_ref=config.account_ref,
        config=config.model_dump(mode="json"),
        created_ts=now,
    )
    _append(ledger, "AccountCreated", payload.model_dump(mode="json"))
    return config.account_ref


__all__ = [
    "AccountAlreadyExists",
    "BrokerPort",
    "create_paper_account",
    "execute_order",
    "get",
    "reconcile",
    "record_manual_fill",
]
