"""tests for the PUBLIC tradekit.mae.get_correlation_matrix verb AND its
private pure-math core tradekit.mae._correlation (SPRINT-P1C story 3,
"Correlation pins").

TEST-PATH EXCEPTION (extends ASSUMPTIONS 23/29/39): the direct
`compute_correlation` tests in this file import `tradekit.mae._correlation`
directly (pure-math golden vectors, same rationale as `mae._sizing`'s
existing exception — exercising the join+Pearson arithmetic in isolation is
cheaper and more precise than only ever going through the verb). The
verb-level tests fake runtime bars by monkeypatching
`"tradekit.mae._runtime.get_daily_bars"` by dotted STRING path (no import
statement, needs no exception).

Status: both `get_correlation_matrix` and `compute_correlation` are P1C
batch A STUBS (raise NotImplementedError unconditionally) — every test
below currently fails with NotImplementedError, the expected red state.

=== Pearson derivation (fixture-freeze rule; `derive_p1c_batchA.py` in the
session scratchpad, never committed) ===

5-point hand-computed golden (addendum-required "show sums" discipline):
    x = [1, 2, 3, 4, 5],  y = [2, 1, 4, 3, 5]
    mean_x = 3.0, mean_y = 3.0
    dx = [-2, -1, 0, 1, 2]
    dy = [-1, -2, 1, 0, 2]
    dx*dy = [2, 2, 0, 0, 4]        sum = 8
    dx^2  = [4, 1, 0, 1, 4]        sum = 10
    dy^2  = [1, 4, 1, 0, 4]        sum = 10
    r = 8 / sqrt(10*10) = 8/10 = 0.8
    Cross-check (DERIVATION-time only, per fixture-freeze rule):
    numpy.corrcoef([1,2,3,4,5], [2,1,4,3,5])[0,1] = 0.7999999999999999 (matches)

y=2x / y=-x (25 points, arbitrary base return series xs = 1..25 scaled by
1/100): pearson(xs, 2*xs) = 1.0 exactly; pearson(xs, -xs) = -1.0 exactly
(scale/sign-invariance of Pearson r — verified by direct computation, not
just the algebraic identity, in derive_p1c_batchA.py).

Independent seeded noise (Python stdlib `random.gauss`, seed=1337 for x,
seed=2026 for y, n=25, sigma=0.01 on log-return space): computed r =
0.2285787678389131 -> |r| < 0.5.

Weekend-drop join fixture (6 calendar weeks from Monday 2026-03-02, 36
total days spanned; crypto trades all 36 days, closes flat on weekends;
equity trades only the first 26 weekdays): crypto weekday-to-weekday
returns and equity returns are built from the SAME xs/2*xs relationship as
the y=2x golden above, so a CORRECT UTC-date inner join of the two return
series yields exactly 25 joined points (26 weekday dates - 1, since the
first weekday has no prior-bar return) with r=1.0 (>=20 overlap, so a real
number, not None) AND |r|>0.75 (high_correlation_warnings). Weekend closes
are held FLAT (zero return) specifically so that if an implementation bug
leaked weekend dates into the join (equity truly has no bars there, so a
correct date-based inner join cannot include them) or mis-aligned by
POSITION instead of by DATE, the result would visibly deviate from exactly
1.0 — this fixture is a "wrong join breaks the number" trap, not just an
existence check.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from tradekit.contracts import AssetRef, Bar, BarSeries
from tradekit.mae import _correlation, get_correlation_matrix

# ---------------------------------------------------------------------------
# Direct compute_correlation (pure math core) golden vectors
# ---------------------------------------------------------------------------


def test_compute_correlation_five_point_hand_derived_golden() -> None:
    dates = [date(2026, 1, i) for i in range(1, 6)]
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [2.0, 1.0, 4.0, 3.0, 5.0]
    series = {
        "A": list(zip(dates, x, strict=True)),
        "B": list(zip(dates, y, strict=True)),
    }

    result = _correlation.compute_correlation(series, min_overlap=3, high_corr_threshold=0.75)

    assert result.matrix["A"]["B"] == pytest.approx(0.8, abs=1e-9)
    assert result.matrix["B"]["A"] == pytest.approx(0.8, abs=1e-9)


def test_compute_correlation_y_equals_2x_gives_r_one() -> None:
    dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(25)]
    xs = [i / 100.0 for i in range(1, 26)]
    ys = [2 * v for v in xs]
    series = {"A": list(zip(dates, xs, strict=True)), "B": list(zip(dates, ys, strict=True))}

    result = _correlation.compute_correlation(series)

    assert result.matrix["A"]["B"] == pytest.approx(1.0, abs=1e-9)


def test_compute_correlation_y_equals_negative_x_gives_r_negative_one() -> None:
    dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(25)]
    xs = [i / 100.0 for i in range(1, 26)]
    ys = [-v for v in xs]
    series = {"A": list(zip(dates, xs, strict=True)), "B": list(zip(dates, ys, strict=True))}

    result = _correlation.compute_correlation(series)

    assert result.matrix["A"]["B"] == pytest.approx(-1.0, abs=1e-9)


def test_compute_correlation_independent_seeded_noise_low_correlation() -> None:
    import random

    random.seed(1337)
    xs = [random.gauss(0, 0.01) for _ in range(25)]
    random.seed(2026)
    ys = [random.gauss(0, 0.01) for _ in range(25)]
    dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(25)]
    series = {"A": list(zip(dates, xs, strict=True)), "B": list(zip(dates, ys, strict=True))}

    result = _correlation.compute_correlation(series)

    r = result.matrix["A"]["B"]
    assert r is not None
    assert abs(r) < 0.5, f"independent noise should show weak correlation, got r={r}"


def test_compute_correlation_self_correlation_is_exactly_one() -> None:
    dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(25)]
    xs = [i / 100.0 for i in range(1, 26)]
    series = {"A": list(zip(dates, xs, strict=True))}

    result = _correlation.compute_correlation(series)

    assert result.matrix["A"]["A"] == 1.0, (
        "self-correlation is reported as exactly 1.0, not computed"
    )


def test_compute_correlation_insufficient_overlap_yields_null_and_warning() -> None:
    dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(10)]
    xs = [i / 100.0 for i in range(1, 11)]
    series = {
        "A": list(zip(dates, xs, strict=True)),
        "B": list(zip(dates, [2 * v for v in xs], strict=True)),
    }

    result = _correlation.compute_correlation(series, min_overlap=20)

    assert result.matrix["A"]["B"] is None
    assert result.matrix["B"]["A"] is None
    assert ("A", "B", 10) in result.insufficient_overlap_warnings or (
        "B",
        "A",
        10,
    ) in result.insufficient_overlap_warnings


def test_compute_correlation_high_correlation_flagged() -> None:
    dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(25)]
    xs = [i / 100.0 for i in range(1, 26)]
    series = {
        "A": list(zip(dates, xs, strict=True)),
        "B": list(zip(dates, [2 * v for v in xs], strict=True)),
    }

    result = _correlation.compute_correlation(series, high_corr_threshold=0.75)

    pairs = [(a, b) for (a, b, _r) in result.high_correlation_warnings]
    assert ("A", "B") in pairs or ("B", "A") in pairs


# ---------------------------------------------------------------------------
# Verb-level tests: through PUBLIC mae.get_correlation_matrix with faked
# runtime bars (BarSeries fixtures, monkeypatched via string path).
# ---------------------------------------------------------------------------

_CRYPTO_ASSET = AssetRef(
    symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01")
)
_EQUITY_ASSET = AssetRef(
    symbol="SPY", venue="alpaca", asset_class="equity", tick_size=Decimal("0.01")
)

# Weekend-drop fixture (see module docstring for derivation). Crypto trades
# every calendar day (weekend closes held flat); equity trades only its 26
# weekday dates. Prices computed by derive_p1c_batchA.py section 5.
_CRYPTO_CLOSES: dict[str, str] = {
    "2026-03-02": "100.00000000",
    "2026-03-03": "101.00501671",
    "2026-03-04": "103.04545340",
    "2026-03-05": "106.18365465",
    "2026-03-06": "110.51709181",
    "2026-03-07": "110.51709181",
    "2026-03-08": "110.51709181",
    "2026-03-09": "116.18342427",
    "2026-03-10": "123.36780600",
    "2026-03-11": "132.31298123",
    "2026-03-12": "143.33294146",
    "2026-03-13": "156.83121855",
    "2026-03-14": "156.83121855",
    "2026-03-15": "156.83121855",
    "2026-03-16": "173.32530179",
    "2026-03-17": "193.47923344",
    "2026-03-18": "218.14722655",
    "2026-03-19": "248.43225334",
    "2026-03-20": "285.76511181",
    "2026-03-21": "285.76511181",
    "2026-03-22": "285.76511181",
    "2026-03-23": "332.01169227",
    "2026-03-24": "389.61933018",
    "2026-03-25": "461.81768223",
    "2026-03-26": "552.89614776",
    "2026-03-27": "668.58944423",
    "2026-03-28": "668.58944423",
    "2026-03-29": "668.58944423",
    "2026-03-30": "816.61699126",
    "2026-03-31": "1007.44246550",
    "2026-04-01": "1255.35061367",
    "2026-04-02": "1579.98429483",
    "2026-04-03": "2008.55369232",
    "2026-04-04": "2008.55369232",
    "2026-04-05": "2008.55369232",
    "2026-04-06": "2579.03399172",
}

_EQUITY_CLOSES: dict[str, str] = {
    "2026-03-02": "50.00000000",
    "2026-03-03": "51.01006700",
    "2026-03-04": "53.09182733",
    "2026-03-05": "56.37484258",
    "2026-03-06": "61.07013791",
    "2026-03-09": "67.49294038",
    "2026-03-10": "76.09807778",
    "2026-03-11": "87.53362501",
    "2026-03-12": "102.72166053",
    "2026-03-13": "122.98015556",
    "2026-03-16": "150.20830120",
    "2026-03-17": "187.17106886",
    "2026-03-18": "237.94106226",
    "2026-03-19": "308.59292249",
    "2026-03-20": "408.30849563",
    "2026-03-23": "551.15881903",
    "2026-03-24": "759.01611225",
    "2026-03-25": "1066.37785810",
    "2026-03-26": "1528.47075105",
    "2026-03-27": "2235.05922467",
    "2026-03-30": "3334.31655205",
    "2026-03-31": "5074.70160648",
    "2026-04-01": "7879.52581617",
    "2026-04-02": "12481.75185948",
    "2026-04-03": "20171.43967464",
    "2026-04-06": "33257.08165222",
}


def _bars_from_closes(asset: AssetRef, closes: dict[str, str]) -> BarSeries:
    bars = [
        Bar(
            ts_open=datetime.fromisoformat(d).replace(tzinfo=UTC),
            open=Decimal(price),
            high=Decimal(price),
            low=Decimal(price),
            close=Decimal(price),
            volume=Decimal("1000"),
        )
        for d, price in sorted(closes.items())
    ]
    return BarSeries(asset=asset, timeframe="1d", bars=bars, source="fake")


def _fake_get_daily_bars_factory(by_symbol: dict[str, BarSeries]):
    def _fake(symbol: str, lookback_days: int) -> BarSeries:
        return by_symbol[symbol]

    return _fake


def test_get_correlation_matrix_weekend_drop_join_and_high_correlation(monkeypatch) -> None:
    crypto_series = _bars_from_closes(_CRYPTO_ASSET, _CRYPTO_CLOSES)
    equity_series = _bars_from_closes(_EQUITY_ASSET, _EQUITY_CLOSES)
    fake = _fake_get_daily_bars_factory({"BTC/USD": crypto_series, "SPY": equity_series})
    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", fake)

    result = get_correlation_matrix(symbols=["BTC/USD", "SPY"], window_days=40, timeframe="1d")

    assert result["matrix"]["BTC/USD"]["SPY"] == pytest.approx(1.0, abs=1e-6), (
        "correct UTC-date inner join (weekend crypto dates dropped, since SPY "
        "has no bars there) must reproduce the planted y=2x relationship exactly"
    )
    assert result["matrix"]["BTC/USD"]["BTC/USD"] == 1.0
    assert result["matrix"]["SPY"]["SPY"] == 1.0
    pairs = [tuple(w["pair"]) for w in result["high_correlation_warnings"]]
    assert ("BTC/USD", "SPY") in pairs or ("SPY", "BTC/USD") in pairs


def test_get_correlation_matrix_insufficient_overlap_names_pair(monkeypatch) -> None:
    # First 10 equity weekday dates only -> 9 joined return points (<20).
    short_equity_closes = dict(list(_EQUITY_CLOSES.items())[:10])
    first_equity_date = min(short_equity_closes)
    short_crypto_closes = {d: p for d, p in _CRYPTO_CLOSES.items() if d <= first_equity_date}
    crypto_series = _bars_from_closes(_CRYPTO_ASSET, short_crypto_closes)
    equity_series = _bars_from_closes(_EQUITY_ASSET, short_equity_closes)
    fake = _fake_get_daily_bars_factory({"BTC/USD": crypto_series, "SPY": equity_series})
    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", fake)

    result = get_correlation_matrix(symbols=["BTC/USD", "SPY"], window_days=15, timeframe="1d")

    assert result["matrix"]["BTC/USD"]["SPY"] is None, (
        "< 20 overlapping return points must NEVER be a silently-computed number (R-013)"
    )
    # Key name is NOT pinned by canonical §3 (its example output shows only
    # high_correlation_warnings) -- this session's choice, flagged in the
    # batch report as a schema ambiguity for CTO ratification.
    named_pairs = [tuple(w["pair"]) for w in result["insufficient_overlap_warnings"]]
    assert ("BTC/USD", "SPY") in named_pairs or ("SPY", "BTC/USD") in named_pairs


def test_get_correlation_matrix_output_shape(monkeypatch) -> None:
    crypto_series = _bars_from_closes(_CRYPTO_ASSET, _CRYPTO_CLOSES)
    equity_series = _bars_from_closes(_EQUITY_ASSET, _EQUITY_CLOSES)
    fake = _fake_get_daily_bars_factory({"BTC/USD": crypto_series, "SPY": equity_series})
    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", fake)

    result = get_correlation_matrix(symbols=["BTC/USD", "SPY"], window_days=40, timeframe="1d")

    assert set(result.keys()) >= {"window_days", "as_of", "matrix", "high_correlation_warnings"}
    assert result["window_days"] == 40
    assert isinstance(result["matrix"], dict)
    assert isinstance(result["high_correlation_warnings"], list)
