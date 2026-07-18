"""Scanner core (SPRINT-P1C batch C, story 4 `scan_markets`; DESIGN §9.1,
canonical doc §3 `scan_markets`). `tradekit.mae.scan_markets` (the public
verb) stays an unconditional `NotImplementedError` stub in `mae/__init__.py`
THIS batch (red-only, same shape as batch B's `get_regime`/`_regime.
compute_regime` split, ASSUMPTIONS 48) — the dev pass's entire job for the
public verb is a thin `return _scanner.scan(...)` call, so `scan` IS the
verb body under test here.

=== CTO design pins (SPRINT-P1C batch C dispatch; binding on the dev agent
implementing this module's real body) ===

**Universe (this sprint):** `symbols=None` ("full universe scan", canonical
§3's input comment "omit for full universe scan") is explicitly OUT OF
SCOPE this sprint — `scan` raises `ValueError` naming the deferral BEFORE
any bar fetch or filter evaluation. This ONE check is real, implemented
code even in this otherwise-stub module (pure input validation, zero
pipeline dependency — same "validation can be real even in a stub module"
precedent as `_data.macro.get_macro_bars`'s never-raise wrapper existing
independently of `MacroProvider`'s raising). Everything past that check is
`NotImplementedError` this batch.

**Bars:** sourced ONLY via `_runtime.get_closed_bars(symbol, timeframe,
_SCAN_LOOKBACK_DAYS)` — never `_runtime.provider_for` directly (the
lookahead discipline every other verb already follows). `_SCAN_LOOKBACK_DAYS`
(90) is a scanner-internal constant, not an agent-facing input — chosen to
comfortably cover every filter's indicator lookback (MACD's 33-bar warmup is
the longest) plus the ATR-percentile filter's own rolling window, with
headroom.

**Indicators computed per filter present** (never unconditionally — "compute
only the indicators the filters need", sprint doc): `rsi_max`/`rsi_min` ->
`_indicators.momentum.rsi(closes, 14)`; `macd_signal` ->
`_indicators.momentum.macd(closes)`; `bb_position` ->
`_indicators.volatility.bollinger(closes, 20, 2.0)`; `volume_spike` ->
`_indicators.volume.volume_ratio(volumes, 20)`; `atr_percentile_min` ->
`_indicators.volatility.atr(highs, lows, closes, 14)` (percentile computed
over the fetched window's own non-None ATR values, `<=`-rank, same
convention as `_regime._rules_fallback`'s `vol_pctile`).

**Filter semantics** (aligned to canonical §3's input schema where it
speaks; flagged where it does not — see `tests/ASSUMPTIONS.md`'s new P1C
batch C entry for the full flag text, summarized here):
  - `rsi_max`: last non-None RSI(14) <= value.
  - `rsi_min`: last non-None RSI(14) >= value.
  - `macd_signal`: `"bullish_cross" | "bearish_cross"` — canonical §3's OWN
    value strings (NOT the sprint-doc addendum's `"bullish"`/`"bearish"`,
    which contradicts canonical; canonical wins per the "align names with
    canonical, flag if it contradicts" instruction). Semantics PINNED to the
    SIMPLE reading (addendum's explicit fallback when crossing semantics is
    unspecified): `"bullish_cross"` <-> last non-None histogram > 0;
    `"bearish_cross"` <-> last non-None histogram < 0. FLAGGED: canonical's
    own value names ("_cross") textually imply an actual crossover EVENT
    (macd line crossing signal within some lookback), which neither
    canonical §3 nor the addendum ever defines algorithmically (no "N bars
    ago" window is pinned anywhere) — this batch deliberately does NOT
    improvise a crossing-detection window; CTO ratification needed before
    treating either reading as load-bearing.
  - `bb_position`: `"below_lower" | "above_upper" | "inside"` vs the last
    closed bar's close and the last non-None Bollinger band values.
    `"inside"` is an ADDITIVE value beyond canonical §3's two enumerated
    strings (`"below_lower" | "above_upper" | None`) — flagged as a minor,
    unambiguous extension (floor-not-ceiling rule, ASSUMPTIONS 47
    precedent), not a contradiction (the semantics — close strictly between
    the bands — has no ambiguity of its own).
  - `volume_spike`: last non-None `volume_ratio(20)` >= value.
  - `atr_percentile_min`: last non-None ATR(14)'s `<=`-rank percentile
    within the fetched window's non-None ATR values (0-100 scale, matching
    canonical §3's `atr_percentile_min: 40` style) >= value.
  - ALL supplied filters AND together — a symbol/timeframe must clear every
    filter present in the input dict to appear in `matches`.

**Insufficient bars (anti-permissive, never a crash, never a silent
pass-through):** if a filter's required indicator has no non-None value in
the fetched window for a given symbol/timeframe, that symbol/timeframe combo
is SKIPPED entirely (excluded from `matches`) and a warnings entry naming
BOTH the symbol and the reason is appended
(`f"{symbol} {timeframe}: insufficient bars for <filter_name>"`) — never an
exception, never a match built on a fabricated/None value.

**Regime gate** (`regime_gate: bool`):
  - `regime_gate=False` -> ZERO calls to `_regime.compute_regime` (pinned by
    a test asserting a monkeypatched compute_regime records no calls at
    all); every candidate's `signal_tags` pass through unfiltered.
  - `regime_gate=True` -> `_regime.compute_regime` is called via the MODULE
    ATTRIBUTE (`from tradekit.mae import _regime; _regime.compute_regime(
    symbol, _SCAN_REGIME_LOOKBACK_DAYS, _SCAN_REGIME_N_STATES)` — never a
    `from ... import compute_regime` binding, so tests can monkeypatch
    `"tradekit.mae._regime.compute_regime"` by dotted string path) AT MOST
    ONCE PER SYMBOL PER SCAN, cached in a local dict keyed by symbol across
    every timeframe in the scan (pinned by the "2 symbols x 2 timeframes ->
    exactly 2 recorded calls" test — regime correctness itself is story 2's
    job; the scanner only exercises the plumbing/caching contract, per the
    sprint doc: "mock the regime call — this is plumbing").
  - Drop rule: each candidate's filter-derived `signal_tags` are mapped
    through `_TAG_STRATEGY` (below) to an optional strategy family; a tag
    whose mapped family is NOT in that symbol's `recommended_strategies` is
    DROPPED from the match's `signal_tags` (a tag with no mapped family,
    e.g. `"bb_inside"`, always survives — it carries no strategy affiliation
    to gate against). `current_state == "neutral"` or an empty
    `recommended_strategies` (ASSUMPTIONS 53's "no-recommendation" rule)
    therefore drops EVERY strategy-tagged tag for that symbol as a natural
    consequence of intersecting against an empty set — no `"neutral"`
    special-case string needed in this module. A match whose `signal_tags`
    end up empty after the gate is NOT removed from `matches` — filter
    AND-composition alone controls list membership; the regime gate only
    prunes tags. FLAGGED (new this batch, no precedent): whether an
    all-tags-dropped match should be REMOVED from `matches` entirely (vs.
    kept with `signal_tags: []`) is a CTO call this session makes explicit,
    not silently improvised — see ASSUMPTIONS.

**Signal tag / strategy-family mapping** (`_TAG_STRATEGY`, a SESSION-CHOSEN
mapping extrapolating canonical §3's example tags — `"oversold"`,
`"volume_spike"`, `"at_support"` — NOT itself CTO-ratified, same disclaimer
as `_regime._STRATEGY_TAGS`'s own docstring precedent):

    rsi_max hit            -> "oversold"       -> mean_reversion
    rsi_min hit             -> "overbought"     -> mean_reversion
    macd_signal bullish_cross -> "macd_bullish" -> momentum
    macd_signal bearish_cross -> "macd_bearish" -> momentum
    bb_position below_lower -> "at_support"     -> mean_reversion
    bb_position above_upper -> "at_resistance"  -> mean_reversion
    bb_position inside      -> "bb_inside"      -> (no strategy affiliation)
    volume_spike hit        -> "volume_spike"   -> breakout
    atr_percentile_min hit  -> "high_volatility"-> breakout

**Output** (canonical §3 shape + additive house keys, floor-not-ceiling
rule): `scan_ts` (canonical's OWN field name — NOT the dispatch note's
suggested `"as_of"`, which canonical §3 does not use; canonical wins per the
"align names with canonical" instruction, FLAGGED as a naming correction
against the dispatch note, not a contradiction within canonical itself),
`regime_context` (RESTRUCTURED from canonical's flat single-symbol example
`{"state":..., "confidence":...}` into `dict[symbol, {"state", "confidence"}]`
— FLAGGED: canonical's example only ever shows ONE symbol's regime, so it
never actually specifies the multi-symbol shape; a per-symbol keyed dict is
this session's necessary extrapolation, not a schema floor-not-ceiling
addition in the ASSUMPTIONS-47 sense since it changes the VALUE TYPE of an
existing key rather than only adding new keys — CTO ratification needed
before this is load-bearing), `matches` (canonical's per-match keys:
`symbol`, `timeframe`, `price`, `rsi`, `macd_hist`, `atr`,
`atr_pct_of_price`, `volume_ratio`, `signal_tags` — only the keys relevant
to filters actually present need be non-None; house addition `warnings`
(top-level list[str], ASSUMPTIONS 47 precedent) for insufficient-bars
skips.

**Lookahead:** every bar fetch goes through `_runtime.get_closed_bars`
exclusively (never a provider directly) — the same discipline every other
P1C verb follows (ASSUMPTIONS 45).
"""

