from backtest.trade import Trade


class PaperTrading:

    def execute(self, order, candle):
        """Simulate an order exit using the candle close."""
        side = str(order.side).upper()
        direction = -1 if side in {"SELL", "SHORT"} else 1
        pnl = (candle.close - order.price) * order.quantity * direction
        denominator = order.price * order.quantity
        pnl_percent = (pnl / denominator) * 100 if denominator else 0.0

        return Trade(
            symbol=order.symbol,
            entry_date=order.timestamp,
            exit_date=candle.timestamp,
            entry_price=order.price,
            exit_price=candle.close,
            quantity=order.quantity,
            side=order.side,
            pnl=pnl,
            pnl_percent=pnl_percent,
            stoploss=order.stoploss,
            target=order.target2,
            strategy=order.strategy,
        )
