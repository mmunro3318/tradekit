"""Subprocess `LLMReviewerPort` adapters (DESIGN §12.1, TD-21, SPRINT P3
batch D) -- Codex CLI default, Gemini alt (both installed on Mike's
machine per the sprint doc). NEVER invoked with a real reviewer binary in
this test suite (batch dispatch pin) -- `tests/unit/review/test_adapters.py`
exercises the subprocess PLUMBING (timeout/cap enforcement, JSON-boundary
error typing) against a tiny stub Python script written to `tmp_path`, not
against `codex`/`gemini` themselves.

Construction (`SubprocessReviewerAdapter.__init__` / `from_dials`) is REAL
this batch -- same "cheap, declarative" status as `PaperBroker.__init__`
storing `account_ref`/`_ledger`: an adapter instance is just its resolved
argv + two numeric caps, no I/O at construction time. `review()` itself --
the actual `subprocess.run(...)` call, timeout enforcement, output-size
capping, and typed-exception translation -- is a `NotImplementedError`
stub THIS batch (TDD red phase); the algorithm it must implement is pinned
in its own docstring below so the dev pass has no design decisions left to
make.
"""

from __future__ import annotations

import subprocess

from tradekit.policy._dials import PolicyDials
from tradekit.review._port import ReviewMalformedOutput, ReviewOutputTooLarge, ReviewTimeout


class SubprocessReviewerAdapter:
    """One reviewer CLI, resolved from dials (`reviewer_binary`/
    `reviewer_args`/`reviewer_timeout_s`/`reviewer_max_output_bytes`,
    `policy._dials.PolicyDials`). Implements `review._port.LLMReviewerPort`
    structurally."""

    def __init__(
        self,
        binary: str,
        args: tuple[str, ...] = (),
        *,
        timeout_s: int = 120,
        max_output_bytes: int = 1_048_576,
    ) -> None:
        self.binary = binary
        self.args = tuple(args)
        self.timeout_s = timeout_s
        self.max_output_bytes = max_output_bytes

    @classmethod
    def from_dials(cls, dials: PolicyDials | None = None) -> SubprocessReviewerAdapter:
        """Resolve an adapter straight off `config.toml`'s reviewer_* dials
        (§12.1's "adapter binaries resolved from dials" pin) -- the
        constructor every real `review.run_review`/`verify_claim` call site
        uses; tests construct `SubprocessReviewerAdapter(...)` directly with
        a stub-script `binary` instead."""
        d = dials if dials is not None else PolicyDials.load()
        return cls(
            d.reviewer_binary,
            d.reviewer_args,
            timeout_s=d.reviewer_timeout_s,
            max_output_bytes=d.reviewer_max_output_bytes,
        )

    def review(self, prompt: str, *, timeout_s: int, max_output_bytes: int) -> str:
        """Pinned target algorithm (dev pass lands this; STUB this batch):

          1. `subprocess.run([self.binary, *self.args], input=prompt,
             capture_output=True, text=True, timeout=timeout_s)` --
             `timeout_s`/`max_output_bytes` are the CALL-time arguments
             (mirrors the Protocol signature), NOT `self.timeout_s`/
             `self.max_output_bytes` -- those are the from-dials DEFAULTS a
             caller may override per-call (e.g. a shorter timeout for the
             void-signoff prompt kit).
          2. A `subprocess.TimeoutExpired` -> re-raise as `review._port.
             ReviewTimeout` (never let the raw stdlib exception cross the
             adapter boundary -- the pipeline only ever catches this
             module's three typed exceptions).
          3. `len(result.stdout.encode("utf-8")) > max_output_bytes` ->
             raise `review._port.ReviewOutputTooLarge` BEFORE returning --
             an oversized-but-truncated read is never silently accepted as
             if it were the complete exchange.
          4. Otherwise return `result.stdout` verbatim (untrusted text --
             `_port.LLMReviewerPort.review`'s own docstring: JSON-parsing
             is the CALLER's job, not this method's; `ReviewMalformedOutput`
             is raised by the caller after a failed `json.loads`, never
             from inside `review()`)."""
        try:
            result = subprocess.run(
                [self.binary, *self.args],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise ReviewTimeout(
                f"SubprocessReviewerAdapter(binary={self.binary!r}).review(...): exceeded "
                f"timeout_s={timeout_s!r}"
            ) from exc

        if len(result.stdout.encode("utf-8")) > max_output_bytes:
            raise ReviewOutputTooLarge(
                f"SubprocessReviewerAdapter(binary={self.binary!r}).review(...): stdout "
                f"exceeded max_output_bytes={max_output_bytes!r}"
            )
        return result.stdout


__all__ = [
    "ReviewMalformedOutput",
    "ReviewOutputTooLarge",
    "ReviewTimeout",
    "SubprocessReviewerAdapter",
]
