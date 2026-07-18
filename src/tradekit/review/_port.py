"""`LLMReviewerPort` -- the reviewer-model-neutral protocol (DESIGN §12.1,
TD-21, SPRINT P3 batch D). Mirrors `broker._port.BrokerPort`'s shape: one
Protocol, adapters behind it (`_adapters.py`), a conformance discipline
(no dedicated `tests/contract/` suite this batch -- FLAGGED, ASSUMPTIONS
round-20 -- but the same "adapters are interchangeable behind one call
signature" intent).

`review(prompt, *, timeout_s, max_output_bytes) -> str` is the ENTIRE
surface: one blocking call, untrusted stdout back (§12.1/"Traps": "treat
stdout as untrusted data (parse JSON strictly; a chatty model must not
crash the pipeline)"). Everything reviewer-specific (binary path, CLI
flags, JSON-vs-text prompting convention) is the adapter's job; the port
itself carries no reviewer identity.

The three typed refusal/failure exceptions below are the subprocess-
boundary vocabulary `review.__init__`'s pipeline catches to produce a
`ReviewCompleted(passed=False, failure_mode=...)` artifact -- NEVER an
uncaught crash, NEVER an unbounded retry (sprint doc addendum, binding).
Canonical home here (not `_adapters.py`) for the same identity-match
reason as `broker._port`'s exceptions: `review.__init__`'s pipeline and
every adapter module must import the SAME class objects, or
`except ReviewTimeout` in the pipeline would never catch a real adapter's
raise.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class ReviewTimeout(Exception):
    """The adapter subprocess exceeded `timeout_s` (§12.1 "Traps": hard
    timeout dial, default 120s per DESIGN's addendum). The pipeline catches
    this and emits `ReviewCompleted(passed=False, failure_mode="timeout")`
    -- never a crash, never a retry loop."""


class ReviewOutputTooLarge(Exception):
    """The adapter subprocess's stdout exceeded `max_output_bytes` (default
    1MB, DESIGN addendum) -- caught by the same failure_mode path
    (`"output_too_large"`)."""


class ReviewMalformedOutput(Exception):
    """The adapter's stdout did not strictly JSON-parse against the
    expected exchange schema (§12.1: "structured JSON exchange" ; "a
    chatty model must not crash the pipeline") -- caught by the same
    failure_mode path (`"malformed_output"`)."""


@runtime_checkable
class LLMReviewerPort(Protocol):
    def review(self, prompt: str, *, timeout_s: int, max_output_bytes: int) -> str:
        """Blocking call to a reviewer-model subprocess (Codex/Gemini CLI,
        §12.1). Returns raw stdout (untrusted text -- the CALLER, not this
        method, is responsible for JSON-parsing it). Raises `ReviewTimeout`/
        `ReviewOutputTooLarge` when the dial bounds are exceeded; does NOT
        raise on malformed JSON (that is a parse-time failure the caller
        detects after this returns, per `ReviewMalformedOutput`'s own
        docstring: the adapter's job ends at "here is what the subprocess
        printed")."""
        ...


__all__ = [
    "LLMReviewerPort",
    "ReviewMalformedOutput",
    "ReviewOutputTooLarge",
    "ReviewTimeout",
]
