"""Small report payload from the exact completed candles the scanner evaluated."""

import math

import pandas as pd


def capture(frame, *, horizon, now):
    from services.institutional_stock_rating import assess_technical, technical_evidence

    def finite(value):
        try:
            value = float(value)
            return value if math.isfinite(value) else None
        except (TypeError, ValueError):
            return None

    candles = []
    for stamp, row in frame.tail(252).iterrows():
        values = {
            key: finite(row.get(key))
            for key in (
                "open",
                "high",
                "low",
                "close",
                "volume",
            )
        }
        if all(value is not None for value in values.values()):
            candles.append({"date": pd.Timestamp(stamp).date().isoformat(), **values})
    last = frame.iloc[-1]
    names = (
        "EMA_20",
        "EMA_50",
        "EMA_100",
        "EMA_200",
        "VWMA_9",
        "VWMA_26",
        "VWMA_20",
        "VWMA_50",
        "RSI_WILDER_14",
        "VOL_SMA_20",
        "volume",
        "close",
        *("FIB_YEAR_" + key for key in ("P", "S1", "S2", "S3", "R1", "R2", "R3")),
    )
    assessed = assess_technical(
        technical_evidence(frame, horizon=horizon, now=now),
        horizon=horizon,
        now=now,
    )
    return {
        "candles": candles,
        "indicators": {key: finite(last.get(key)) for key in names},
        "technical_assessment": assessed,
        "source": "canonical_completed_scan_candles",
    }
