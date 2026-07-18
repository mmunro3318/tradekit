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

from typing import Any

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


def run_review(thesis_id: str) -> dict[str, Any]:
    """`run_review(thesis_id) -> ReviewArtifact` (dict-shaped, §4.2). STUB
    — see module docstring for the pinned pipeline algorithm."""
    raise NotImplementedError(
        f"review.run_review({thesis_id!r}): SPRINT P3 batch D dev pass lands this "
        "(§12.1 auto-fail short-circuits + attack/defense pipeline)"
    )


def verify_claim(claim: dict[str, Any]) -> dict[str, Any]:
    """`verify_claim(claim) -> Verification` (dict-shaped, §4.2/§12.2/
    §10.4). STUB — see module docstring for the pinned pipeline algorithm,
    including the EXACT `kind="void_signoff"` `ReviewCompleted` shape this
    closes the P2 void-verb debt against."""
    raise NotImplementedError(
        f"review.verify_claim({claim!r}): SPRINT P3 batch D dev pass lands this "
        "(§12.2/§10.4 verification pipeline)"
    )
