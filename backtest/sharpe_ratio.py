import math
import statistics


class SharpeRatio:

    def calculate(self, returns, risk_free=0.06):
        """Calculate annualized daily Sharpe ratio safely."""
        returns = list(returns)
        if len(returns) < 2:
            return 0.0

        excess = [r - risk_free / 252 for r in returns]
        deviation = statistics.stdev(excess)
        if deviation == 0:
            return 0.0

        return (
            statistics.mean(excess) / deviation
        ) * math.sqrt(252)
