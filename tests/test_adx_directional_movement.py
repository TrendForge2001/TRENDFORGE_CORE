"""Independent directional-movement fixtures for the existing rolling ADX."""

import numpy as np
import pandas as pd
import pytest

from indicators.momentum import MomentumIndicators


def test_equal_positive_movements_do_not_invent_a_bearish_trend():
    steps = np.arange(40, dtype=float)
    frame = pd.DataFrame({"high": 101 + steps, "low": 99 - steps, "close": 100.0})
    result = MomentumIndicators.add_adx(frame)
    assert (result[["+DI", "-DI"]].iloc[13:] == 0).all().all()
    # Zero directional movement leaves DX undefined, not a strong trend.
    assert result["ADX"].isna().all()


def test_flat_prices_have_zero_directional_movement_after_warmup():
    frame = pd.DataFrame({"high": [101.0] * 40, "low": 99.0, "close": 100.0})
    result = MomentumIndicators.add_adx(frame)
    assert result[["+DI", "-DI"]].iloc[-1].tolist() == [0.0, 0.0]
    assert result["ADX"].isna().all()
    assert not np.isinf(result[["+DI", "-DI", "ADX"]].to_numpy()).any()


def test_rolling_adx_retains_its_two_window_warmup():
    steps = np.arange(30, dtype=float)
    frame = pd.DataFrame(
        {"high": 102 + steps, "low": 100 + steps, "close": 101 + steps}
    )
    result = MomentumIndicators.add_adx(frame)
    assert result["+DI"].iloc[:13].isna().all()
    assert result["ADX"].iloc[:26].isna().all()
    assert result["ADX"].iloc[26] == pytest.approx(100)


@pytest.mark.parametrize("direction", [1, -1])
def test_one_direction_trends_preserve_the_correct_di_leg(direction):
    close = 100 + direction * np.arange(40, dtype=float)
    frame = pd.DataFrame({"high": close + 1, "low": close - 1, "close": close})
    row = MomentumIndicators.add_adx(frame).iloc[-1]
    active, inactive = ("+DI", "-DI") if direction == 1 else ("-DI", "+DI")
    assert row[active] == pytest.approx(50)
    assert row[inactive] == 0
    assert row["ADX"] == pytest.approx(100)


def test_mixed_bars_match_hand_calculated_rolling_adx():
    # Raw +DM: 0,1,0,0,3,0,0,3; -DM: 0,0,0,1,0,0,1,0.
    # Three-bar DX values after ATR warm-up: 100,0,50,50,50,50.
    frame = pd.DataFrame(
        {
            "high": [11, 12, 14, 13, 16, 16, 15, 18],
            "low": [9, 10, 8, 7, 9, 9, 8, 10],
            "close": [10, 11, 10, 8, 15, 15, 9, 17],
        }
    )
    result = MomentumIndicators.add_adx(frame, length=3)
    assert result["+DI"].iloc[2] == pytest.approx(10)
    assert result["-DI"].iloc[2] == 0
    assert result["+DI"].iloc[-1] == pytest.approx(300 / 23)
    assert result["-DI"].iloc[-1] == pytest.approx(100 / 23)
    assert result["ADX"].iloc[4:].tolist() == pytest.approx([50, 100 / 3, 50, 50])
