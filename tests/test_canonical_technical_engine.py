from __future__ import annotations

import pandas as pd

from engines.canonical_technical_engine import CanonicalTechnicalEngine


class CountingIndicators:
    calls = 0
    def calculate(self, frame):
        self.calls += 1
        raise AssertionError("canonical technical engine must not calculate indicators")


def enriched_frame(rows=30):
    data = {"open": [99.0] * rows, "high": [101.0] * rows, "low": [98.0] * rows,
            "close": [100.0] * rows, "volume": [1000.0] * rows}
    for key in CanonicalTechnicalEngine.REQUIRED_INDICATORS:
        data[key] = [0.0] * rows
    data.update({"EMA_9": [101.0] * rows, "EMA_20": [100.0] * rows, "EMA_50": [99.0] * rows,
                 "EMA_100": [98.0] * rows, "EMA_200": [97.0] * rows, "RSI": [60.0] * rows,
                 "MACD": [1.0] * rows, "MACD_SIGNAL": [0.5] * rows, "MACD_HIST": [0.5] * rows,
                 "ADX": [30.0] * rows, "+DI": [25.0] * rows, "-DI": [15.0] * rows,
                 "RVOL": [1.5] * rows, "VWAP": [99.0] * rows, "CMF": [0.2] * rows,
                 "MFI": [60.0] * rows, "ATR": [2.0] * rows, "ATR_PERCENT": [2.0] * rows,
                 "BB_WIDTH": [0.05] * rows, "SUPPORT": [95.0] * rows, "RESISTANCE": [105.0] * rows})
    return pd.DataFrame(data)


def test_canonical_engine_consumes_existing_indicator_frame():
    engine = CanonicalTechnicalEngine(CountingIndicators())
    result = engine.evaluate({"df": enriched_frame()})
    assert result.engine == "Technical Engine"
    assert result.score >= 0


def test_canonical_engine_rejects_missing_indicator_columns():
    frame = enriched_frame().drop(columns=["EMA_200"])
    result = CanonicalTechnicalEngine(CountingIndicators()).evaluate({"df": frame})
    assert result.passed is False
    assert any("Missing indicators" in warning for warning in result.warnings)