from __future__ import annotations

from typing import Any

from tradekit import strategies
from tradekit.mae import _regime, _runtime
from tradekit.mae._indicators import momentum, volatility, volume

# Scanner-internal constants (not agent-facing inputs).
_SCAN_LOOKBACK_DAYS = 90
"""Bars fetched per symbol/timeframe via `_runtime.get_closed_bars` — chosen
to comfortably cover every filter's indicator lookback (MACD's 33-bar
warmup is the longest) plus the ATR-percentile filter's own rolling window."""

_SCAN_REGIME_LOOKBACK_DAYS = 90
_SCAN_REGIME_N_STATES = 3
"""Args passed to `_regime.compute_regime` when `regime_gate=True` — match
`get_regime`'s own public defaults (mae/__init__.py); the scanner does not
expose these as agent-facing inputs this sprint."""

# SPRINT P3 batch E (ASSUMPTIONS round-21, sprint-doc "one source of truth"):
# re-derived FROM `tradekit.strategies.TAGS` — the SAME object (import, not a
# copy), not a re-typed literal, so an edit to the shared registry propagates
# here without touching this module again (`tests/unit/test_strategies_
# registry.py`). `tradekit.strategies`'s own module docstring is the mapping's
# canonical home now; see it for the "session-chosen, not CTO-ratified"
# provenance note this dict used to carry directly.
_TAG_STRATEGY: dict[str, str | None] = strategies.TAGS

