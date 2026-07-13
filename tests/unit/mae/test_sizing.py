"""Kelly + ATR sizing math (DESIGN §9.3, TD-11; canonical MAE §3 formulas).

TEST-PATH EXCEPTION (ASSUMPTIONS 23): imports mae._sizing directly until the
size_position verb gets its data wiring in P1C — then re-point + ban.

Golden vectors are hand-derived. The canonical doc's example OUTPUT for these
inputs (0.2102) does NOT satisfy its own formula — trust f* = W - (1-W)/R.
"""

from decimal import Decimal

import pytest

from tradekit.mae._sizing import atr_position, kelly_fractions


def test_kelly_golden_vector() -> None:
    full, quarter = kelly_fractions(win_rate=0.574, payoff_ratio=1.572)
    # Exact-fraction derivation: .426/1.572 = 426/1572 = 71/262 = 0.2709924
    # f* = .574 - 71/262 = 0.3030076
    assert full == pytest.approx(0.574 - 71 / 262, abs=1e-9), (
        f"full Kelly {full}: f* = W - (1-W)/R. The canonical doc's example answer "
        "(0.2102) is WRONG for these inputs — the formula is the authority"
    )
    assert quarter == pytest.approx((0.574 - 71 / 262) / 4, abs=1e-9), "quarter = 0.25 x f*"


def test_negative_kelly_clamps_to_zero() -> None:
    full, quarter = kelly_fractions(win_rate=0.40, payoff_ratio=1.0)
    assert full == 0.0 and quarter == 0.0, (
        "W=.40, R=1.0 gives raw f* = -0.2 -> must clamp to 0 (negative edge = NO "
        "position, never a short-the-strategy hallucination; DESIGN §9.3)"
    )


@pytest.mark.parametrize(
    ("win_rate", "payoff"), [(-0.1, 1.5), (1.1, 1.5), (0.5, 0.0), (0.5, -2.0)]
)
def test_kelly_rejects_nonsense_inputs(win_rate: float, payoff: float) -> None:
    with pytest.raises(ValueError):
        kelly_fractions(win_rate=win_rate, payoff_ratio=payoff)


def test_atr_position_golden_vector() -> None:
    got = atr_position(
        equity_usd=Decimal("1000"),
        risk_pct=0.01,
        atr=Decimal("2.0"),
        multiplier=2.0,
        price=Decimal("100"),
    )
    assert got["risk_usd"] == Decimal("10"), "equity x risk_pct"
    assert got["stop_distance"] == Decimal("4.0"), "ATR x multiplier"
    assert got["stop_pct"] == pytest.approx(0.04), "stop_distance / price"
    assert got["units"] == Decimal("2.5"), (
        "units = risk_usd / stop_distance — being stopped out loses exactly risk_usd; "
        "that identity IS the point of ATR sizing (canonical §3)"
    )
    assert got["size_usd"] == Decimal("250"), "units x price"


def test_atr_rejects_zero_atr() -> None:
    with pytest.raises(ValueError):
        atr_position(
            equity_usd=Decimal("1000"), risk_pct=0.01,
            atr=Decimal("0"), multiplier=2.0, price=Decimal("100"),
        )
    # zero ATR would size an infinite position — a data-layer glitch must die
    # here, not at the broker
