"""Subprocess `LLMReviewerPort` adapters (DESIGN §12.1, TD-21, SPRINT P3
batch D) -- Codex CLI default, Gemini alt (both installed on Mike's
machine per the sprint doc). NEVER invoked with a real reviewer binary in
this test suite (batch dispatch pin) -- `tests/unit/review/test_adapters.py`
exercises the subprocess PLUMBING (timeout/cap enforcement, JSON-boundary
error typing) against a tiny stub Python script written to `tmp_path`, not
against `codex`/`gemini` themselves.

Construction (`SubprocessReviewerAdapter.__init__` / `from_dials`) is REAL
-- same "cheap, declarative" status as `PaperBroker.__init__` storing
`account_ref`/`_ledger`: an adapter instance is just its resolved argv +
two numeric caps, no I/O at construction time.

`review()` (SPRINT P4-PAPER batch B, addendum 2 round-22 LOW, "Streaming
subprocess caps") -- STREAMING via `Popen` + a background reader thread +
a RUNNING byte budget, not the prior post-hoc `subprocess.run(...)`
collect-then-check shape: a subprocess that floods stdout past
`max_output_bytes` is KILLED as soon as the running total crosses the cap,
never allowed to keep producing (and, for an adversarial/malfunctioning
process that never exits, never allowed to block the caller past
`timeout_s` either -- the two bounds, byte budget and wall-clock budget,
are enforced by the SAME poll loop, not two independent code paths). The
algorithm (pinned, implemented verbatim below):

  1. `Popen([binary, *args], stdin=PIPE, stdout=PIPE, stderr=DEVNULL)` --
     stderr is discarded (never read, never checked) so a chatty stderr
     writer cannot deadlock the pipe we DO care about; `prompt` is written
     to stdin and stdin is closed immediately after (a script that never
     reads stdin is unaffected -- closing our own write end is always safe).
  2. A daemon reader thread drains `stdout` in `os.read`-sized chunks (each
     call returns as soon as ANY bytes are available -- never blocks
     waiting to fill a fixed buffer) and pushes them onto a `queue.Queue`;
     a `None` sentinel signals EOF (the subprocess closed stdout, normally
     because it exited).
  3. The calling thread polls the queue with SHORT (<=0.5s) timeouts in a
     loop, re-checking elapsed wall-clock time against `timeout_s` on every
     iteration -- this is what makes the timeout enforceable even while the
     subprocess is silently producing nothing (the old `subprocess.run(...,
     timeout=timeout_s)` shape already covered that case; this preserves it
     while ALSO covering the new streaming case) and, symmetrically, makes
     the byte-cap enforceable WHILE the subprocess is still running (the
     old shape could only ever check the cap AFTER the process exited or
     the hard timeout fired -- an infinite-flood process would hang the
     caller for the full `timeout_s` before the oversized-output error ever
     surfaced; this is the bug this batch fixes).
  4. Elapsed time exceeds `timeout_s` -> `proc.kill()` + `proc.wait()` ->
     raise `ReviewTimeout`. Running total exceeds `max_output_bytes` ->
     `proc.kill()` + `proc.wait()` -> raise `ReviewOutputTooLarge` --
     checked immediately after EVERY chunk arrives, so a process that
     writes its entire flood in one giant burst is still caught on the
     FIRST chunk read, and a process that dribbles output slowly past the
     cap is caught on whichever chunk crosses it -- never after collecting
     the whole (unbounded) stream first.
  5. EOF (the `None` sentinel) with the running total still under the cap
     -> reap the process (`proc.wait()`, bounded so a process that closes
     stdout but never actually exits still hits the SAME timeout path) and
     return the concatenated bytes decoded as UTF-8 (untrusted text --
     `_port.LLMReviewerPort.review`'s own docstring: JSON-parsing is the
     CALLER's job, never this method's; `ReviewMalformedOutput` is raised
     by the caller after a failed `json.loads`, never from inside
     `review()`).
"""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import time

from tradekit.policy._dials import PolicyDials
from tradekit.review._port import ReviewMalformedOutput, ReviewOutputTooLarge, ReviewTimeout

_POLL_INTERVAL_S = 0.5
_READ_CHUNK_BYTES = 65536


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
        """Streaming `Popen` + running byte budget -- see the module
        docstring for the pinned algorithm this implements verbatim.
        `timeout_s`/`max_output_bytes` are the CALL-time arguments (mirrors
        the Protocol signature), NOT `self.timeout_s`/`self.max_output_bytes`
        -- those are the from-dials DEFAULTS a caller may override per-call
        (e.g. a shorter timeout for the void-signoff prompt kit)."""
        proc = subprocess.Popen(
            [self.binary, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        if proc.stdin is not None:
            try:
                proc.stdin.write(prompt.encode("utf-8"))
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                # A script that never reads stdin (every stub in this
                # test suite) closes its read end when it exits; writing
                # into a broken pipe is not this adapter's failure mode.
                pass

        chunk_queue: queue.Queue[bytes | None] = queue.Queue()

        def _reader() -> None:
            assert proc.stdout is not None
            try:
                while True:
                    chunk = os.read(proc.stdout.fileno(), _READ_CHUNK_BYTES)
                    if not chunk:
                        break
                    chunk_queue.put(chunk)
            except OSError:
                pass
            finally:
                chunk_queue.put(None)  # EOF sentinel

        reader_thread = threading.Thread(target=_reader, daemon=True)
        reader_thread.start()

        start = time.monotonic()
        chunks: list[bytes] = []
        total_bytes = 0
        while True:
            elapsed = time.monotonic() - start
            remaining = timeout_s - elapsed
            if remaining <= 0:
                proc.kill()
                proc.wait()
                raise ReviewTimeout(
                    f"SubprocessReviewerAdapter(binary={self.binary!r}).review(...): exceeded "
                    f"timeout_s={timeout_s!r}"
                )
            try:
                item = chunk_queue.get(timeout=min(remaining, _POLL_INTERVAL_S))
            except queue.Empty:
                continue

            if item is None:
                break

            chunks.append(item)
            total_bytes += len(item)
            if total_bytes > max_output_bytes:
                # Killed the INSTANT the running total crosses the cap --
                # never after collecting the rest of an unbounded stream.
                proc.kill()
                proc.wait()
                raise ReviewOutputTooLarge(
                    f"SubprocessReviewerAdapter(binary={self.binary!r}).review(...): stdout "
                    f"exceeded max_output_bytes={max_output_bytes!r}"
                )

        try:
            proc.wait(timeout=max(timeout_s - (time.monotonic() - start), 0.01))
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            proc.wait()
            raise ReviewTimeout(
                f"SubprocessReviewerAdapter(binary={self.binary!r}).review(...): exceeded "
                f"timeout_s={timeout_s!r} while the subprocess exited"
            ) from exc

        return b"".join(chunks).decode("utf-8", errors="replace")


__all__ = [
    "ReviewMalformedOutput",
    "ReviewOutputTooLarge",
    "ReviewTimeout",
    "SubprocessReviewerAdapter",
]
