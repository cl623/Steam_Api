import numpy as np

from nlp.velocity import lag_shift_correlation, mean_abs_velocity


def test_lag_shift_correlation_zero_lag():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    y = np.array([1.0, 2.0, 3.0, 4.0])
    p, s = lag_shift_correlation(x, y, 0)
    assert np.isfinite(p) and abs(p - 1.0) < 1e-6


def test_mean_abs_velocity_finite():
    ts = np.array([0.0, 60.0, 120.0, 180.0])
    sc = np.array([-1.0, 0.0, 1.0, 0.0])
    m = mean_abs_velocity(ts, sc, bin_seconds=60.0)
    assert np.isfinite(m)
