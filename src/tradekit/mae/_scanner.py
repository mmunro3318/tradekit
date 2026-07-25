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
from tradekit.mae import _regime, _runtime, _scan_trace
from tradekit.mae._indicators import momentum, volatility, volume
from tradekit.mae._scan_trace import ScanAuditMode
from tradekit.mae._vocab import BBPosition, MacdSignal

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

# SPRINT-TICKET-001 P1/P2: closed vocabularies for the two enum-valued
# filters, keyed off `_vocab`'s StrEnums (single source of truth) — `scan()`
# validates an incoming filter value against these sets, loud, before any
# bar fetch (P2); never a silent per-candidate drop (TICKET-001 §2a).
_MACD_ALLOWED: set[str] = {member.value for member in MacdSignal}
_BB_ALLOWED: set[str] = {member.value for member in BBPosition}

# SCAN-AUDIT-LOG: closed vocabulary for the `audit` param (design doc B4,
# same TICKET-001 convention as the two sets above).
_AUDIT_ALLOWED: set[str] = {"off", "on", "exhaustive"}


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


def _precompute_indicators(
    filters: dict[str, Any],
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    symbol: str,
    timeframe: str,
) -> dict[str, Any]:
    """Compute only the indicators `filters` needs, in the pinned stage
    order (P3: rsi, macd_signal, bb_position, volume_spike,
    atr_percentile). Raises `_InsufficientBars` on the FIRST present filter
    whose indicator has no non-None value in the fetched window — this
    becomes the single `"bars"` attrition stage (P3), never a per-filter
    named failure."""
    values: dict[str, Any] = {}

    if "rsi_max" in filters or "rsi_min" in filters:
        last_rsi = _last_non_none(momentum.rsi(closes, 14))
        if last_rsi is None:
            name = "rsi_max" if "rsi_max" in filters else "rsi_min"
            raise _InsufficientBars(f"{symbol} {timeframe}: insufficient bars for {name}")
        values["rsi"] = last_rsi

    if "macd_signal" in filters:
        last_hist = _last_non_none(momentum.macd(closes).histogram)
        if last_hist is None:
            raise _InsufficientBars(f"{symbol} {timeframe}: insufficient bars for macd_signal")
        values["macd_hist"] = last_hist

    if "bb_position" in filters:
        bb_result = volatility.bollinger(closes, 20, 2.0)
        last_upper = _last_non_none(bb_result.upper)
        last_lower = _last_non_none(bb_result.lower)
        if last_upper is None or last_lower is None or not closes:
            raise _InsufficientBars(f"{symbol} {timeframe}: insufficient bars for bb_position")
        last_close = closes[-1]
        if last_close < last_lower:
            values["bb_position_value"] = "below_lower"
        elif last_close > last_upper:
            values["bb_position_value"] = "above_upper"
        else:
            values["bb_position_value"] = "inside"

    if "volume_spike" in filters:
        last_vr = _last_non_none(volume.volume_ratio(volumes, 20))
        if last_vr is None:
            raise _InsufficientBars(f"{symbol} {timeframe}: insufficient bars for volume_spike")
        values["volume_ratio"] = last_vr

    if "atr_percentile_min" in filters:
        non_none_atr = [v for v in volatility.atr(highs, lows, closes, 14) if v is not None]
        if not non_none_atr:
            raise _InsufficientBars(
                f"{symbol} {timeframe}: insufficient bars for atr_percentile_min"
            )
        last_atr = non_none_atr[-1]
        values["atr"] = last_atr
        values["atr_pctile"] = (
            sum(1 for v in non_none_atr if v <= last_atr) / len(non_none_atr) * 100.0
        )

    return values


