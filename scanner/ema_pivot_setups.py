"""The owner's eight EMA/RSI/MACD/traditional-pivot research setups."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EmaPivotSetup:
    name: str
    fast: int
    slow: int
    direction: int
    rsi_min: float
    rsi_max: float
    stop_atr: float
    partial_r: float
    final_r: float | None

    @property
    def trailing(self) -> bool:
        return self.final_r is None

    def pivot_period(self, mode: str) -> str:
        return "DAY" if mode == "intraday" else "MONTH" if self.slow == 200 else "WEEK"


EMA_PIVOT_SETUPS = {
    f"tf_ema{fast}_{slow}_{side}_pivot": EmaPivotSetup(
        f"{fast}/{slow} {side} {label}",
        fast,
        slow,
        direction,
        low,
        high,
        stop,
        partial,
        final,
    )
    for fast, slow, side, direction, label, low, high, stop, partial, final in (
        (9, 26, "bullish", 1, "momentum", 55, 70, 1.5, 1, 2),
        (9, 26, "bearish", -1, "momentum", 30, 45, 1.5, 1, 2),
        (20, 50, "bullish", 1, "swing", 50, 65, 2, 1.5, 3),
        (20, 50, "bearish", -1, "swing", 35, 50, 2, 1.5, 3),
        (50, 100, "bullish", 1, "trend", 50, 100, 2, 2, None),
        (50, 100, "bearish", -1, "trend", 0, 50, 2, 2, None),
        (100, 200, "bullish", 1, "position", 50, 70, 3, 3, None),
        (100, 200, "bearish", -1, "position", 30, 50, 3, 3, None),
    )
}


def setup_indicators(setup: EmaPivotSetup) -> tuple[str, ...]:
    return (
        f"EMA_{setup.fast}",
        f"EMA_{setup.slow}",
        "RSI_WILDER_14",
        "MACD",
        "MACD_SIGNAL",
        "MACD_HIST",
        "ATR_WILDER_14",
        "VOL_SMA_20_PREV",
        "EMA_RESEARCH_BARS",
        *(
            f"TRAD_{period}_{level}"
            for period in ("DAY", "WEEK", "MONTH")
            for level in ("P", "R1", "R2", "S1", "S2")
        ),
    )