_BB_POSITION_TAGS: dict[str, str] = {
    "below_lower": "at_support",
    "above_upper": "at_resistance",
    "inside": "bb_inside",
}
"""`bb_position` value -> signal tag, per the module docstring's "Signal tag
/ strategy-family mapping" section."""


class _InsufficientBars(Exception):
    """Raised internally when a present filter's required indicator has no
    non-None value in the fetched window — caught by `scan`, which converts
    it into a `warnings` entry and skips the symbol/timeframe combo (never
    an exception that escapes to the caller)."""


def _last_non_none(values: list[float | None]) -> float | None:
    for v in reversed(values):
        if v is not None:
            return v
    return None


def _evaluate_symbol_timeframe(
    symbol: str, timeframe: str, bars: list[Any], filters: dict[str, Any]
) -> dict[str, Any] | None:
    """Compute only the indicators `filters` needs, apply the AND-composed
    filter checks, and return a fully-populated match dict, or `None` if the
    symbol/timeframe combo fails at least one filter. Raises
    `_InsufficientBars` if a present filter's indicator has no non-None
    value in the fetched window (caller converts this to a warning + skip)."""
    closes = [float(b.close) for b in bars]
    highs = [float(b.high) for b in bars]
    lows = [float(b.low) for b in bars]
    volumes = [float(b.volume) for b in bars]

    candidate: dict[str, Any] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "price": closes[-1] if closes else None,
        "rsi": None,
        "macd_hist": None,
        "atr": None,
        "atr_pct_of_price": None,
        "volume_ratio": None,
        "signal_tags": [],
    }
    tags: list[str] = []

    if "rsi_max" in filters or "rsi_min" in filters:
        rsi_vals = momentum.rsi(closes, 14)
        last_rsi = _last_non_none(rsi_vals)
        if last_rsi is None:
            name = "rsi_max" if "rsi_max" in filters else "rsi_min"
            raise _InsufficientBars(f"{symbol} {timeframe}: insufficient bars for {name}")
        candidate["rsi"] = last_rsi
        if "rsi_max" in filters and last_rsi > filters["rsi_max"]:
            return None
        if "rsi_max" in filters:
            tags.append("oversold")
        if "rsi_min" in filters and last_rsi < filters["rsi_min"]:
            return None
        if "rsi_min" in filters:
            tags.append("overbought")

    if "macd_signal" in filters:
        macd_result = momentum.macd(closes)
        last_hist = _last_non_none(macd_result.histogram)
        if last_hist is None:
            raise _InsufficientBars(f"{symbol} {timeframe}: insufficient bars for macd_signal")
        candidate["macd_hist"] = last_hist
        want = filters["macd_signal"]
        if want == "bullish_cross":
            if not (last_hist > 0.0):
                return None
            tags.append("macd_bullish")
        elif want == "bearish_cross":
            if not (last_hist < 0.0):
                return None
            tags.append("macd_bearish")
        else:
            return None

    if "bb_position" in filters:
        bb_result = volatility.bollinger(closes, 20, 2.0)
        last_upper = _last_non_none(bb_result.upper)
        last_lower = _last_non_none(bb_result.lower)
        if last_upper is None or last_lower is None or not closes:
            raise _InsufficientBars(f"{symbol} {timeframe}: insufficient bars for bb_position")
        last_close = closes[-1]
        if last_close < last_lower:
            position = "below_lower"
        elif last_close > last_upper:
            position = "above_upper"
        else:
            position = "inside"
        if position != filters["bb_position"]:
            return None
        tags.append(_BB_POSITION_TAGS[position])

    if "volume_spike" in filters:
        vr_vals = volume.volume_ratio(volumes, 20)
        last_vr = _last_non_none(vr_vals)
        if last_vr is None:
            raise _InsufficientBars(f"{symbol} {timeframe}: insufficient bars for volume_spike")
        candidate["volume_ratio"] = last_vr
        if last_vr < filters["volume_spike"]:
            return None
        tags.append("volume_spike")

    if "atr_percentile_min" in filters:
        atr_vals = volatility.atr(highs, lows, closes, 14)
        non_none_atr = [v for v in atr_vals if v is not None]
        if not non_none_atr:
            raise _InsufficientBars(
                f"{symbol} {timeframe}: insufficient bars for atr_percentile_min"
            )
        last_atr = non_none_atr[-1]
        pctile = sum(1 for v in non_none_atr if v <= last_atr) / len(non_none_atr) * 100.0
        if pctile < filters["atr_percentile_min"]:
            return None
        candidate["atr"] = last_atr
        if candidate["price"] is not None:
            candidate["atr_pct_of_price"] = last_atr / candidate["price"] * 100.0
        tags.append("high_volatility")

    candidate["signal_tags"] = tags
    return candidate


