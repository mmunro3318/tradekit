"""Multi-timeframe confluence scan (T-MTF-2, docs/design/MTF-SCAN.md "New
verb (one, deep)" section). `tradekit.mae.scan_confluence` (the public verb)
is a thin delegate to `confluence` here — see that function's docstring for
the per-symbol/per-leg pipeline.

Deliberately REUSES `_scanner._evaluate_symbol_timeframe` (raw per-leg filter
evaluation), `_scanner._apply_regime_gate` (tag pruning), and `_scanner`'s
closed-vocabulary sets (`_MACD_ALLOWED`/`_BB_ALLOWED`) rather than forking any
of that logic — `scan_markets`'s single-timeframe contract and tests stay the
sole owner of that code; this module only adds the AND-across-legs
composition and the confluence-specific warning taxonomy.
"""

from __future__ import annotations

from typing import Any, TypedDict

from tradekit.mae import _regime, _runtime, _scanner
from tradekit.mae._data.errors import ProviderError
from tradekit.mae._data.limits import TIMEFRAME_MAX_LOOKBACK_DAYS


class ScanLeg(TypedDict):
    timeframe: str
    filters: dict[str, Any]
    min_tags: int


def confluence(
    asset_class: str,
    legs: list[ScanLeg],
    symbols: list[str],
    regime_gate: bool,
) -> dict[str, Any]:
    """Screen `symbols` for an AND-across-legs multi-timeframe setup
    (MTF-SCAN.md "New verb" semantics). `asset_class` is accepted for
    parity with `scan_markets`'s signature (future audit/trace hook) but is
    not otherwise consulted — no such use is pinned this batch.

    Validation (loud, BEFORE any bar fetch, same TICKET-001 doctrine as
    `_scanner.scan`): an unknown leg timeframe (not a key of
    `TIMEFRAME_MAX_LOOKBACK_DAYS`), two legs sharing the same timeframe
    (unrepresentable — the return shape keys legs by timeframe), or an
    unknown `macd_signal`/`bb_position` filter value raises `ValueError`
    naming the bad value.

    Per symbol, legs are evaluated in order and short-circuit on the first
    failure (AND composition — one failing leg drops the whole symbol, so
    evaluating further legs would only produce warnings nobody asked for):

    - Bars come ONLY from `_runtime.get_closed_bars(symbol, leg.timeframe,
      TIMEFRAME_MAX_LOOKBACK_DAYS[leg.timeframe])` — the per-leg lookback
      IS the retention-honesty pin (never a restated constant). A provider
      error (`_data.errors.ProviderError`) on any leg drops that symbol
      with a warning (`"<symbol>: provider error on leg <tf>
      (<ExceptionName>)"`, MTF-SCAN.md error map) — never an exception out
      of the verb.
    - `_scanner._evaluate_symbol_timeframe` computes that leg's raw
      (pre-regime) `signal_tags`. Insufficient bars on any leg drops the
      symbol entirely with the existing insufficient-bars warning text
      (`_evaluate_symbol_timeframe`'s own `stages[0]["observed"]`) — same
      anti-silent convention as `scan()`.
    - `regime_gate=True` calls `_regime.compute_regime` via the module
      attribute AT MOST ONCE PER SYMBOL (cached across every leg — same
      "150 HMM loads" cache discipline as `_scanner.scan`), pruning that
      leg's raw tags through `_scanner._apply_regime_gate`. A leg whose
      evaluation yields no match skips the `compute_regime` call entirely
      for that leg (mirrors `_scanner.scan`'s `match is not None` guard) —
      its tags are `[]` either way. `regime_gate=False` skips regime
      entirely; the leg's raw tags stand unpruned.
    - `min_tags` is checked AFTER pruning. A leg with fewer than
      `min_tags` surviving tags fails the symbol with a warning
      `"<symbol>: leg <tf> failed (<n>/<min> tags)"` — `n` is the
      post-prune surviving count, 0 for an outright filter failure (CTO
      adjudication, this dispatch: one warning shape covers both an
      outright leg failure and a pruned-below-min leg; no separate
      wording for the two cases).

    A symbol that clears every leg appears in `matches` as `{symbol, legs:
    {timeframe: {signal_tags, indicators}}, confluence: True}` — `indicators`
    is that leg's raw computed indicator values (`_precompute_indicators`'s
    output, minus the audit-only `"_vars"` key)."""
    seen_timeframes: set[str] = set()
    for leg in legs:
        timeframe = leg["timeframe"]
        if timeframe not in TIMEFRAME_MAX_LOOKBACK_DAYS:
            raise ValueError(
                f"scan_confluence: unknown leg timeframe {timeframe!r}; expected one of "
                f"{sorted(TIMEFRAME_MAX_LOOKBACK_DAYS)}"
            )
        if timeframe in seen_timeframes:
            raise ValueError(
                f"scan_confluence: duplicate leg timeframe {timeframe!r}; each leg must use "
                "a distinct timeframe (matches are keyed by timeframe)"
            )
        seen_timeframes.add(timeframe)
        filters = leg["filters"]
        if "macd_signal" in filters and filters["macd_signal"] not in _scanner._MACD_ALLOWED:
            value = filters["macd_signal"]
            raise ValueError(
                f"scan_confluence: unknown macd_signal value {value!r}; expected one of "
                f"{sorted(_scanner._MACD_ALLOWED)}"
            )
        if "bb_position" in filters and filters["bb_position"] not in _scanner._BB_ALLOWED:
            value = filters["bb_position"]
            raise ValueError(
                f"scan_confluence: unknown bb_position value {value!r}; expected one of "
                f"{sorted(_scanner._BB_ALLOWED)}"
            )

    matches: list[dict[str, Any]] = []
    warnings: list[str] = []
    regime_cache: dict[str, dict[str, Any]] = {}

    for symbol in symbols:
        legs_out: dict[str, dict[str, Any]] = {}
        symbol_failed = False

        for leg in legs:
            timeframe = leg["timeframe"]
            lookback_days = TIMEFRAME_MAX_LOOKBACK_DAYS[timeframe]
            try:
                series = _runtime.get_closed_bars(symbol, timeframe, lookback_days)
            except ProviderError as exc:
                warnings.append(
                    f"{symbol}: provider error on leg {timeframe} ({type(exc).__name__})"
                )
                symbol_failed = True
                break

            match, stages, killed_by, values = _scanner._evaluate_symbol_timeframe(
                symbol, timeframe, series.bars, leg["filters"]
            )

            if killed_by == "bars":
                warnings.append(stages[0]["observed"])
                symbol_failed = True
                break

            raw_tags = match["signal_tags"] if match is not None else []

            if match is not None and regime_gate:
                if symbol not in regime_cache:
                    regime_cache[symbol] = _regime.compute_regime(
                        symbol=symbol,
                        lookback_days=_scanner._SCAN_REGIME_LOOKBACK_DAYS,
                        n_states=_scanner._SCAN_REGIME_N_STATES,
                    )
                pruned_tags = _scanner._apply_regime_gate(raw_tags, regime_cache[symbol])
            else:
                pruned_tags = raw_tags

            min_tags = leg["min_tags"]
            if len(pruned_tags) < min_tags:
                warnings.append(
                    f"{symbol}: leg {timeframe} failed ({len(pruned_tags)}/{min_tags} tags)"
                )
                symbol_failed = True
                break

            indicators = {key: value for key, value in values.items() if key != "_vars"}
            legs_out[timeframe] = {"signal_tags": pruned_tags, "indicators": indicators}

        if not symbol_failed:
            matches.append({"symbol": symbol, "legs": legs_out, "confluence": True})

    regime_context = {
        symbol: {"state": regime.get("current_state"), "confidence": regime.get("confidence")}
        for symbol, regime in regime_cache.items()
    }

    return {
        "scan_ts": _runtime.clock().isoformat(),
        "regime_context": regime_context,
        "matches": matches,
        "warnings": warnings,
    }
