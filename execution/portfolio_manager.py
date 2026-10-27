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
    trade_mode: str = "intraday"
    strategy_id: str | None = None
    strategy_name: str | None = None
    strategy_source: str | None = None
    source_scan_run_id: str | None = None
    validation_run_id: str | None = None
    strategy_score: float = 0.0
    consensus_score: float = 0.0
    entry_signal: str | None = None
    entry_bar_at: str | None = None
    entry_at: str | None = None
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
            average_price=getattr(
                trade,
                "entry_price",
                getattr(trade, "price", 0.0),
            ),
            ltp=getattr(
                trade,
                "entry_price",
                getattr(trade, "price", 0.0),
            ),
            side=str(trade.side).upper(),
            stoploss=getattr(trade, "stoploss", 0.0),
            target2=getattr(
                trade,
                "target2",
                getattr(trade, "target", 0.0),
            ),
            trade_mode=str(
                getattr(trade, "trade_mode", "intraday") or "intraday"
            ).strip().lower(),
            strategy_id=(
                str(getattr(trade, "strategy_id", "") or "").strip().lower()
                or None
            ),
            strategy_name=(
                str(getattr(trade, "strategy_name", "") or "").strip()
                or None
            ),
            strategy_source=(
                str(getattr(trade, "strategy_source", "") or "").strip()
                or None
            ),
            source_scan_run_id=(
                str(getattr(trade, "source_scan_run_id", "") or "").strip()
                or None
            ),
            validation_run_id=(
                str(getattr(trade, "validation_run_id", "") or "").strip()
                or None
            ),
            strategy_score=float(
                getattr(trade, "strategy_score", 0.0) or 0.0
            ),
            consensus_score=float(
                getattr(trade, "consensus_score", 0.0) or 0.0
            ),
            entry_signal=(
                str(getattr(trade, "entry_signal", "") or "").strip().upper()
                or None
            ),
            entry_bar_at=(
                str(getattr(trade, "entry_bar_at", "") or "").strip()
                or None
            ),
            entry_at=getattr(trade, "created_at", None),
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
