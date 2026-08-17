class ATRStopRule:
    """Calculate an ATR-based protective stop below the current price."""

    def __init__(self, multiplier: float = 1.5) -> None:
        self.multiplier = float(multiplier)

    def calculate(self, snapshot) -> float:
        entry = float(snapshot.close)
        atr = float(getattr(snapshot, "atr", 0.0) or 0.0)
        if atr <= 0:
            raise ValueError("Positive ATR is required for ATR stop calculation")
        return round(max(0.0, entry - self.multiplier * atr), 4)
