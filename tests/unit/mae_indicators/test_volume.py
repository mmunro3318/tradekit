"""tests/unit/mae_indicators/test_volume.py — SPRINT P1B story 4:
vwap, obv, volume_ratio (tradekit.mae._indicators.volume).

TEST-PATH EXCEPTION (tests/ASSUMPTIONS.md, extends entry 39): this module
imports `tradekit.mae._indicators.volume` directly — no public verb wires
`_indicators` in yet (P1C+).

Golden vectors (tests/golden/indicators/{vwap,obv,volume_ratio}.json) are
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
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from tradekit.contracts import Bar
from tradekit.mae._indicators.volume import obv, volume_ratio, vwap

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


def _bars_from_json(raw: list[dict]) -> list[Bar]:
    return [
        Bar(
            ts_open=datetime.fromisoformat(b["ts_open"]),
            open=Decimal(b["open"]),
            high=Decimal(b["high"]),
            low=Decimal(b["low"]),
            close=Decimal(b["close"]),
            volume=Decimal(b["volume"]),
        )
        for b in raw
    ]


def _bar(ts: datetime, h: str, lo: str, c: str, v: str) -> Bar:
    return Bar(
        ts_open=ts,
        open=Decimal(lo),
        high=Decimal(h),
        low=Decimal(lo),
        close=Decimal(c),
        volume=Decimal(v),
    )


def _random_walk_volumes(n: int = 120, seed: int = 43) -> tuple[list[float], list[float]]:
    rng = random.Random(seed)
    closes = [100.0]
    for _ in range(n - 1):
        closes.append(max(1.0, closes[-1] + rng.uniform(-2.5, 2.5)))
    volumes = [rng.uniform(1.0, 500.0) for _ in range(n)]
    return closes, volumes


# ---------------------------------------------------------------------------
# vwap
# ---------------------------------------------------------------------------


def test_vwap_golden_vector_spans_utc_midnight() -> None:
    g = _load("vwap")
    bars = _bars_from_json(g["input"]["bars"])
    out = vwap(bars)
    _assert_aligned(out, g["expected"]["vwap"])

    # Hand check 1 (seed bar, index 0, no prior accumulation): tp0 =
    # (H+L+C)/3 = (101+99+100)/3 = 300/3 = 100.0; cum_tv=100.0*10=1000.0,
    # cum_v=10.0 -> vwap0 = 1000.0/10.0 = 100.0.
    assert out[0] == pytest.approx(100.0, abs=1e-9)

    # Hand check 2 (mid-session, index 3, cumulative across 4 bars in the
    # 2026-07-15 session): tp1=(102+100+101)/3=101.0, tp2=(103+101+102)/3=
    # 102.0 (volume 0, contributes nothing to cum_tv or cum_v), tp3=
    # (104+102+103)/3=103.0. cum_tv = 100*10 + 101*20 + 102*0 + 103*15 =
    # 1000 + 2020 + 0 + 1545 = 4565.0; cum_v = 10+20+0+15 = 45.0.
    # vwap3 = 4565.0/45.0 = 101.44444444444444...
    assert out[3] == pytest.approx(4565.0 / 45.0, rel=1e-9)

    # Hand check 3 (just after the UTC-midnight session reset, index 4):
    # bar4 is the FIRST bar of the 2026-07-16 session and has volume=0, so
    # cumulative volume so far in this brand-new session is 0.0 -> None
    # (the zero-cumulative-volume rule), even though tp4=(90+88+89)/3=89.0
    # is a perfectly well-defined typical price.
    assert out[4] is None


def test_vwap_zero_volume_bar_mid_session_does_not_crash() -> None:
    """Index 2 has volume=0 but is NOT the first bar of its session (cum
    volume from bars 0-1 is already 20.0), so vwap[2] is defined and equal
    to vwap[1] (the zero-volume bar contributes 0 to both cum_tv and
    cum_v)."""
    g = _load("vwap")
    bars = _bars_from_json(g["input"]["bars"])
    out = vwap(bars)
    assert out[2] == pytest.approx(out[1], rel=1e-9)


def test_vwap_session_resets_at_utc_day_boundary() -> None:
    """Bar 5 (first NONZERO-volume bar of the 2026-07-16 session) must NOT
    carry over any accumulation from the 2026-07-15 session: vwap5 = tp5
    exactly (single-bar session-so-far), tp5=(91+89+90)/3=90.0."""
    g = _load("vwap")
    bars = _bars_from_json(g["input"]["bars"])
    out = vwap(bars)
    assert out[5] == pytest.approx(90.0, abs=1e-9)


def test_vwap_single_bar() -> None:
    b = _bar(datetime(2026, 7, 15, 12, 0, tzinfo=UTC), "10.0", "8.0", "9.0", "5.0")
    out = vwap([b])
    # tp = (10+8+9)/3 = 9.0; cum_tv=9*5=45; cum_v=5 -> 45/5=9.0
    assert out == [pytest.approx(9.0, abs=1e-9)]


def test_vwap_all_zero_volume_session_all_none() -> None:
    bars = [
        _bar(datetime(2026, 7, 15, h, 0, tzinfo=UTC), "10.0", "8.0", "9.0", "0.0")
        for h in range(3)
    ]
    out = vwap(bars)
    assert out == [None, None, None]


def test_vwap_naive_datetime_rejected_at_bar_construction() -> None:
    """Bar.ts_open is pydantic AwareDatetime (contracts/_marketdata.py) —
    a naive datetime is a validation error at Bar construction, before
    vwap ever sees it (deliberate, per the task brief)."""
    with pytest.raises(ValidationError):
        Bar(
            ts_open=datetime(2026, 7, 15, 12, 0),  # naive, no tzinfo
            open=Decimal("9.0"),
            high=Decimal("10.0"),
            low=Decimal("8.0"),
            close=Decimal("9.0"),
            volume=Decimal("5.0"),
        )


def test_vwap_properties_random_walk() -> None:
    """A single-session random walk (all bars same UTC day): output length
    matches input, and every position is non-None once volume is
    positive (addendum: vwap lookback first non-None index = 0)."""
    rng = random.Random(99)
    base = datetime(2026, 7, 15, 0, 0, tzinfo=UTC)
    bars = []
    price = 100.0
    for i in range(60):
        price = max(1.0, price + rng.uniform(-2.0, 2.0))
        h = price + rng.uniform(0.1, 1.0)
        lo = price - rng.uniform(0.1, 1.0)
        c = price
        v = rng.uniform(1.0, 100.0)
        bars.append(
            _bar(base + timedelta(minutes=i), f"{h:.6f}", f"{lo:.6f}", f"{c:.6f}", f"{v:.6f}")
        )
    out = vwap(bars)
    assert len(out) == len(bars)
    assert all(v is not None for v in out)


# ---------------------------------------------------------------------------
# obv
# ---------------------------------------------------------------------------


def test_obv_golden_vector() -> None:
    g = _load("obv")
    out = obv(g["input"]["closes"], g["input"]["volumes"])
    _assert_aligned(out, g["expected"]["obv"])

    # Hand check 1 (seed, obv[0] always 0.0 per the pinned convention):
    assert out[0] == pytest.approx(0.0, abs=1e-9)

    # Hand check 2 (up move, index 1): close1=102.0 > close0=100.0 ->
    # obv1 = obv0 + vol1 = 0.0 + 20.0 = 20.0.
    assert out[1] == pytest.approx(20.0, abs=1e-9)

    # Hand check 3 (unchanged close, index 3): close3=101.0 == close2=
    # 101.0 -> obv3 = obv2 (unchanged) = 5.0 (obv2 = obv1 - vol2 =
    # 20.0 - 15.0 = 5.0, since close2=101.0 < close1=102.0 is a down move).
    assert out[2] == pytest.approx(5.0, abs=1e-9)
    assert out[3] == pytest.approx(5.0, abs=1e-9)


def test_obv_single_bar_is_zero() -> None:
    out = obv([100.0], [10.0])
    assert out == [pytest.approx(0.0, abs=1e-9)]


def test_obv_never_none() -> None:
    """obv has no lookback prefix — first non-None index = 0 (addendum),
    unlike every lookback-bound indicator elsewhere in this package."""
    g = _load("obv")
    out = obv(g["input"]["closes"], g["input"]["volumes"])
    assert all(v is not None for v in out)


def test_obv_properties_random_walk() -> None:
    closes, volumes = _random_walk_volumes()
    out = obv(closes, volumes)
    assert len(out) == len(closes)
    assert out[0] == pytest.approx(0.0, abs=1e-9)
    assert all(v is not None for v in out)


# ---------------------------------------------------------------------------
# volume_ratio
# ---------------------------------------------------------------------------


def test_volume_ratio_golden_vector_pins_zero_sma_case() -> None:
    g = _load("volume_ratio")
    out = volume_ratio(g["input"]["volumes"], period=5)
    _assert_aligned(out, g["expected"]["volume_ratio"])

    # Hand check 1 (seed boundary, index period-1=4): window = volumes[0:5]
    # = [10,20,15,25,30], sum=100.0, sma=100.0/5=20.0.
    # ratio[4] = volumes[4]/sma = 30.0/20.0 = 1.5.
    assert out[4] == pytest.approx(1.5, abs=1e-9)

    # Hand check 2 (zero-numerator, non-zero SMA, index 5): window =
    # volumes[1:6] = [20,15,25,30,0], sum=90.0, sma=18.0.
    # ratio[5] = volumes[5]/sma = 0.0/18.0 = 0.0 (NOT None -- the SMA
    # itself is nonzero here, only the numerator is 0).
    assert out[5] == pytest.approx(0.0, abs=1e-9)

    # Hand check 3 (the pinned zero-SMA case, index 9): window =
    # volumes[5:10] = [0,0,0,0,0], sum=0.0, sma=0.0 -> ratio[9] MUST be
    # None (division-by-zero guard), not a crash and not inf/NaN.
    assert out[9] is None


def test_volume_ratio_short_series_all_none() -> None:
    out = volume_ratio([10.0, 20.0, 30.0], period=5)
    assert out == [None, None, None]


def test_volume_ratio_single_bar() -> None:
    out = volume_ratio([10.0], period=5)
    assert out == [None]


def test_volume_ratio_properties_random_walk_period_20_lookback_and_no_interior_none() -> None:
    """addendum lookback table: volume_ratio(20) first non-None index = 19;
    with strictly positive volumes there is no zero-SMA case, so the
    None-prefix is exactly 19 with no interior None values."""
    _, volumes = _random_walk_volumes(n=120, seed=7)
    # ensure strictly positive (uniform(1.0, 500.0) already guarantees this)
    out = volume_ratio(volumes, period=20)
    assert len(out) == len(volumes)
    none_prefix = sum(1 for v in out if v is None)
    assert none_prefix == 19, "addendum lookback table: volume_ratio(20) first non-None = 19"
    assert all(v is not None for v in out[19:])
