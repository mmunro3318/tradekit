"""`ReviewArtifact` assembly + ledgering (DESIGN §12.1, TD-21, SPRINT P3
batch D). "`ReviewArtifact` (full transcript, scores, model+version) is
ledgered with the thesis" -- this module is where `run_review`/
`verify_claim`'s pipeline turns (exchanges, rubric_scores, verdict) into a
persisted artifact + the ledgered `ReviewCompleted` event.

`_append_review_completed` mirrors the `_append` ledger-helper convention
every producing module in this sprint uses (`broker.__init__._append`,
`broker._paper.PaperBroker._append`) -- REAL this batch (pure declarative
Event construction, no business logic of its own). `assemble` (composing a
`ReviewArtifact` from the pipeline's intermediate state) is a STUB --
dev pass lands it once `run_review`'s own algorithm is real, since the
exact field wiring depends on that pipeline's shape.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ulid import ULID

from tradekit.contracts import Event, ReviewArtifact, ReviewCompletedPayload
from tradekit.ledger import Ledger, default_ledger

# 'agent:<model>' | 'mike' | 'system:<job>' -- review artifacts are a
# machine-derived ledger append, same actor convention as
# tradekit.broker's _ACTOR / tradekit.thesis's _ACTOR.
_ACTOR = "system:review"


def assemble(
    *,
    thesis_id: str,
    kind: str,
    passed: bool,
    model: str,
    exchanges: list[dict[str, Any]],
    rubric_scores: dict[str, Any],
    unresolved_attack_count: int,
    auto_fail_reason: str | None = None,
    failure_mode: str | None = None,
) -> ReviewArtifact:
    """Pinned target algorithm (dev pass lands this; STUB this batch): mint
    a fresh `review_artifact_id` (ULID, same "cheap identity" pattern as
    every other producer in this codebase), stamp `ts_utc` from
    `mae._runtime.clock()` (the sanctioned clock seam -- never
    `datetime.now()` directly, TD-17), and construct+validate a
    `ReviewArtifact` from the given fields. Validation-only; does NOT
    ledger anything (`_append_review_completed` is the separate write
    step, called by `run_review`/`verify_claim` AFTER this returns, mirrors
    `thesis._submit`'s "validate everything, return payloads; caller
    appends" split)."""
    raise NotImplementedError(
        f"review._artifacts.assemble(thesis_id={thesis_id!r}, kind={kind!r}): SPRINT P3 batch D "
        "dev pass lands this (§12.1 artifact assembly)"
    )


def _append(ledger: Ledger, event_type: str, payload: dict[str, Any], ts: datetime) -> str:
    event = Event(
        event_id=str(ULID()),
        ts_utc=ts,
        type=event_type,  # type: ignore[arg-type]
        actor=_ACTOR,
        run_id=None,
        schema_ver=1,
        payload=payload,
    )
    return ledger.append(event)


def append_review_completed(
    artifact: ReviewArtifact,
    ledger: Ledger | None = None,
) -> str:
    """Ledgers the `ReviewCompleted` EVENT (the narrow pointer+verdict
    shape, `ReviewCompletedPayload` -- distinct from the full
    `ReviewArtifact` this module's `assemble()` builds, per `_review.py`'s
    own "artifact vs pointer-event" docstring split). REAL this batch
    (declarative Event construction over an already-validated
    `ReviewArtifact` -- no decision logic lives here)."""
    ledger = ledger if ledger is not None else default_ledger()
    payload = ReviewCompletedPayload(
        thesis_id=artifact.thesis_id,
        review_artifact_id=artifact.review_artifact_id,
        passed=artifact.passed,
        kind=artifact.kind,
        failure_mode=artifact.failure_mode,
    )
    return _append(ledger, "ReviewCompleted", payload.model_dump(mode="json"), artifact.ts_utc)


__all__ = ["append_review_completed", "assemble"]