def _evaluate_symbol_timeframe(
    symbol: str,
    timeframe: str,
    bars: list[Any],
    filters: dict[str, Any],
    exhaustive: bool = False,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None, dict[str, Any]]:
    """Compute only the indicators `filters` needs, apply the AND-composed
    filter checks in the pinned stage order, and return
    `(match_or_None, stages, killed_by, values)`. `stages` is the P3
    attrition trail for this (symbol, timeframe). `killed_by` is the first
    failing stage's name, or `None` if every present filter passed. `values`
    is the raw `_precompute_indicators` output (SCAN-AUDIT-LOG: handed to
    the audit trace so a logged number can never drift from the number a
    gate actually compared — never recomputed there).

    `exhaustive=False` (default): stops at the first failure, same as
    before this batch — `stages` holds no entries past the killer.
    `exhaustive=True` (SCAN-AUDIT-LOG audit="exhaustive" only): keeps
    evaluating every remaining PRESENT filter after the first failure.
    `killed_by`/the returned match are governed ONLY by the first failure
    either way (design doc B3: "kill semantics unchanged") — stages
    evaluated after the kill carry `"post_kill": True`, trace-only, never
    affecting `killed_by` or the match."""
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

    try:
        values = _precompute_indicators(filters, closes, highs, lows, volumes, symbol, timeframe)
    except _InsufficientBars as exc:
        stages: list[dict[str, Any]] = [{"name": "bars", "outcome": "fail", "observed": str(exc)}]
        return None, stages, "bars", {}

    stages = [{"name": "bars", "outcome": "pass", "observed": f"{len(bars)} bars"}]
    tags: list[str] = []
    killed_by: str | None = None

    def _check_rsi() -> tuple[bool, str, list[str]]:
        last_rsi = values["rsi"]
        candidate["rsi"] = last_rsi
        observed = f"rsi={last_rsi}"
        if "rsi_max" in filters and last_rsi > filters["rsi_max"]:
            return False, observed, []
        if "rsi_min" in filters and last_rsi < filters["rsi_min"]:
            return False, observed, []
        # Restore pre-refactor dual-tag semantics: BOTH tags fire when both
        # bounds are set and both pass (review round item 1).
        rsi_tags: list[str] = []
        if "rsi_max" in filters:
            rsi_tags.append("oversold")
        if "rsi_min" in filters:
            rsi_tags.append("overbought")
        return True, observed, rsi_tags

    def _check_macd() -> tuple[bool, str, str | None]:
        last_hist = values["macd_hist"]
        candidate["macd_hist"] = last_hist
        observed = f"hist={last_hist}"
        want = filters["macd_signal"]
        if want == MacdSignal.BULLISH_CROSS:
            ok, tag = last_hist > 0.0, "macd_bullish"
        elif want == MacdSignal.BEARISH_CROSS:
            ok, tag = last_hist < 0.0, "macd_bearish"
        else:
            # Unreachable: scan() validates macd_signal against _MACD_ALLOWED
            # before any candidate is evaluated (P2).
            raise AssertionError(f"unreachable: unvalidated macd_signal value {want!r}")
        return ok, observed, tag if ok else None

    def _check_bb() -> tuple[bool, str, str | None]:
        position = values["bb_position_value"]
        observed = f"position={position}"
        ok = position == filters["bb_position"]
        return ok, observed, _BB_POSITION_TAGS[position] if ok else None

    def _check_volume() -> tuple[bool, str, str | None]:
        last_vr = values["volume_ratio"]
        candidate["volume_ratio"] = last_vr
        observed = f"vr={last_vr}"
        ok = last_vr >= filters["volume_spike"]
        return ok, observed, "volume_spike" if ok else None

    def _check_atr() -> tuple[bool, str, str | None]:
        last_atr = values["atr"]
        pctile = values["atr_pctile"]
        observed = f"pctile={pctile}"
        ok = pctile >= filters["atr_percentile_min"]
        if ok:
            candidate["atr"] = last_atr
            if candidate["price"] is not None:
                candidate["atr_pct_of_price"] = last_atr / candidate["price"] * 100.0
        return ok, observed, "high_volatility" if ok else None

    checks: list[tuple[str, Any]] = []
    if "rsi_max" in filters or "rsi_min" in filters:
        checks.append(("rsi", _check_rsi))
    if "macd_signal" in filters:
        checks.append(("macd_signal", _check_macd))
    if "bb_position" in filters:
        checks.append(("bb_position", _check_bb))
    if "volume_spike" in filters:
        checks.append(("volume_spike", _check_volume))
    if "atr_percentile_min" in filters:
        checks.append(("atr_percentile", _check_atr))

    for name, check_fn in checks:
        if killed_by is not None and not exhaustive:
            break
        ok, observed, tag = check_fn()
        stage: dict[str, Any] = {
            "name": name,
            "outcome": "pass" if ok else "fail",
            "observed": observed,
        }
        if killed_by is not None:
            stage["post_kill"] = True
        stages.append(stage)
        if ok:
            if killed_by is None and tag is not None:
                if isinstance(tag, list):
                    tags.extend(tag)
                else:
                    tags.append(tag)
        elif killed_by is None:
            killed_by = name

    if killed_by is not None:
        return None, stages, killed_by, values

    candidate["signal_tags"] = tags
    return candidate, stages, None, values


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
    audit: ScanAuditMode = "off",
) -> dict[str, Any]:
    """Screen `symbols` across `timeframes` for setups matching `filters`
    (canonical §3 `scan_markets`). See module docstring for the full
    pipeline, filter semantics, regime-gate caching/drop rule, and output
    shape pins.

    `audit` (SCAN-AUDIT-LOG, docs/design/SCAN-AUDIT-LOG.md): `"off"`
    (default) is today's behavior, byte-identical, zero disk writes.
    `"on"` writes a full-lifecycle trace under `_scan_trace._OUTPUT_ROOT`
    without changing scan semantics. `"exhaustive"` additionally evaluates
    every PRESENT filter for every candidate that passed the `bars` stage,
    even after the first failure — kill semantics (`killed_by`, `matches`)
    stay identical to `"on"`; post-kill verdicts are trace-only. An unknown
    `audit` value raises `ValueError` naming it (TICKET-001 convention).

    `symbols is None` ("full universe" scan) is deferred past this sprint
    and raises `ValueError` before any bar fetch. `macd_signal`/`bb_position`
    filter VALUES are validated against their closed vocabularies before any
    bar fetch too (P2/ASSUMPTIONS 162) — an unknown value raises `ValueError`
    naming the bad value and the allowed set, never a silent empty `matches`.
    Otherwise: for every symbol/timeframe pair, bars come ONLY from
    `_runtime.get_closed_bars`; filters AND-compose; `regime_gate=True` calls
    `_regime.compute_regime` at most once per symbol (cached), pruning each
    match's `signal_tags` against that symbol's `recommended_strategies`
    (see module docstring). The result additionally carries `"attrition"`
    (P3): one entry per (symbol, timeframe) in input order, naming every
    stage evaluated and which one (if any) killed the candidate.

    A regime-gate-killed candidate REMAINS in `matches` with empty
    `signal_tags` (pre-existing CTO call, preserved) — `attrition.killed_by`
    is the AUTHORITY for survivor counts; callers must never infer
    survivorship from `len(matches)` (ASSUMPTIONS 163c).
    """
    if symbols is None:
        raise ValueError(
            "scan_markets: symbols=None ('full universe' scan) is deferred past "
            "SPRINT-P1C — pass an explicit symbols list "
            "(docs/handoff/SPRINT-P1C-regime-scanner-sizing.md story 4)"
        )

    if audit not in _AUDIT_ALLOWED:
        raise ValueError(
            f"scan_markets: unknown audit value {audit!r}; expected one of "
            f"{sorted(_AUDIT_ALLOWED)}"
        )

    if "macd_signal" in filters and filters["macd_signal"] not in _MACD_ALLOWED:
        value = filters["macd_signal"]
        raise ValueError(
            f"scan_markets: unknown macd_signal value {value!r}; expected one of "
            f"{sorted(_MACD_ALLOWED)}"
        )
    if "bb_position" in filters and filters["bb_position"] not in _BB_ALLOWED:
        value = filters["bb_position"]
        raise ValueError(
            f"scan_markets: unknown bb_position value {value!r}; expected one of "
            f"{sorted(_BB_ALLOWED)}"
        )

    matches: list[dict[str, Any]] = []
    warnings: list[str] = []
    regime_context: dict[str, Any] = {}
    regime_cache: dict[str, dict[str, Any]] = {}
    attrition: list[dict[str, Any]] = []

    # SCAN-AUDIT-LOG: timestamp captured ONCE, from `_runtime.clock()` only,
    # and reused for both `scan_ts` and the trace's file names/header — a
    # single scan never straddles two clock reads.
    ts = _runtime.clock()
    trace = (
        _scan_trace.ScanTrace(ts, audit, asset_class, timeframes, filters, symbols, regime_gate)
        if audit != "off"
        else None
    )

    for symbol in symbols:
        for timeframe in timeframes:
            series = _runtime.get_closed_bars(symbol, timeframe, _SCAN_LOOKBACK_DAYS)
            match, stages, killed_by, values = _evaluate_symbol_timeframe(
                symbol, timeframe, series.bars, filters, exhaustive=(audit == "exhaustive")
            )
            if killed_by == "bars":
                warnings.append(stages[0]["observed"])

            if match is not None and regime_gate:
                if symbol not in regime_cache:
                    regime_cache[symbol] = _regime.compute_regime(
                        symbol, _SCAN_REGIME_LOOKBACK_DAYS, _SCAN_REGIME_N_STATES
                    )
                regime = regime_cache[symbol]
                regime_context[symbol] = {
                    "state": regime.get("current_state"),
                    "confidence": regime.get("confidence"),
                }
                before_tags = match["signal_tags"]
                after_tags = _apply_regime_gate(before_tags, regime)
                match["signal_tags"] = after_tags
                regime_observed = f"state={regime.get('current_state')}"
                if before_tags and not after_tags:
                    stages.append(
                        {"name": "regime_gate", "outcome": "fail", "observed": regime_observed}
                    )
                    killed_by = "regime_gate"
                else:
                    stages.append(
                        {"name": "regime_gate", "outcome": "pass", "observed": regime_observed}
                    )

            if match is not None:
                matches.append(match)

            if trace is not None:
                trace.record_symbol_timeframe(
                    symbol, timeframe, series.bars, series.source, _SCAN_LOOKBACK_DAYS,
                    values, stages, filters,
                )

            attrition.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "stages": stages,
                    "killed_by": killed_by,
                }
            )

    result = {
        # Reverts to pre-refactor semantics (review round item 4): scan_ts
        # is read HERE, at result assembly (end of scan), not the
        # start-captured `ts` — which remains reserved for audit trace
        # naming/header only.
        "scan_ts": _runtime.clock().isoformat(),
        "regime_context": regime_context,
        "matches": matches,
        "warnings": warnings,
        "attrition": attrition,
    }

    if trace is not None:
        trace.write({"attrition": attrition, "matches": matches, "warnings": warnings})

    return result
