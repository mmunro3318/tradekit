"""`review._adapters.SubprocessReviewerAdapter` (DESIGN §12.1, TD-21,
SPRINT P3 batch D) -- construction (`__init__`/`from_dials`) is REAL this
batch (declarative, no I/O); `review()` itself (the actual subprocess
spawn + timeout/cap enforcement) is a `NotImplementedError` stub -- every
`.review(...)` test below is red for that reason, describing REAL target
behavior (same discipline as the rest of this sprint's red-phase files).

Subprocess boundary (sprint doc addendum pin): "ONE test with a real
subprocess stub executable -- a tiny python script in tmp_path echoing
canned JSON -- validating the adapter's timeout/caps plumbing; everything
else uses in-process fakes." `sys.executable` running a tiny script
written to `tmp_path` IS a real subprocess -- never `codex`/`gemini`
themselves (those are never invoked anywhere in this test suite).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from pathlib import Path

from tradekit.policy._dials import PolicyDials
from tradekit.review._adapters import SubprocessReviewerAdapter
from tradekit.review._port import ReviewOutputTooLarge, ReviewTimeout


def _write_script(tmp_path: Path, name: str, body: str) -> Path:
    script = tmp_path / name
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return script


def test_from_dials_resolves_binary_args_and_caps_from_policydials() -> None:
    dials = PolicyDials(
        reviewer_binary="codex",
        reviewer_args=("--json",),
        reviewer_timeout_s=45,
        reviewer_max_output_bytes=2048,
    )
    adapter = SubprocessReviewerAdapter.from_dials(dials)
    assert adapter.binary == "codex"
    assert adapter.args == ("--json",)
    assert adapter.timeout_s == 45
    assert adapter.max_output_bytes == 2048


def test_real_subprocess_stub_executable_returns_canned_stdout(tmp_path) -> None:
    script = _write_script(
        tmp_path,
        "echo_canned.py",
        """\
        import sys
        sys.stdout.write('[{"attack": "a", "category": "ev_arithmetic", '
                          '"severity": 1, "defense": "d", "resolved": true}]')
        """,
    )
    adapter = SubprocessReviewerAdapter(
        sys.executable, (str(script),), timeout_s=5, max_output_bytes=4096
    )

    stdout = adapter.review("attack this thesis", timeout_s=5, max_output_bytes=4096)

    assert "ev_arithmetic" in stdout


def test_real_subprocess_stub_executable_enforces_timeout(tmp_path) -> None:
    script = _write_script(
        tmp_path,
        "sleep_forever.py",
        """\
        import time
        time.sleep(30)
        print("too late")
        """,
    )
    adapter = SubprocessReviewerAdapter(sys.executable, (str(script),))

    try:
        adapter.review("attack this thesis", timeout_s=1, max_output_bytes=4096)
        raised = False
    except ReviewTimeout:
        raised = True
    assert raised, "a subprocess exceeding timeout_s must raise review._port.ReviewTimeout"


def test_real_subprocess_stub_executable_enforces_max_output_bytes(tmp_path) -> None:
    script = _write_script(
        tmp_path,
        "print_huge.py",
        """\
        import sys
        sys.stdout.write("x" * 5000)
        """,
    )
    adapter = SubprocessReviewerAdapter(sys.executable, (str(script),))

    try:
        adapter.review("attack this thesis", timeout_s=5, max_output_bytes=100)
        raised = False
    except ReviewOutputTooLarge:
        raised = True
    assert raised, (
        "a subprocess whose stdout exceeds max_output_bytes must raise "
        "review._port.ReviewOutputTooLarge -- never a silent truncation"
    )


def _process_alive(pid: int) -> bool:
    """Portable "is this pid still running" check (no psutil dependency).
    Windows: `tasklist` filtered by PID; POSIX: `os.kill(pid, 0)` (raises if
    the process is gone)."""
    if sys.platform == "win32":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        return str(pid) in out
    import os

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_real_subprocess_stub_executable_kills_a_flooding_process_early(tmp_path) -> None:
    """SPRINT P4-PAPER batch B, addendum 2 round-22 LOW ("Streaming
    subprocess caps"): a FLOOD stub -- prints far more than the cap IN A
    LOOP, never exiting on its own -- proves the adapter enforces
    `max_output_bytes` via an INCREMENTAL Popen read with a running byte
    budget, not the prior post-hoc `subprocess.run(...)` collect-then-check
    shape (which could only ever discover the overage AFTER the whole
    unbounded stream had been collected, or after the full timeout_s had
    elapsed -- whichever came first). Three assertions distinguish "killed
    early" from "just timed out waiting the full budget":

      (i) `ReviewOutputTooLarge` is raised (not `ReviewTimeout`);
      (ii) elapsed wall-clock time is well under `timeout_s` (30s) --
           proving the kill happened as soon as the running total crossed
           the cap, not because the timeout also happened to fire;
      (iii) the flooding process is actually DEAD afterward (not merely
            un-awaited) -- proving this is a real `proc.kill()`, not a
            silently-abandoned subprocess still writing into a pipe nobody
            reads anymore.
    """
    pid_file = tmp_path / "flood.pid"
    script = _write_script(
        tmp_path,
        "flood.py",
        f"""\
        import os, sys
        with open(r"{pid_file}", "w") as f:
            f.write(str(os.getpid()))
        while True:
            sys.stdout.write("x" * 4096)
            sys.stdout.flush()
        """,
    )
    adapter = SubprocessReviewerAdapter(sys.executable, (str(script),))

    start = time.monotonic()
    try:
        adapter.review("attack this thesis", timeout_s=30, max_output_bytes=200)
        raised = False
    except ReviewOutputTooLarge:
        raised = True
    elapsed = time.monotonic() - start

    assert raised, (
        "a flooding subprocess must raise review._port.ReviewOutputTooLarge -- never hang "
        "until the caller gives up, and never a silent truncation"
    )
    assert elapsed < 10, (
        f"elapsed={elapsed!r}s must be well under timeout_s=30 -- proving an early kill on "
        "byte-budget breach, not a fall-through to the timeout path"
    )

    # The stub writes its own pid before flooding -- give the OS a brief
    # moment to finish reaping (proc.wait() already ran inside review()),
    # then confirm the process is actually gone, not merely un-awaited.
    deadline = time.monotonic() + 5
    pid = int(pid_file.read_text().strip()) if pid_file.exists() else None
    still_alive = pid is not None and _process_alive(pid)
    while still_alive and time.monotonic() < deadline:
        time.sleep(0.1)
        still_alive = _process_alive(pid)  # type: ignore[arg-type]
    assert not still_alive, (
        f"the flooding subprocess (pid={pid}) must be killed, not left running after "
        "ReviewOutputTooLarge is raised"
    )
