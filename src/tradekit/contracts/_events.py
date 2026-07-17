"""Event envelope + ledger query/audit contracts (DESIGN §5.3, §6.2, §6.3).

The taxonomy IS a contract: a typo'd event type dies at the envelope, not as
an unqueryable orphan row. Payloads are plain JSON objects in P0; typed
per-event payload models land with their producing subsystems (ASSUMPTIONS 10,
CTO-ratified).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, field_validator

from tradekit.contracts._base import FrozenModel

# §6.3 v1 taxonomy, transcribed in full — one Literal member per line group.
EventType = Literal[
    "RunStarted",
    "ConfigChanged",
    "PolicyVersionLoaded",
    "ThesisDrafted",
    "ThesisSubmitted",
    "MarketSnapshotTaken",
    "SizingComputed",
    "ReviewCompleted",
    "ThesisApproved",
    "ThesisRejected",
    "ThesisActivated",
    "ActionProposed",
    "VerdictIssued",
    "OrderSubmitted",
    "OrderAck",
    "OrderCancelled",
    "FillRecorded",
    "InvalidationAttested",
    "ThesisGraded",
    "SeriesClosed",
    "PromotionGranted",
    "PromotionConfirmed",
    "Demoted",
    "CircuitBreakerTripped",
    "HaltSet",
    "HaltCleared",
    "GateViolationDetected",
    "LessonRecorded",
    "ReconciliationRun",
    # SPRINT P3 batch A (TD-24): named-account lifecycle.
    "AccountCreated",
]


class Event(FrozenModel):
    """Envelope: matches the §6.2 column list (ASSUMPTIONS 9)."""

    event_id: str  # ULID
    ts_utc: AwareDatetime  # tz-aware required (ASSUMPTIONS 18); ledger stores ISO-8601 UTC
    type: EventType
    actor: str  # 'agent:<model>' | 'mike' | 'system:<job>'
    run_id: str | None = None  # stamped by the ledger at append when missing (TD-20)
    schema_ver: int
    payload: dict[str, Any]

    @field_validator("event_id", "actor", "run_id")
    @classmethod
    def _no_control_chars(cls, v: str | None) -> str | None:
        # Control characters in identity fields could smuggle preimage
        # structure or garble audit output (reviewer D3, ASSUMPTIONS 22).
        if v is not None and any(ord(c) < 0x20 for c in v):
            raise ValueError("control characters are not allowed in ledger identity fields")
        return v


class EventFilter(FrozenModel):
    """Ledger query shape (ASSUMPTIONS 12); since/until are inclusive.

    Aware datetimes required: a naive bound would be read as machine-local
    time and silently shift the window (TD-17, reviewer D2, ASSUMPTIONS 20).
    """

    types: list[str] | None = None
    since: AwareDatetime | None = None
    until: AwareDatetime | None = None


class ChainReport(FrozenModel):
    """verify_chain() result (ASSUMPTIONS 13)."""

    ok: bool
    first_bad_seq: int | None = None
