"""Per-provider token bucket + retry (DESIGN §9.1, sprint story 5).

Two small, separately testable pieces:

1. ``TokenBucket`` — a pure, non-blocking rate limiter. It takes an injected
   ``clock: Callable[[], float]`` (monotonic seconds) rather than sleeping
   itself (TD-17 "no real clock", extended here to "no real sleeps" — tests
   advance the fake clock explicitly between calls). ``try_acquire`` reports
   whether a token was available *right now*; it never blocks.
2. ``call_with_retry`` — tenacity-style backoff for a callable that returns an
   ``httpx.Response``. Retries on 5xx and ``httpx.TimeoutException`` (L6 —
   the timeout is caught INSIDE this function) up to ``max_attempts``; 4xx
   NEVER retries (a 4xx will not get better — sprint doc pin). No real
   `time.sleep` — the caller supplies a ``sleeper`` callable so tests can
   assert on backoff durations without waiting for them.

``acquire_blocking`` is the provider-facing glue (H2 review fix): it waits on
a bucket via the provider's injected ``sleeper``, using the bucket's own
computed ``seconds_until_token()`` — the wait is calculated, never spun.

``PROVIDER_RATES`` pins the sprint doc's per-provider numbers so `bucket_for`
is the one place they're defined (kraken ~1 req/s polite; coingecko 100/min;
alpaca 200/min).
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from tradekit.mae._data.errors import ProviderRequestError, ProviderUnavailable

# provider name -> (tokens per second, bucket capacity / burst size)
PROVIDER_RATES: dict[str, tuple[float, float]] = {
    "kraken": (1.0, 1.0),
    "coingecko": (100.0 / 60.0, 5.0),
    "alpaca": (200.0 / 60.0, 10.0),
}

# Float refill math never lands on an exact integer token count (accumulated
# rounding error from repeated elapsed*rate additions) — this epsilon lets
# "exactly 1.0s at 1 token/sec" still grant a token instead of coming up a
# hair short.
_EPSILON = 1e-9

# Backoff schedule for call_with_retry: 0.5s, 1s, 2s, 4s, ... capped at 8s.
_BACKOFF_BASE_S = 0.5
_BACKOFF_CAP_S = 8.0


class TokenBucket:
    """Non-blocking token bucket. `clock()` returns monotonic seconds; the
    bucket refills continuously at `rate_per_sec`, capped at `capacity`."""

    def __init__(self, rate_per_sec: float, capacity: float, *, clock: Callable[[], float]) -> None:
        self._rate = rate_per_sec
        self._capacity = capacity
        self._clock = clock
        self._tokens = capacity  # start full — burst up to capacity is allowed immediately
        self._last_check = clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = now - self._last_check
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_check = now

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """Consume `tokens` if available right now; return False (and
        consume nothing) otherwise. Never blocks, never sleeps."""
        self._refill()
        if self._tokens + _EPSILON >= tokens:
            self._tokens -= tokens
            return True
        return False

    def seconds_until_token(self, tokens: float = 1.0) -> float:
        """Seconds until `tokens` will be available at the current fill rate;
        0.0 if available right now. Callers wait THIS computed amount via
        their injected sleeper instead of spinning on try_acquire (H2)."""
        self._refill()
        deficit = tokens - self._tokens
        if deficit <= _EPSILON:
            return 0.0
        return deficit / self._rate


def bucket_for(provider: str, *, clock: Callable[[], float]) -> TokenBucket:
    """TokenBucket pre-configured from PROVIDER_RATES; raises ValueError for
    an unknown provider (same "never silently free" spirit as costs.py)."""
    try:
        rate, capacity = PROVIDER_RATES[provider]
    except KeyError:
        raise ValueError(
            f"unknown provider {provider!r}; no rate configured in PROVIDER_RATES"
        ) from None
    return TokenBucket(rate, capacity, clock=clock)


def acquire_blocking(bucket: TokenBucket, sleeper: Callable[[float], None]) -> None:
    """Wait (via `sleeper`, never `time.sleep`) until `bucket` grants a
    token. The wait duration comes from the bucket's own
    `seconds_until_token()` — computed, not spun (H2 review fix)."""
    while not bucket.try_acquire():
        wait = bucket.seconds_until_token()
        # A zero wait means the token became available between the two calls;
        # still yield a minimal positive wait so a fake-clock sleeper always
        # observes progress and a no-op sleeper cannot hot-spin unbounded.
        sleeper(wait if wait > 0 else _EPSILON)


def call_with_retry(
    fn: Callable[[], httpx.Response],
    *,
    max_attempts: int = 3,
    sleeper: Callable[[float], None] = lambda _seconds: None,
) -> httpx.Response:
    """Call `fn`, retrying on 5xx responses AND `httpx.TimeoutException`
    (L6 — caught here, retried like a 5xx) with backoff (via `sleeper`,
    never `time.sleep`) up to `max_attempts` total tries.

    Raises ProviderRequestError immediately on any 4xx (no retry — it will
    not get better). Raises ProviderUnavailable if attempts are exhausted
    still failing on 5xx/timeout.
    """
    last_failure: str | None = None
    for attempt in range(max_attempts):
        try:
            response = fn()
        except httpx.TimeoutException as exc:
            last_failure = f"timeout ({exc})"
        else:
            status = response.status_code
            if status < 400:
                return response
            if 400 <= status < 500:
                raise ProviderRequestError(f"HTTP {status}: {response.text}")
            # 5xx (or anything else >= 500): retryable.
            last_failure = f"HTTP {status}"
        if attempt == max_attempts - 1:
            break
        backoff = min(_BACKOFF_CAP_S, _BACKOFF_BASE_S * 2**attempt)
        sleeper(backoff)
    raise ProviderUnavailable(
        f"exhausted {max_attempts} attempts, last failure: {last_failure}"
    )
