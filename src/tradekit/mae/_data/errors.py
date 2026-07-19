"""Typed provider errors (SPRINT-P1A stories 4-5).

Deliberately a flat, small hierarchy — every _data provider raises ONE of
these, never a bare httpx exception or a silently-swallowed failure. Primary
OHLCV data NEVER degrades silently (sprint doc trap): a provider that cannot
answer must raise, not return a stale/partial BarSeries.
"""

from __future__ import annotations


class ProviderError(Exception):
    """Base for every typed error raised out of tradekit.mae._data.*."""


class ProviderRangeError(ProviderError):
    """Requested [start, end) exceeds what the provider can return.

    Kraken OHLC retains only its most recent ~720-bar window per interval
    (CTO-verified live 2026-07-19) — there is no deeper data to page to, so
    this is a hard retention wall, not a caller-side pagination job. Alpaca
    instead pages internally via `next_page_token` (T-PAGE-1); there this
    error means its internal page-cap guard tripped (a runaway token), not
    a normal multi-page fetch."""


class ProviderUnavailable(ProviderError):
    """The provider could not answer (HTTP 5xx/timeout after retries
    exhausted, or any other unrecoverable failure). Primary market data
    raises this rather than returning `stale=True` — that flag is reserved
    for macro/supplementary providers only (sprint doc trap)."""


class ProviderRequestError(ProviderError):
    """The provider rejected the request itself (HTTP 4xx): bad params,
    unknown symbol, auth failure. Never retried — a 4xx will not get better
    on the next attempt (sprint doc story 5 pin)."""
