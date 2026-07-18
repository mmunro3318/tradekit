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

import sys
import textwrap
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
