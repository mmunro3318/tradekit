"""mae.compute_strategy_metrics — the edge-math core (DESIGN §9.4, TD-14, G1).

Golden vectors are hand-computed from the documented conventions (see the
module docstring of tradekit/mae/_metrics.py): per-trade returns r=pnl/size,
trade-level Sharpe annualized by sqrt(trades-per-year over the log's span).
If a formula changes, these numbers must be re-derived BY HAND — never by
running the implementation and pasting its output (that's how wrong math
gets frozen as truth).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradekit.mae import compute_strategy_metrics

D0 = datetime(2026, 1, 1, tzinfo=UTC)


def _t(day: float) -> datetime:
    return D0 + timedelta(days=day)


def _trade(entry_d, exit_d, entry_px, exit_px, side="long", size="1000", fees="2"):
    return {
        "entry_ts": _t(entry_d),
        "exit_ts": _t(exit_d),
        "entry_price": Decimal(entry_px),
        "exit_price": Decimal(exit_px),
        "side": side,
        "size_usd": Decimal(size),
        "fees_usd": Decimal(fees),
    }


@pytest.fixture
def golden_log():
    """4 trades, pnl = [+98, -52, +98, -2] (fees make trade D a loss).

    Hand-derived: r=[.098,-.052,.098,-.002]; mean=.0355; std(ddof=1)=.0750;
    span 30d -> trades/yr = 4*365.25/30 = 48.70, sqrt = 6.9785.
    """
    return [
        _trade(0, 3, "100", "110"),                  # +98
        _trade(2, 6, "100", "95"),                   # -52
        _trade(5, 9, "100", "90", side="short"),     # +98 (short profits on the drop)
        _trade(8, 30, "100", "100"),                 # -2 (flat price, fees eat it)
    ]


def test_pnl_win_rate_expectancy_pf(golden_log) -> None:
    m = compute_strategy_metrics(golden_log, risk_free_rate_annual=0.0)
    assert m.n_trades == 4
    assert m.total_pnl_usd == Decimal("142"), (
        f"net pnl {m.total_pnl_usd}: (+98 -52 +98 -2) — short direction or fee handling "
        "is wrong if this is off (pnl = side * (exit-entry)/entry * size - fees)"
    )
    assert m.total_fees_usd == Decimal("8")
    assert m.win_rate == pytest.approx(0.5), (
        f"win_rate {m.win_rate}: trade D (flat price, fees) is a LOSS — counting "
        "pnl==0-ε as a win inflates edge (§9.4 net-of-costs discipline)"
    )
    assert m.expectancy_usd == Decimal("35.5"), "expectancy = mean net pnl = 142/4"
    assert m.profit_factor == pytest.approx(196 / 54), "PF = gross wins / |gross losses|"
    assert m.avg_win_usd == Decimal("98") and m.avg_loss_usd == Decimal("27")


def test_sharpe_and_sortino_annualization_convention(golden_log) -> None:
    m = compute_strategy_metrics(golden_log, risk_free_rate_annual=0.0)
    # SR_trade = .0355/.0750 = .47333; annual = x sqrt(48.70) = x 6.9785
    assert m.sharpe_annual == pytest.approx(3.303, abs=0.01), (
        f"sharpe_annual {m.sharpe_annual}: convention is trade-level SR x "
        "sqrt(trades-per-year over the log span) — a different annualization basis "
        "changes every gate in DESIGN §9.4 silently"
    )
    # downside dev (MAR=0, full-n): sqrt((.052^2+.002^2)/4)=.02602 -> 1.3644 x 6.9785
    assert m.sortino_annual == pytest.approx(9.52, abs=0.05)


def test_drawdown_and_calmar_with_base_equity(golden_log) -> None:
    m = compute_strategy_metrics(
        golden_log, risk_free_rate_annual=0.0, base_equity_usd=Decimal("1000")
    )
    assert m.max_drawdown_usd == Decimal("52"), (
        f"MDD {m.max_drawdown_usd}: cum-pnl by exit order is [98,46,144,142] — peak 98 "
        "to trough 46 is the max peak-to-trough drop"
    )
    assert m.max_drawdown_pct == pytest.approx(52 / 1098, rel=1e-3), (
        "MDD%% is measured against PEAK equity (base+98), not base — measuring against "
        "base understates drawdown after gains"
    )
    assert m.calmar == pytest.approx(85.2, rel=0.02), (
        "calmar = CAGR/MDD%%; CAGR=(1.142)^(365.25/30)-1 = 4.035 over the 30d span"
    )


def test_calmar_and_mdd_pct_none_without_base_equity(golden_log) -> None:
    m = compute_strategy_metrics(golden_log)
    assert m.calmar is None and m.max_drawdown_pct is None
    assert "base_equity_not_provided" in m.warnings, (
        "percent drawdown without a base equity would be an invented number — None + "
        "warning, never a guess (§13 'never silent substitution')"
    )


def test_small_sample_verdict_and_warnings(golden_log) -> None:
    m = compute_strategy_metrics(golden_log)
    assert m.edge_verdict == "insufficient", (
        f"verdict {m.edge_verdict!r} at n=4: below n=10 metrics are descriptive only, "
        "no verdict (G1) — 4 trades 'proving' an edge is the exact failure mode "
        "the SME flagged (F2/F3)"
    )
    assert "sample_size_insufficient" in m.warnings
    assert "overfit_risk_pf" in m.warnings, "PF=3.63 > 3 must warn (canonical doc)"
    assert m.dsr is None and "dsr_not_applicable_small_n" in m.warnings


def _pattern_log(n: int):
    """Alternating +2%/-1% on $1000, no fees: symmetric two-point return dist."""
    out = []
    for i in range(n):
        px = "102" if i % 2 == 0 else "99"
        out.append(_trade(i, i + 1, "100", px, fees="0"))
    return out


def test_provisional_band_penalized_sharpe_formula() -> None:
    m = compute_strategy_metrics(_pattern_log(20), risk_free_rate_annual=0.0)
    assert m.dsr is None, "n=20 is inside the provisional band — DSR must not gate (G1)"
    assert m.penalized_sharpe_annual is not None and m.sharpe_annual is not None
    assert m.penalized_sharpe_annual / m.sharpe_annual == pytest.approx(
        1 - 1 / (20**0.5)
    ), (
        "provisional haircut is SR x (1 - 1/sqrt(n)) exactly (DESIGN §9.4, G1) — any "
        "other shrinkage silently moves the promotion bar"
    )


def test_dsr_unlocks_at_30_and_penalizes_trials() -> None:
    log = _pattern_log(40)
    lone = compute_strategy_metrics(log, risk_free_rate_annual=0.0, n_trials=1)
    mined = compute_strategy_metrics(log, risk_free_rate_annual=0.0, n_trials=100)
    assert lone.dsr is not None and 0.0 <= lone.dsr <= 1.0
    assert lone.penalized_sharpe_annual is None, "penalized regime ends at n>=30 (G1)"
    assert mined.dsr is not None and mined.dsr < lone.dsr, (
        f"dsr(trials=100)={mined.dsr} !< dsr(trials=1)={lone.dsr}: the entire point of "
        "DSR is punishing strategy-mining — 100 tries must score below 1 (TD-14; the "
        "experiment registry supplies the real trial count)"
    )


def test_no_losing_trades_pf_none_not_inf() -> None:
    log = [_trade(0, 1, "100", "110", fees="0"), _trade(1, 2, "100", "105", fees="0")]
    m = compute_strategy_metrics(log)
    assert m.profit_factor is None and "no_losing_trades" in m.warnings, (
        "all-winner logs make PF undefined — None + warning, not inf (inf poisons "
        "downstream JSON and comparisons)"
    )


def test_rejects_exit_before_entry() -> None:
    bad = [_trade(5, 3, "100", "110")]
    with pytest.raises(ValueError):
        compute_strategy_metrics(bad)


def test_rejects_empty_log() -> None:
    with pytest.raises(ValueError):
        compute_strategy_metrics([])
