"""tradekit.review — adversarial review + verification (DESIGN §12, TD-21,
SPRINT P3 batch D).

Deep interface (§4.2, exactly two verbs): `run_review(thesis_id) -> dict`
(a `ReviewArtifact.model_dump(mode="json")`) and `verify_claim(claim: dict)
-> dict` (a `Verification.model_dump(mode="json")`). Internals: `_port.py`
(`LLMReviewerPort` Protocol + the three subprocess-boundary exceptions),
`_adapters.py` (subprocess Codex/Gemini adapters — NEVER invoked with a
real binary in this test suite), `_rubric.py` (deterministic Python
scoring), `_artifacts.py` (`ReviewArtifact` assembly + ledgering).

Status THIS batch (TDD red phase, "Failing tests + stubs" dispatch): both
verbs below are unconditional `NotImplementedError` stubs. Every algorithm
step is pinned in the docstrings so the dev pass has no design decisions
left to make — mirrors `broker._pipeline.execute_order`'s own red-phase
docstring discipline (SPRINT P3 batch C).

`run_review` pipeline (§12.1, sprint doc addendum, binding order):
  1. AUTO-FAIL SHORT-CIRCUITS FIRST — BEFORE any adapter call, zero tokens
     spent (sprint doc's own phrasing). Three checks, evaluated in this
     order, first match wins:
       a. missing/non-numeric EV block on the thesis contract (F5) ->
          `failure_mode=None`, `auto_fail_reason="missing_numeric_ev"`.
       b. no falsifiable success criteria (`ThesisContract.success_criteria`
          empty, OR every predicate is a bare `time_expiry` with no
          price-anchored criterion alongside it — a horizon with nothing
          measurable is not falsifiable) ->
          `auto_fail_reason="no_falsifiable_success_criteria"`.
       c. submitted order size != the `SizingComputed` event recorded at
          `thesis.submit()` time (reuses R-012's own tolerance-comparison
          convention, `policy._dials.PolicyDials.sizing_tolerance_pct` —
          the SAME dial R-012 reads, never a second copy) ->
          `auto_fail_reason="size_mismatch_vs_sizing_computed"`.
     Any short-circuit -> `ReviewCompleted(passed=False, kind=
     "thesis_review")` + a `ReviewArtifact` carrying `auto_fail_reason`
     (empty `exchanges`/`rubric_scores`, `failure_mode=None` — an
     auto-fail is a REAL verdict the deterministic code reached on its
     own, not a boundary failure).
  2. Otherwise: assemble the attack/defense prompt (thesis + market
     snapshot + MAE context per §4.2's read-verb surface), call
     `LLMReviewerPort.review(prompt, timeout_s=dials.reviewer_timeout_s,
     max_output_bytes=dials.reviewer_max_output_bytes)` via
     `_adapters.SubprocessReviewerAdapter.from_dials()`.
  3. Adapter boundary failure (`_port.ReviewTimeout` /
     `_port.ReviewOutputTooLarge`, OR a `json.loads` failure on the
     returned stdout -> `_port.ReviewMalformedOutput` raised HERE, not by
     the adapter) -> caught, NEVER a crash, NEVER an unbounded retry ->
     `ReviewCompleted(passed=False, kind="thesis_review",
     failure_mode="timeout" | "output_too_large" | "malformed_output")`.
  4. Otherwise: `_rubric.score_exchanges(exchanges)` -> deterministic
     `rubric_scores` + `unresolved_attack_count`. `unresolved_attack_count
     >= dials.unresolved_attack_threshold` -> `passed=False` (rubric
     verdict — `failure_mode=None`, this is NOT a boundary failure); else
     `passed=True`.
  5. `_artifacts.assemble(...)` -> `_artifacts.append_review_completed(...)`
     -> return `artifact.model_dump(mode="json")`.

`verify_claim` pipeline (§12.2/§10.4, rides the SAME port):
  - `claim["kind"] == "void_signoff"`: assemble the void-signoff prompt kit
    (thesis + the `InvalidationAttested(kind="structural")` event
    `thesis.void`'s guard-1 already appended — §10.4 guard 2 requires this
    to exist FIRST), call the adapter, score via the SAME `_rubric`
    machinery. On a pass: emit `ReviewCompleted` with `kind="void_signoff"`
    matching `tests/unit/thesis/test_void_verb.py`'s PINNED shape EXACTLY
    (`review_artifact_id`, `passed=True`, referencing `thesis_id`) — this
    is the P3 debt-closure: `thesis.void()`'s reviewer-signoff guard
    becomes reachable end-to-end through a REAL verb call instead of only
    a harness-appended event. On a fail (rubric OR boundary failure): the
    SAME `ReviewCompleted(passed=False, ...)` shape, `kind="void_signoff"`
    — `thesis.void()` stays refused (its own `VoidRefused` guard 2, P2).
  - `claim["kind"] == "trade_settlement"` (P4's §12.2 done-gate use):
    NOT implemented this sprint — raises `NotImplementedError` naming P4,
    distinct from the "still a red-phase stub" NotImplementedError every
    other path in this module raises (a caller can't yet tell these apart
    by message alone; FLAGGED, ASSUMPTIONS round-20, for a typed
    distinction in the dev pass if this matters to a caller).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from ulid import ULID

from tradekit.contracts import EventFilter, Verification
from tradekit.ledger import Ledger, default_ledger
from tradekit.mae import _runtime as _mae_runtime
from tradekit.policy._dials import PolicyDials
from tradekit.review import _artifacts
from tradekit.review._adapters import SubprocessReviewerAdapter
from tradekit.review._port import (
    LLMReviewerPort,
    ReviewMalformedOutput,
    ReviewOutputTooLarge,
    ReviewTimeout,
)
from tradekit.review._rubric import RUBRIC_CATEGORIES, score_exchanges

__all__ = [
    "RUBRIC_CATEGORIES",
    "LLMReviewerPort",
    "ReviewMalformedOutput",
    "ReviewOutputTooLarge",
    "ReviewTimeout",
    "SubprocessReviewerAdapter",
    "run_review",
    "score_exchanges",
    "verify_claim",
]


def _latest_payload(
    ledger: Ledger, thesis_id: str, event_type: str
) -> dict[str, Any] | None:
    """Latest `event_type` payload for `thesis_id`, queried DIRECTLY (not
    via `thesis._machine.latest_payload`, which is scoped to
    `THESIS_EVENT_TYPES` -- the lifecycle-marker whitelist -- and does not
    include `SizingComputed`/`InvalidationAttested`, both of which this
    module needs to read)."""
    matches = [
        event
        for event in ledger.query(EventFilter(types=[event_type]))
        if event.payload.get("thesis_id") == thesis_id
    ]
    return matches[-1].payload if matches else None


def _no_falsifiable_success_criteria(success_criteria: list[dict[str, Any]]) -> bool:
    """Empty, OR every predicate is a bare `time_expiry` with no
    price-anchored criterion alongside it (§12.1 step 1b)."""
    if not success_criteria:
        return True
    kinds = {predicate["kind"] for predicate in success_criteria}
    return kinds == {"time_expiry"}


def _auto_fail_reason(
    contract: dict[str, Any], sizing_payload: dict[str, Any], dials: PolicyDials
) -> str | None:
    """Three auto-fail checks, first match wins (§12.1 step 1, ASSUMPTIONS
    round-20 entries 125/126/129)."""
    ev_usd = Decimal(str(contract["ev_block"]["ev_usd"]))
    if ev_usd <= 0:
        return "missing_numeric_ev"

    if _no_falsifiable_success_criteria(contract["success_criteria"]):
        return "no_falsifiable_success_criteria"

    size_usd = Decimal(str(contract["size_usd"]))
    recommended = Decimal(str(sizing_payload["sizing"]["recommended_size_usd"]))
    deviation = abs(size_usd - recommended) / recommended if recommended != 0 else Decimal("1")
    if deviation > dials.sizing_tolerance_pct:
        return "size_mismatch_vs_sizing_computed"

    return None


def _build_thesis_review_prompt(contract: dict[str, Any]) -> str:
    """Attack/defense prompt kit (§12.1 step 2, §4.2's read-verb surface) —
    a structured JSON block; the reviewer-model-specific prose wrapping is
    an adapter/prompt-template concern, not this pipeline's (`prompts/
    rubric-thesis-v1.md`, DRAFT, ASSUMPTIONS round-20 entry 132)."""
    return json.dumps({"kind": "thesis_review", "thesis_contract": contract})


def _build_void_signoff_prompt(
    contract: dict[str, Any], attestation: dict[str, Any]
) -> str:
    """Void sign-off prompt kit (§12.2/§10.4 guard 2) — thesis + the
    `InvalidationAttested(kind="structural")` payload guard 1 already
    appended."""
    return json.dumps(
        {"kind": "void_signoff", "thesis_contract": contract, "invalidation_attested": attestation}
    )


def _call_reviewer_and_score(
    prompt: str, dials: PolicyDials
) -> tuple[list[dict[str, Any]], dict[str, Any], int, str | None]:
    """Adapter call + strict-JSON-parse + deterministic rubric scoring,
    shared by `run_review`/`verify_claim` (§12.1 steps 2-4). Returns
    `(exchanges, rubric_scores, unresolved_attack_count, failure_mode)` —
    `failure_mode` is `None` on a clean scored round, else one of
    `"timeout"`/`"output_too_large"`/`"malformed_output"` (§12.1 step 3,
    ASSUMPTIONS round-20 entry 128) — NEVER a crash, NEVER a retry."""
    adapter = SubprocessReviewerAdapter.from_dials(dials)
    failure_mode: str | None = None
    exchanges: list[dict[str, Any]] = []
    try:
        stdout = adapter.review(
            prompt,
            timeout_s=dials.reviewer_timeout_s,
            max_output_bytes=dials.reviewer_max_output_bytes,
        )
        try:
            exchanges = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise ReviewMalformedOutput(
                f"review pipeline: reviewer stdout did not strictly JSON-parse: {exc}"
            ) from exc
    except ReviewTimeout:
        failure_mode = "timeout"
    except ReviewOutputTooLarge:
        failure_mode = "output_too_large"
    except ReviewMalformedOutput:
        failure_mode = "malformed_output"

    if failure_mode is not None:
        return [], {}, 0, failure_mode

    scored = score_exchanges(exchanges)
    return (
        exchanges,
        scored["rubric_scores"],
        scored["unresolved_attack_count"],
        None,
    )


def run_review(thesis_id: str) -> dict[str, Any]:
    """`run_review(thesis_id) -> ReviewArtifact` (dict-shaped, §4.2). See
    module docstring for the pinned pipeline algorithm."""
    ledger: Ledger = default_ledger()
    dials = PolicyDials.load()

    drafted = _latest_payload(ledger, thesis_id, "ThesisDrafted")
    if drafted is None:
        raise ValueError(f"no ThesisDrafted event found for thesis_id={thesis_id!r}")
    contract = drafted["contract"]

    sizing_payload = _latest_payload(ledger, thesis_id, "SizingComputed")
    if sizing_payload is None:
        raise ValueError(f"no SizingComputed event found for thesis_id={thesis_id!r}")

    auto_fail_reason = _auto_fail_reason(contract, sizing_payload, dials)
    if auto_fail_reason is not None:
        artifact = _artifacts.assemble(
            thesis_id=thesis_id,
            kind="thesis_review",
            passed=False,
            model=dials.reviewer_binary,
            exchanges=[],
            rubric_scores={},
            unresolved_attack_count=0,
            auto_fail_reason=auto_fail_reason,
            failure_mode=None,
        )
        _artifacts.append_review_completed(artifact, ledger)
        return artifact.model_dump(mode="json")

    prompt = _build_thesis_review_prompt(contract)
    exchanges, rubric_scores, unresolved_attack_count, failure_mode = _call_reviewer_and_score(
        prompt, dials
    )

    passed = failure_mode is None and unresolved_attack_count < dials.unresolved_attack_threshold
    artifact = _artifacts.assemble(
        thesis_id=thesis_id,
        kind="thesis_review",
        passed=passed,
        model=dials.reviewer_binary,
        exchanges=exchanges,
        rubric_scores=rubric_scores,
        unresolved_attack_count=unresolved_attack_count,
        auto_fail_reason=None,
        failure_mode=failure_mode,
    )
    _artifacts.append_review_completed(artifact, ledger)
    return artifact.model_dump(mode="json")


def _verify_void_signoff(claim: dict[str, Any]) -> dict[str, Any]:
    """`claim["kind"] == "void_signoff"` (§12.2/§10.4 guard 2) — see module
    docstring for the pinned algorithm."""
    thesis_id = claim["thesis_id"]
    ledger: Ledger = default_ledger()
    dials = PolicyDials.load()

    drafted = _latest_payload(ledger, thesis_id, "ThesisDrafted")
    if drafted is None:
        raise ValueError(f"no ThesisDrafted event found for thesis_id={thesis_id!r}")
    contract = drafted["contract"]

    attested = _latest_payload(ledger, thesis_id, "InvalidationAttested")
    if attested is None:
        raise ValueError(
            f"no InvalidationAttested event found for thesis_id={thesis_id!r} — §10.4 guard 1 "
            "must exist before a void-signoff verification can be attempted"
        )

    prompt = _build_void_signoff_prompt(contract, attested)
    exchanges, rubric_scores, unresolved_attack_count, failure_mode = _call_reviewer_and_score(
        prompt, dials
    )

    passed = failure_mode is None and unresolved_attack_count < dials.unresolved_attack_threshold
    artifact = _artifacts.assemble(
        thesis_id=thesis_id,
        kind="void_signoff",
        passed=passed,
        model=dials.reviewer_binary,
        exchanges=exchanges,
        rubric_scores=rubric_scores,
        unresolved_attack_count=unresolved_attack_count,
        auto_fail_reason=None,
        failure_mode=failure_mode,
    )
    _artifacts.append_review_completed(artifact, ledger)

    verification = Verification(
        verification_id=str(ULID()),
        claim_kind="void_signoff",
        passed=passed,
        review_artifact_id=artifact.review_artifact_id,
        notes=None,
        ts_utc=_mae_runtime.clock(),
    )
    return verification.model_dump(mode="json")


def verify_claim(claim: dict[str, Any]) -> dict[str, Any]:
    """`verify_claim(claim) -> Verification` (dict-shaped, §4.2/§12.2/
    §10.4). See module docstring for the pinned pipeline algorithm,
    including the EXACT `kind="void_signoff"` `ReviewCompleted` shape this
    closes the P2 void-verb debt against."""
    kind = claim.get("kind")
    if kind == "void_signoff":
        return _verify_void_signoff(claim)
    if kind == "trade_settlement":
        raise NotImplementedError(
            f"review.verify_claim({claim!r}): claim_kind='trade_settlement' is P4's §12.2 "
            "done-gate use, not implemented this sprint"
        )
    raise NotImplementedError(
        f"review.verify_claim({claim!r}): unknown claim_kind {kind!r} — this module handles "
        "'void_signoff' (implemented) and 'trade_settlement' (P4, not yet)"
    )
