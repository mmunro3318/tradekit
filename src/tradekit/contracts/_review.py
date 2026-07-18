"""`ReviewArtifact` / `Verification` -- the two return-value contracts for
`tradekit.review`'s public surface (DESIGN §4.2/§12, SPRINT P3 batch D).

`run_review(thesis_id) -> ReviewArtifact` and `verify_claim(claim) ->
Verification` are pinned by the batch dispatch to return PLAIN DICTS
(`model_dump(mode="json")`), not model instances -- same "verb surface
returns JSON-shaped data" convention as every other `tradekit.*` deep
module (mirrors `broker.execute_order -> OrderAck`'s own dict-shaped CLI
consumption via `.model_dump_json()`). The models below are the producer-
side validation layer (typo'd/missing field dies at construction, never
silently), and the ledgered `ReviewCompleted` EVENT payload
(`contracts.ReviewCompletedPayload`) stays the separate, narrower,
ledger-facing shape -- a `ReviewArtifact` is the FULL transcript+scores
object; the ledger event is a pointer to it (`review_artifact_id`) plus the
pass/fail verdict, same "artifact vs pointer-event" split DESIGN §12.1
describes ("`ReviewArtifact` (full transcript, scores, model+version) is
ledgered with the thesis").

Heterogeneous sub-structures (attack/defense exchange transcript, rubric
category scores) stay plain JSON objects under the same ASSUMPTIONS-10
deferral every other producer-side contract in this package uses -- a
reviewer-model JSON exchange shape is reviewer/prompt-version-dependent,
not something this shared leaf should freeze into a nested typed model
this early.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, Field

from tradekit.contracts._base import StrictFrozenModel


class ReviewArtifact(StrictFrozenModel):
    """`run_review(thesis_id) -> ReviewArtifact` (DESIGN §4.2). Ledgered
    alongside the thesis (§12.1) -- `review_artifact_id` is the join key
    the `ReviewCompleted` event payload carries.

    `kind` mirrors `ReviewCompletedPayload.kind` (`"thesis_review"` |
    `"void_signoff"` -- one artifact shape, two use sites, ASSUMPTIONS 73's
    existing convention carried forward). `auto_fail_reason` is set (and
    `exchanges`/`rubric_scores` are empty) exactly when `run_review` short-
    circuited BEFORE spending any reviewer tokens (sprint doc addendum:
    "AUTO-FAIL SHORT-CIRCUITS FIRST ... before any adapter call, zero
    tokens spent"). `failure_mode` mirrors the event payload's field of the
    same name -- set exactly when the adapter boundary failed (malformed
    JSON / timeout / oversized output) rather than the rubric producing a
    real fail verdict."""

    review_artifact_id: str
    thesis_id: str
    kind: Literal["thesis_review", "void_signoff"] = "thesis_review"
    passed: bool
    model: str  # e.g. "codex" | "gemini" (reviewer_binary dial, §12.1 "model+version")
    model_version: str | None = None
    auto_fail_reason: str | None = None
    failure_mode: (
        Literal["malformed_output", "timeout", "output_too_large"] | None
    ) = None
    # Attack/defense transcript: one dict per exchange round, reviewer-JSON-
    # shaped (attack claim, proposer defense, per-category rubric scores,
    # resolved bool) -- see prompts/rubric-thesis-v1.md for the schema this
    # batch DRAFTS (not yet Mike-ratified).
    exchanges: list[dict[str, Any]] = Field(default_factory=list)
    rubric_scores: dict[str, Any] = Field(default_factory=dict)
    unresolved_attack_count: int = 0
    ts_utc: AwareDatetime


class Verification(StrictFrozenModel):
    """`verify_claim(claim) -> Verification` (DESIGN §4.2/§12.2). Rides the
    SAME `LLMReviewerPort`, a different prompt kit -- MVP done-gate use
    (§12.2, ledger extract + broker records + `verify_chain()` proof) and
    the void sign-off use (§10.4 guard 2) share this one return shape.

    `claim_kind` names what was being verified (`"void_signoff"` for the
    thesis-void path this batch closes; `"trade_settlement"` reserved for
    P4's §12.2 done-gate, not exercised by any P3 test). `review_artifact_id`
    is set whenever the verification produced a ledgered `ReviewArtifact`
    (always true for `"void_signoff"`, per §10.4's guard requiring a real
    reviewer sign-off artifact to exist before `thesis.void` can succeed)."""

    verification_id: str
    claim_kind: Literal["void_signoff", "trade_settlement"]
    passed: bool
    review_artifact_id: str | None = None
    notes: str | None = None
    ts_utc: AwareDatetime


__all__ = ["ReviewArtifact", "Verification"]
