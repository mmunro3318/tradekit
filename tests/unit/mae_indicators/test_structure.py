"""tests/unit/mae_indicators/test_structure.py — SPRINT P1B story 5:
swing_points, qfl_bases (tradekit.mae._indicators.structure).

TEST-PATH EXCEPTION (tests/ASSUMPTIONS.md, extends entry 39): this module
imports `tradekit.mae._indicators.structure` directly — no public verb
wires `_indicators` in yet (P1C+).

Golden vectors (tests/golden/indicators/{swing_points,qfl_bases}.json) are
NOT computed by running these stubs (they raise NotImplementedError) and
NOT from a third-party TA library. They come from an independent,
from-spec reference implementation written directly against the formulas
pinned in docs/handoff/SPRINT-P1B-indicators.md (main body + addendum) —
see scratchpad script `gen_golden_p1b45.py` referenced in each JSON's
"source" field.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from tradekit.mae._indicators.structure import qfl_bases, swing_points

GOLDEN_DIR = Path(__file__).resolve().parent.parent.parent / "golden" / "indicators"


def _load(name: str) -> dict:
    return json.loads((GOLDEN_DIR / f"{name}.json").read_text())


def _assert_aligned(actual: list, expected: list) -> None:
    assert len(actual) == len(expected)
    for i, (a, e) in enumerate(zip(actual, expected, strict=True)):
        if e is None:
            assert a is None, f"index {i}: expected None, got {a}"
        else:
            assert a == pytest.approx(e, rel=1e-9, abs=1e-12), f"index {i}: {a} != {e}"


def _random_walk(n: int = 120, seed: int = 55) -> tuple[list[float], list[float], list[float]]:
    rng = random.Random(seed)
    closes = [100.0]
    for _ in range(n - 1):
        closes.append(max(1.0, closes[-1] + rng.uniform(-2.5, 2.5)))
    highs = [c + rng.uniform(0.05, 1.6) for c in closes]
    lows = [c - rng.uniform(0.05, 1.6) for c in closes]
    return highs, lows, closes


# ---------------------------------------------------------------------------
# swing_points
# ---------------------------------------------------------------------------


def test_swing_points_golden_vector() -> None:
    g = _load("swing_points")
    sh, sl = swing_points(g["input"]["highs"], g["input"]["lows"], k=2)
    _assert_aligned(sh, g["expected"]["swing_highs"])
    _assert_aligned(sl, g["expected"]["swing_lows"])

    # Hand check 1 (a swing HIGH pivot, index 2): highs = [.., 10,12,15,12,
    # 10, ..] around index2 (values at 0,1,2,3,4 = 10,12,15,12,10). 15 is
    # strictly greater than all 4 neighbors (10,12,12,10) -> pivot,
    # level=15.0.
    assert sh[2] == pytest.approx(15.0, abs=1e-9)

    # Hand check 2 (a swing LOW pivot, index 7): lows around index7
    # (indices 5,6,7,8,9 = 7,5,3,5,7). 3 is strictly less than all 4
    # neighbors (7,5,5,7) -> pivot, level=3.0.
    assert sl[7] == pytest.approx(3.0, abs=1e-9)

    # Hand check 3 (edge exclusion): index 0 is within k=2 of the series
    # start and can NEVER be a pivot regardless of its value.
    assert sh[0] is None and sl[0] is None


def test_swing_points_edge_indices_always_none() -> None:
    """Indices within k of either end can never be pivots (addendum), even
    though the golden 15-bar series's raw values at those edges are
    otherwise unremarkable-looking."""
    g = _load("swing_points")
    sh, sl = swing_points(g["input"]["highs"], g["input"]["lows"], k=2)
    n = len(g["input"]["highs"])
    for i in (0, 1, n - 2, n - 1):
        assert sh[i] is None
        assert sl[i] is None


def test_swing_points_short_series_all_none() -> None:
    """A series shorter than 2k+1 bars has no possible pivots — every
    index is within k of one end or the other (addendum edge exclusion)."""
    highs = [10.0, 12.0, 15.0, 11.0]  # n=4 < 2*2+1=5
    lows = [5.0, 4.0, 2.0, 6.0]
    sh, sl = swing_points(highs, lows, k=2)
    assert len(sh) == len(sl) == 4
    assert all(v is None for v in sh)
    assert all(v is None for v in sl)


def test_swing_points_monotonic_series_no_swing_lows_or_highs() -> None:
    """A strictly monotonically increasing series has no interior index
    that is BOTH a local max (for swing highs) or local min (for swing
    lows) against all 2k neighbors -- every neighbor comparison fails in
    exactly one direction, so neither output ever fires."""
    highs = [float(i) for i in range(20)]  # strictly increasing
    lows = [float(i) - 0.5 for i in range(20)]
    sh, sl = swing_points(highs, lows, k=2)
    assert all(v is None for v in sh)
    assert all(v is None for v in sl)


def test_swing_points_tie_disqualifies_pivot() -> None:
    """A tied neighbor fails the STRICT inequality and disqualifies the
    candidate index -- e.g. highs = [.., 10, 10, 10, ..] around a
    would-be pivot has no strict winner."""
    highs = [1.0, 2.0, 10.0, 10.0, 10.0, 2.0, 1.0]
    lows = [9.0, 8.0, 1.0, 1.0, 1.0, 8.0, 9.0]
    sh, sl = swing_points(highs, lows, k=2)
    # index 2, 3, 4 are candidate pivots but none is strictly greater/less
    # than its tied neighbor(s).
    for i in (2, 3, 4):
        assert sh[i] is None
        assert sl[i] is None


def test_swing_points_properties_random_walk() -> None:
    highs, lows, _ = _random_walk()
    sh, sl = swing_points(highs, lows, k=2)
    n = len(highs)
    assert len(sh) == len(sl) == n
    for i in range(n):
        if i < 2 or i > n - 1 - 2:
            assert sh[i] is None
            assert sl[i] is None
    # swing_highs non-None only at valid pivot indices k..n-1-k
    for i, v in enumerate(sh):
        if v is not None:
            assert 2 <= i <= n - 1 - 2
    for i, v in enumerate(sl):
        if v is not None:
            assert 2 <= i <= n - 1 - 2


# ---------------------------------------------------------------------------
# qfl_bases
# ---------------------------------------------------------------------------


def test_qfl_bases_golden_vector() -> None:
    g = _load("qfl_bases")
    out = qfl_bases(g["input"]["lows"], g["input"]["closes"], k=2)
    _assert_aligned(out, g["expected"]["qfl_bases"])

    # Hand check 1 (confirmation lag): the first swing low is at pivot
    # index 2 (level 6.0 -- lows around index2: 10,9,6,9,11, strictly
    # least). Confirmation index = pivot + k = 2 + 2 = 4. So indices 0-3
    # have NO confirmed base yet (None), and index 4 is the first index
    # reporting 6.0.
    for i in range(4):
        assert out[i] is None
    assert out[4] == pytest.approx(6.0, abs=1e-9)

    # Hand check 2 (active base reported across multiple bars): indices
    # 5 and 6 both still report the same base (closes stay >= 6.0 --
    # close5=11.5, close6=9.5).
    assert out[5] == pytest.approx(6.0, abs=1e-9)
    assert out[6] == pytest.approx(6.0, abs=1e-9)

    # Hand check 3 (crack on the SAME bar it happens, boundary pin):
    # close7=5.5 < 6.0 -> the base is cracked; qfl_bases[7] is ALREADY
    # None on this bar, not the about-to-be-cracked 6.0 value.
    assert out[7] is None


def test_qfl_bases_later_base_replaces_cracked_one() -> None:
    """The second swing low (pivot index 9, level 7.0) confirms at index
    9+2=11 and replaces the cracked first base -- indices 8-10 stay None
    (base1 cracked, base2 not yet confirmed), 11-12 report 7.0, and index
    13 (close=6.5 < 7.0) cracks it again."""
    g = _load("qfl_bases")
    out = qfl_bases(g["input"]["lows"], g["input"]["closes"], k=2)
    for i in (8, 9, 10):
        assert out[i] is None
    assert out[11] == pytest.approx(7.0, abs=1e-9)
    assert out[12] == pytest.approx(7.0, abs=1e-9)
    assert out[13] is None


def test_qfl_bases_short_series_all_none() -> None:
    lows = [10.0, 9.0, 6.0, 9.0]  # n=4 < 2*2+1=5, no possible pivot
    closes = [10.0, 9.5, 6.5, 9.0]
    out = qfl_bases(lows, closes, k=2)
    assert out == [None, None, None, None]


def test_swing_points_and_qfl_reject_degenerate_k() -> None:
    """P1B review LOW-2: k < 1 would make the strict-inequality pivot test
    vacuously true at EVERY index (all() over an empty neighbor range),
    silently flagging everything as both a swing high and a swing low —
    guard with a loud ValueError instead."""
    with pytest.raises(ValueError, match="k must be >= 1"):
        swing_points([1.0, 2.0, 3.0], [0.5, 1.5, 2.5], k=0)
    with pytest.raises(ValueError, match="k must be >= 1"):
        qfl_bases([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], k=0)


def test_qfl_bases_properties_random_walk() -> None:
    """Every reported qfl level equals some EARLIER low value (a level
    can only come from a confirmed swing-low pivot strictly before the
    reporting index, since confirmation needs k >= 1 bars after the
    pivot), and close[i] >= level at every reporting index (a cracked
    base is never reported -- crack evaluates before reporting)."""
    _, lows, closes = _random_walk()
    out = qfl_bases(lows, closes, k=2)
    assert len(out) == len(lows)
    for i, level in enumerate(out):
        if level is None:
            continue
        assert closes[i] >= level
        assert any(
            lows[j] == pytest.approx(level, rel=1e-9) for j in range(i)
        ), f"index {i}: reported level {level} matches no earlier low"
