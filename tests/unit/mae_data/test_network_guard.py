"""Proof that the conftest.py zero-network guard (P1A DoD) is real.

Not a story deliverable by itself — a sanity pin. Every other test in
tests/unit/mae_data/ asserts "zero network calls" or "exactly N calls"; those
assertions are only meaningful if an unmocked httpx call actually fails
instead of silently reaching the real internet. This test proves that.
"""

from __future__ import annotations

import httpx
import pytest


def test_unmocked_http_call_is_blocked_not_silently_allowed() -> None:
    """No test in this module (or fixture) mocks this URL — the autouse
    `_no_unmocked_network` fixture in tests/conftest.py must still be active
    and must raise rather than let this reach the network."""
    with pytest.raises(Exception) as exc_info:
        httpx.get("https://example.invalid/definitely-not-mocked")
    assert type(exc_info.value).__name__ == "AllMockedAssertionError", (
        f"expected respx's AllMockedAssertionError (conftest network guard active); "
        f"got {type(exc_info.value).__name__}: {exc_info.value!r}. If this test fails, "
        "the whole suite's 'zero network' claim is unverified, not just this one."
    )