def _apply_regime_gate(tags: list[str], regime: dict[str, Any]) -> list[str]:
    """Drop each tag whose mapped `_TAG_STRATEGY` family is not in
    `regime`'s `recommended_strategies` — a tag with no mapped family (e.g.
    `"bb_inside"`) always survives."""
    recommended = set(regime.get("recommended_strategies") or [])
    kept: list[str] = []
    for tag in tags:
        family = _TAG_STRATEGY.get(tag)
        if family is None or family in recommended:
            kept.append(tag)
    return kept


def scan(
    asset_class: str,
    timeframes: list[str],
    filters: dict[str, Any],
    symbols: list[str] | None,
    regime_gate: bool,
) -> dict[str, Any]:
    """Screen `symbols` across `timeframes` for setups matching `filters`
    (canonical §3 `scan_markets`). See module docstring for the full
    pipeline, filter semantics, regime-gate caching/drop rule, and output
    shape pins.

    `symbols is None` ("full universe" scan) is deferred past this sprint
    and raises `ValueError` before any bar fetch. Otherwise: for every
    symbol/timeframe pair, bars come ONLY from `_runtime.get_closed_bars`;
    filters AND-compose; `regime_gate=True` calls `_regime.compute_regime`
    at most once per symbol (cached), pruning each match's `signal_tags`
    against that symbol's `recommended_strategies` (see module docstring).
    """
    if symbols is None:
        raise ValueError(
            "scan_markets: symbols=None ('full universe' scan) is deferred past "
            "SPRINT-P1C — pass an explicit symbols list "
            "(docs/handoff/SPRINT-P1C-regime-scanner-sizing.md story 4)"
        )

    matches: list[dict[str, Any]] = []
    warnings: list[str] = []
    regime_context: dict[str, Any] = {}
    regime_cache: dict[str, dict[str, Any]] = {}

    for symbol in symbols:
        for timeframe in timeframes:
            series = _runtime.get_closed_bars(symbol, timeframe, _SCAN_LOOKBACK_DAYS)
            try:
                match = _evaluate_symbol_timeframe(symbol, timeframe, series.bars, filters)
            except _InsufficientBars as exc:
                warnings.append(str(exc))
                continue
            if match is None:
                continue

            if regime_gate:
                if symbol not in regime_cache:
                    regime_cache[symbol] = _regime.compute_regime(
                        symbol, _SCAN_REGIME_LOOKBACK_DAYS, _SCAN_REGIME_N_STATES
                    )
                regime = regime_cache[symbol]
                regime_context[symbol] = {
                    "state": regime.get("current_state"),
                    "confidence": regime.get("confidence"),
                }
                match["signal_tags"] = _apply_regime_gate(match["signal_tags"], regime)

            matches.append(match)

    return {
        "scan_ts": _runtime.clock().isoformat(),
        "regime_context": regime_context,
        "matches": matches,
        "warnings": warnings,
    }
