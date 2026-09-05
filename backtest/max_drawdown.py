class MaxDrawdown:

    def calculate(self, equity):
        """Return maximum peak-to-trough drawdown percentage."""
        equity = list(equity)
        if not equity:
            return 0.0

        peak = equity[0]
        max_dd = 0.0

        for value in equity:
            if value > peak:
                peak = value

            drawdown = (peak - value) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, drawdown)

        return round(max_dd * 100, 2)
