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

import os
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from ulid import ULID

from tradekit.broker._alpaca import (
    ALPACA_LIVE_BASE_URL,
    ALPACA_LIVE_KEY_ID_ENV,
    ALPACA_LIVE_SECRET_ENV,
    ALPACA_PAPER_BASE_URL,
    ALPACA_PAPER_KEY_ID_ENV,
    ALPACA_PAPER_SECRET_ENV,
    AlpacaBroker,
)
from tradekit.broker._manual import ManualBroker
from tradekit.broker._manual import record_manual_fill as _manual_record_manual_fill
from tradekit.broker._paper import PaperBroker
from tradekit.broker._pipeline import (
    OrderNotCancelable,
    PipelineDenied,
)
from tradekit.broker._pipeline import cancel_order as _pipeline_cancel_order
from tradekit.broker._pipeline import execute_order as _pipeline_execute_order
from tradekit.broker._pipeline import reconcile as _pipeline_reconcile
from tradekit.broker._port import AdvisoryOnly, BrokerPort, LiveTradingDisabled
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
from tradekit.policy._dials import PolicyDials

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
    """`"paper:*"` -> `PaperBroker` (SPRINT P3 batch B, real).

    `"alpaca-paper:*"` -> `AlpacaBroker` bound to Alpaca's PAPER trading
    base URL + the paper env key names (SPRINT P4-PAPER, addendum 2) -- the
    dress-rehearsal adapter; every method on it is real (`_alpaca.py`'s own
    module docstring) -- same "declarative routing is real, methods land
    with the dev pass" split `ManualBroker` went through in SPRINT P3
    batch D.

    `"live:*"` -> the FAIL-CLOSED live-venue gate (SPRINT P4-PAPER batch A,
    addendum 2 -- REPLACES the SPRINT P3 batch C temporary routing to
    `PaperBroker`, ASSUMPTIONS round-18/round-19; `"live:"` never again
    resolves to `PaperBroker`). Requires BOTH `PolicyDials.
    live_trading_enabled` true AND the live env keys (`ALPACA_LIVE_KEY_ID`/
    `ALPACA_LIVE_SECRET`) present -- either missing raises
    `LiveTradingDisabled` (typed, `broker._port`) before an `AlpacaBroker`
    is ever constructed for a live account_ref. Mike's live keys/rotation
    remain blocked per the sprint doc's Addendum 2 scope note, so this
    path is exercised in tests via `monkeypatch`, never for real.

    `"advisory:*"` (-> `ManualBroker`, §8.1, SPRINT P3 batch D) resolves to
    a real `ManualBroker` instance -- every method on IT is real (batch D
    dev pass)."""
    if account_ref.startswith("paper:"):
        return PaperBroker(account_ref=account_ref)
    if account_ref.startswith("alpaca-paper:"):
        return AlpacaBroker(
            account_ref=account_ref,
            base_url=ALPACA_PAPER_BASE_URL,
            key_id_env=ALPACA_PAPER_KEY_ID_ENV,
            secret_env=ALPACA_PAPER_SECRET_ENV,
        )
    if account_ref.startswith("live:"):
        dials = PolicyDials.load()
        has_live_keys = bool(
            os.environ.get(ALPACA_LIVE_KEY_ID_ENV) and os.environ.get(ALPACA_LIVE_SECRET_ENV)
        )
        if not (dials.live_trading_enabled and has_live_keys):
            raise LiveTradingDisabled(
                f"tradekit.broker.get({account_ref!r}): live trading is disabled -- requires "
                f"BOTH PolicyDials.live_trading_enabled=True (got "
                f"{dials.live_trading_enabled!r}) AND {ALPACA_LIVE_KEY_ID_ENV}/"
                f"{ALPACA_LIVE_SECRET_ENV} present in the environment (got "
                f"has_live_keys={has_live_keys!r}) -- fail-closed conjunction, addendum 2"
            )
        return AlpacaBroker(
            account_ref=account_ref,
            base_url=ALPACA_LIVE_BASE_URL,
            key_id_env=ALPACA_LIVE_KEY_ID_ENV,
            secret_env=ALPACA_LIVE_SECRET_ENV,
        )
    if account_ref.startswith("advisory:"):
        # SPRINT P3 batch D: ManualBroker is real -- every method on it is a
        # real implementation now (see _manual.py's module docstring), not
        # a NotImplementedError stub (that split ended with batch D's own
        # dev pass; this comment was stale, SPRINT P4-PAPER batch A cleanup).
        return ManualBroker(account_ref=account_ref)
    raise NotImplementedError(
        f"tradekit.broker.get({account_ref!r}): no adapter resolves this account_ref prefix"
    )


def execute_order(thesis_id: str) -> OrderAck:
    """The two-phase money pipeline (§8.2): ActionProposed -> policy.evaluate
    -> VerdictIssued -> (deny -> PipelineDenied) -> adapter.submit ->
    OrderSubmitted/OrderAck -> single-poll fill check -> thesis activation
    (+ R-011 live-sequence derivation). Thin delegation to `_pipeline.
    execute_order` (SPRINT P3 batch C dev pass lands the real body — see
    `_pipeline.py`'s module docstring for the pinned algorithm)."""
    return _pipeline_execute_order(thesis_id)


def reconcile(account_ref: str) -> None:
    """Broker records vs ledger; any mismatch -> ReconciliationRun(mismatch)
    + automatic HaltSet (§8.2 step 7, D4/§15). Thin delegation to
    `_pipeline.reconcile` (SPRINT P3 batch C dev pass lands the real body)."""
    _pipeline_reconcile(account_ref)


def cancel_order(account_ref: str, order_id: str) -> None:
    """`tk order cancel` — additive fifth broker verb, TD-24/`create_paper_
    account`'s same "declarative addition, not a §4.2 surface widen" class
    of call (SPRINT P3 batch C, ASSUMPTIONS round-18). MVP: only a resting
    order may be canceled (`OrderNotCancelable` otherwise). Thin delegation
    to `_pipeline.cancel_order` (batch C dev pass lands the real body)."""
    _pipeline_cancel_order(account_ref, order_id)


def record_manual_fill(
    thesis_id: str,
    price: Decimal,
    qty: Decimal,
    fees_usd: Decimal,
    side: Literal["buy", "sell"],
    symbol: str,
    account_ref: str,
) -> Fill:
    """`tk fill record` — advisory/manual fills, `actor="mike"` (D16, §8.4).
    Thin delegation to `_manual.record_manual_fill` (SPRINT P3 batch D dev
    pass lands the real body — see that module's docstring for the pinned
    algorithm). Signature EXPANDED this batch (`side`/`symbol`/
    `account_ref` added, TDD red phase) to the sprint doc's own pinned
    shape — `record_manual_fill(thesis_id, price, qty, fees, side, symbol,
    account_ref)`."""
    return _manual_record_manual_fill(
        thesis_id, price, qty, fees_usd, side, symbol, account_ref
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
    "AdvisoryOnly",
    "AlpacaBroker",
    "BrokerPort",
    "LiveTradingDisabled",
    "ManualBroker",
    "OrderNotCancelable",
    "PaperBroker",
    "PipelineDenied",
    "cancel_order",
    "create_paper_account",
    "execute_order",
    "get",
    "reconcile",
    "record_manual_fill",
]
