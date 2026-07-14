"""tests/unit/mae_data/test_ratelimit.py — story 5: per-provider token
bucket + retry.

No real sleeps anywhere: TokenBucket takes an injected fake `clock`
(`Callable[[], float]`, monotonic seconds) and is non-blocking — tests
advance the fake clock explicitly between calls instead of waiting.
`call_with_retry` takes an injected `sleeper` (`Callable[[float], None]`)
instead of calling `time.sleep`; one test monkeypatches `time.sleep` to raise
if it is ever invoked, to pin that "no real sleep" is structural, not
incidental.

`call_with_retry`'s `fn` returns plain `httpx.Response` objects built
in-process (no real HTTP, no respx route needed) — retry/backoff logic is
provider-agnostic and shouldn't need network mocking to test.
"""

from __future__ import annotations

import time

import httpx
import pytest

from tradekit.mae._data.errors import ProviderRequestError, ProviderUnavailable
from tradekit.mae._data.ratelimit import PROVIDER_RATES, TokenBucket, bucket_for, call_with_retry


class FakeClock:
    """Monotonic fake clock: advances only when the test tells it to."""

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def __call__(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


def _counting_sleeper():
    calls: list[float] = []

    def _sleep(seconds: float) -> None:
        calls.append(seconds)

    return _sleep, calls


def _canned_fn(responses: list[httpx.Response]):
    """A fn() that returns `responses` in order; tracks how many times it
    was actually called (that count IS the retry pin)."""
    state = {"n": 0}

    def _fn() -> httpx.Response:
        resp = responses[state["n"]]
        state["n"] += 1
        return resp

    return _fn, state


# ---------------------------------------------------------------------------
# TokenBucket
# ---------------------------------------------------------------------------


def test_bucket_allows_burst_up_to_capacity_then_blocks() -> None:
    clock = FakeClock(start=0.0)
    bucket = TokenBucket(rate_per_sec=1.0, capacity=3.0, clock=clock)

    assert bucket.try_acquire() is True, "token 1 of 3 burst capacity"
    assert bucket.try_acquire() is True, "token 2 of 3 burst capacity"
    assert bucket.try_acquire() is True, "token 3 of 3 burst capacity"
    assert bucket.try_acquire() is False, (
        "capacity exhausted with zero elapsed time — must NOT grant a 4th token"
    )


def test_bucket_refills_only_after_fake_time_elapses() -> None:
    clock = FakeClock(start=0.0)
    bucket = TokenBucket(rate_per_sec=1.0, capacity=1.0, clock=clock)

    assert bucket.try_acquire() is True, "the single burst token"
    assert bucket.try_acquire() is False, "no time has passed -> no refill yet"

    clock.advance(0.5)
    assert bucket.try_acquire() is False, (
        "at 1 token/sec, 0.5s elapsed is not enough for a full token"
    )

    clock.advance(0.5)  # total elapsed = 1.0s = exactly 1 token at 1/s
    assert bucket.try_acquire() is True, "1.0s elapsed at 1 token/sec must refill exactly one token"
    assert bucket.try_acquire() is False, "that refilled token was just spent"


def test_bucket_for_kraken_and_coingecko_have_different_pinned_rates() -> None:
    clock = FakeClock()
    kraken = bucket_for("kraken", clock=clock)
    coingecko = bucket_for("coingecko", clock=clock)

    assert PROVIDER_RATES["kraken"][0] == pytest.approx(1.0), "Kraken: ~1 req/s polite"
    assert PROVIDER_RATES["coingecko"][0] == pytest.approx(100 / 60), "CoinGecko: 100/min"
    assert kraken.try_acquire() is True
    assert coingecko.try_acquire() is True
    # Kraken's burst is 1: a second immediate acquire must fail.
    assert kraken.try_acquire() is False, "kraken bucket capacity is 1 — no double burst"
    # CoinGecko's burst (5) means several immediate acquires still succeed.
    assert coingecko.try_acquire() is True, "coingecko bucket has burst capacity > 1"


def test_bucket_for_unknown_provider_dies_loudly() -> None:
    with pytest.raises(ValueError, match="provider"):
        bucket_for("robinhood", clock=FakeClock())


# ---------------------------------------------------------------------------
# call_with_retry
# ---------------------------------------------------------------------------


def test_retries_5xx_then_succeeds_exactly_three_calls() -> None:
    sleeper, sleeps = _counting_sleeper()
    fn, state = _canned_fn(
        [httpx.Response(500), httpx.Response(500), httpx.Response(200, json={"ok": True})]
    )

    result = call_with_retry(fn, max_attempts=3, sleeper=sleeper)

    assert result.status_code == 200
    assert state["n"] == 3, f"expected exactly 3 calls (2 failures + 1 success), got {state['n']}"
    assert len(sleeps) == 2, "must back off between the two failed attempts, not before/after"


def test_4xx_never_retries_one_call_typed_error() -> None:
    sleeper, sleeps = _counting_sleeper()
    fn, state = _canned_fn([httpx.Response(400, text="bad request")])

    with pytest.raises(ProviderRequestError):
        call_with_retry(fn, max_attempts=3, sleeper=sleeper)

    assert state["n"] == 1, (
        f"a 4xx must never be retried (it will not get better) — got {state['n']} calls"
    )
    assert sleeps == [], "no backoff sleep should happen for a non-retryable 4xx"


def test_exhausted_5xx_retries_raise_provider_unavailable() -> None:
    sleeper, _sleeps = _counting_sleeper()
    fn, state = _canned_fn([httpx.Response(500), httpx.Response(503), httpx.Response(500)])

    with pytest.raises(ProviderUnavailable):
        call_with_retry(fn, max_attempts=3, sleeper=sleeper)

    assert state["n"] == 3, "must attempt exactly max_attempts times before giving up"


def test_retry_never_calls_real_time_sleep(monkeypatch) -> None:
    """Structural pin: call_with_retry must route ALL backoff through the
    injected `sleeper`, never the stdlib time.sleep — this monkeypatches
    time.sleep to explode if invoked."""

    def _boom(_seconds: float) -> None:
        raise AssertionError("call_with_retry must never call time.sleep() directly")

    monkeypatch.setattr(time, "sleep", _boom)
    sleeper, _sleeps = _counting_sleeper()
    fn, _state = _canned_fn([httpx.Response(500), httpx.Response(200)])

    call_with_retry(fn, max_attempts=3, sleeper=sleeper)  # must not raise via the patched sleep
