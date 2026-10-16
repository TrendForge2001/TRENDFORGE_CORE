from __future__ import annotations

from engines.breadth_engine import BreadthEngine


def test_zero_advances_are_not_treated_as_missing():
    result = BreadthEngine().evaluate(
        {
            "advances": 0,
            "declines": 100,
            "unchanged": 0,
            "total_stocks": 100,
            "new_highs": 0,
            "new_lows": 20,
        }
    )

    assert result.metrics["advances"] == 0.0
    assert result.metrics["declines"] == 100.0
    assert result.metrics["breadth_pct"] == -100.0
    assert result.metrics["direction"] == "STRONG_BEARISH"
    assert "Advancing stock count unavailable." not in result.warnings
