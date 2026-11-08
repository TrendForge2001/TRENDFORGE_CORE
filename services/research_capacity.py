"""Bound cloud preview work; accepted runs retain the complete universe."""

from core.deployment_role import cloud_read_only

CLOUD_MAX_CANDLE_ROWS = 150_000
ESTIMATED_BARS = {"30d": 550, "45d": 825, "60d": 1100, "1y": 270, "2y": 540, "5y": 1350}


def validate_backtest_capacity(settings, count):
    estimate = count * ESTIMATED_BARS[settings["period"]]
    if cloud_read_only() and estimate > CLOUD_MAX_CANDLE_ROWS:
        raise ValueError(
            "This full-list backtest exceeds the temporary cloud preview capacity. "
            "Run it in the PC workspace for the complete universe and "
            "permanent reports."
        )
