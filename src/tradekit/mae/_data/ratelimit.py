"""Per-provider token bucket + retry (DESIGN §9.1, sprint story 5).

Two small, separately testable pieces:

1. ``TokenBucket`` — a pure, non-blocking rate limiter. It takes an injected
   ``clock: Callable[[], float]`` (monotonic seconds) rather than sleeping
   itself (TD-17 "no real clock", extended here to "no real sleeps" — tests
   advance the fake clock explicitly between calls). ``try_acquire`` reports
   whether a token was available *right now*; it never blocks.
2. ``call_with_retry`` — tenacity-style backoff for a callable that returns an
   ``httpx.Response``. Retries on 5xx/timeout up to ``max_attempts``; 4xx
   NEVER retries (a 4xx will not get better — sprint doc pin). No real
   `time.sleep` — the caller supplies a ``sleeper`` callable so tests can
   assert on backoff durations without waiting for them.

``PROVIDER_RATES`` pins the sprint doc's per-provider numbers so `bucket_for`
is the one place they're defined (kraken ~1 req/s polite; coingecko 100/min;
alpaca 200/min).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

import httpx

T = TypeVar("T")

# provider name -> (tokens per second, bucket capacity / burst size)
PROVIDER_RATES: dict[str, tuple[float, float]] = {
    "kraken": (1.0, 1.0),
    "coingecko": (100.0 / 60.0, 5.0),
    "alpaca": (200.0 / 60.0, 10.0),
}


class TokenBucket:
    """Non-blocking token bucket. `clock()` returns monotonic seconds; the
    bucket refills continuously at `rate_per_sec`, capped at `capacity`."""

    def __init__(self, rate_per_sec: float, capacity: float, *, clock: Callable[[], float]) -> None:
        raise NotImplementedError("P1A story 5 — docs/handoff/SPRINT-P1A-data-layer.md")

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """Consume `tokens` if available right now; return False (and
        consume nothing) otherwise. Never blocks, never sleeps."""
        raise NotImplementedError("P1A story 5 — docs/handoff/SPRINT-P1A-data-layer.md")


def bucket_for(provider: str, *, clock: Callable[[], float]) -> TokenBucket:
    """TokenBucket pre-configured from PROVIDER_RATES; raises ValueError for
    an unknown provider (same "never silently free" spirit as costs.py)."""
    raise NotImplementedError("P1A story 5 — docs/handoff/SPRINT-P1A-data-layer.md")


def call_with_retry(
    fn: Callable[[], httpx.Response],
    *,
    max_attempts: int = 3,
    sleeper: Callable[[float], None] = lambda _seconds: None,
) -> httpx.Response:
    """Call `fn`, retrying on 5xx/timeout responses with backoff (via
    `sleeper`, never `time.sleep`) up to `max_attempts` total tries.

    Raises ProviderRequestError immediately on any 4xx (no retry — it will
    not get better). Raises ProviderUnavailable if attempts are exhausted
    still failing on 5xx/timeout.
    """
    raise NotImplementedError("P1A story 5 — docs/handoff/SPRINT-P1A-data-layer.md")
