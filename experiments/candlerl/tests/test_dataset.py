"""Windowing + labeling: no look-ahead, labels anchored to window end."""
import numpy as np
import pandas as pd

from candlerl._dataset import (
    DIR_DOWN,
    DIR_FLAT,
    DIR_UP,
    HORIZON,
    WINDOW,
    direction_labels,
    window_indices,
)


def test_direction_labels_bucket_forward_log_return():
    n = 40
    close = np.full(n, 100.0)
    close[20 + HORIZON] = 110.0   # strong up move after t=20
    close[25 + HORIZON] = 90.0    # strong down move after t=25
    labels = direction_labels(close, threshold=0.01)
    assert labels[20] == DIR_UP
    assert labels[25] == DIR_DOWN
    assert labels[10] == DIR_FLAT


def test_direction_labels_are_invalid_near_series_end():
    close = np.linspace(100, 110, 30)
    labels = direction_labels(close)
    assert (labels[-HORIZON:] == -1).all()


def test_window_indices_fit_inside_series_with_horizon():
    n = 200
    ends = window_indices(n)
    assert ends.min() >= WINDOW - 1
    assert ends.max() <= n - 1 - HORIZON
    assert (np.diff(ends) > 0).all()


def test_chronological_split_has_embargo():
    """No training window may end within HORIZON bars of the validation start."""
    from candlerl._dataset import split_by_date

    dates = pd.date_range("2020-01-01", periods=300, freq="D")
    ends = window_indices(len(dates))
    train, val, test = split_by_date(ends, dates, "2020-07-01", "2020-09-01")
    assert len(train) and len(val) and len(test)
    val_start_idx = int(np.searchsorted(dates, pd.Timestamp("2020-07-01")))
    test_start_idx = int(np.searchsorted(dates, pd.Timestamp("2020-09-01")))
    assert ends[train].max() + HORIZON < val_start_idx
    assert ends[val].max() + HORIZON < test_start_idx
    assert ends[val].min() >= val_start_idx
    assert ends[test].min() >= test_start_idx
