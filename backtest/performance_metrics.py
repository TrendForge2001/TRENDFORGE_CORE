import statistics


class PerformanceMetrics:
    """Aggregate performance statistics for a completed set of trades."""

    def __init__(self, trades):
        self.trades = list(trades)
        self.total_trades = len(self.trades)
        self.wins = len([t for t in self.trades if t.pnl > 0])
        self.losses = len([t for t in self.trades if t.pnl <= 0])
        self.win_rate = self.calculate_win_rate()
        self.net_profit = sum(t.pnl for t in self.trades)
        self.average_profit = self.calculate_average_profit()
        self.average_loss = self.calculate_average_loss()
        self.expectancy = self.calculate_expectancy()

    def calculate_win_rate(self):
        if self.total_trades == 0:
            return 0
        return (self.wins / self.total_trades) * 100

    def calculate_average_profit(self):
        profits = [t.pnl for t in self.trades if t.pnl > 0]
        return statistics.mean(profits) if profits else 0

    def calculate_average_loss(self):
        losses = [t.pnl for t in self.trades if t.pnl < 0]
        return statistics.mean(losses) if losses else 0

    def calculate_expectancy(self):
        return (
            self.average_profit * (self.win_rate / 100)
        ) + (
            self.average_loss * (1 - self.win_rate / 100)
        )
