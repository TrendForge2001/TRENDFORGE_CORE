from dataclasses import dataclass


@dataclass(slots=True)
class Position:
    symbol: str
    quantity: int
    average_price: float
    ltp: float
    side: str = "BUY"
    stoploss: float = 0.0
    target1: float = 0.0
    target2: float = 0.0
    target3: float = 0.0
    pnl: float = 0.0
    pnl_percent: float = 0.0


class PortfolioManager:

    def __init__(self):
        self.positions = {}

    def add(self, trade):
        """Add or replace a tracked position from an executed trade."""
        self.positions[trade.symbol] = Position(
            symbol=trade.symbol,
            quantity=trade.quantity,
            average_price=getattr(trade, "entry_price", getattr(trade, "price", 0.0)),
            ltp=getattr(trade, "entry_price", getattr(trade, "price", 0.0)),
            side=str(trade.side).upper(),
            stoploss=getattr(trade, "stoploss", 0.0),
            target2=getattr(trade, "target2", getattr(trade, "target", 0.0)),
        )

    def update(self, symbol, ltp):
        if symbol not in self.positions:
            return

        position = self.positions[symbol]
        position.ltp = ltp
        direction = -1 if position.side in {"SELL", "SHORT"} else 1
        position.pnl = (
            (ltp - position.average_price)
            * position.quantity
            * direction
        )
        position.pnl_percent = (
            position.pnl / (position.average_price * position.quantity) * 100
            if position.average_price and position.quantity
            else 0.0
        )

    def total_pnl(self):
        return sum(position.pnl for position in self.positions.values())
