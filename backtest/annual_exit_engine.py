"""Native long entries with the shared annual conditional-exit simulator."""

import pandas as pd

from backtest.vwma_yearly_engine import VwmaYearlyBacktestEngine
from scanner.annual_exit_policy import AFFECTED, VERSION, plan_for
from scanner.portfolio_policy import number
from scanner.strategy_registry import get_strategy


class AnnualExitBacktestEngine(VwmaYearlyBacktestEngine):
    VERSION = VERSION

    def validate(self, strategy_id, mode, interval, frames):
        from backtest.multi_strategy_backtest_engine import MultiStrategyBacktestEngine

        if strategy_id not in AFFECTED:
            raise ValueError("Strategy does not use the shared annual exit policy")
        definition = MultiStrategyBacktestEngine().validate_strategy(
            strategy_id, mode=mode
        )
        if interval not in definition["intervals"]:
            raise ValueError("Strategy candle interval mismatch")
        for frame in frames.values():
            if "FIB_YEAR_P" not in frame or not frame.FIB_YEAR_P.notna().any():
                raise ValueError(
                    "Complete daily prior-year history is required for annual exits"
                )
            if mode == "intraday":
                stamps = pd.DatetimeIndex(frame.index)
                stamps = (
                    stamps.tz_localize("Asia/Kolkata")
                    if stamps.tz is None
                    else stamps.tz_convert("Asia/Kolkata")
                )
                # Missing square-off candles must not fabricate an overnight fill.
                for date in set(stamps.date[:-1]):
                    if (
                        date != stamps[-1].date()
                        or (stamps[-1].hour, stamps[-1].minute) >= (15, 0)
                    ) and not any(
                        (x.hour, x.minute) == (15, 0)
                        for x in stamps[stamps.date == date]
                    ):
                        raise ValueError(
                            "Intraday history is missing its "
                            "15:00 IST square-off candle"
                        )

    def indicator_keys(self, strategy_id):
        return get_strategy(strategy_id)["indicators"]

    def make_plan(self, strategy_id, row, tick, fill):
        return plan_for(strategy_id, row, tick_size=tick, entry=fill)

    def entry_raw(self, candidate, row, stamp, mode):
        signal_at = pd.Timestamp(candidate["entry_signal_at"])
        if mode == "intraday" and (
            stamp.date() != signal_at.date()
            or (stamp - signal_at).total_seconds() != 900
            or not (9, 15) <= (stamp.hour, stamp.minute) < (15, 0)
        ):
            return None
        raw = float(row["open"])
        trigger = number(candidate["entry_plan"].get("entry_trigger"))
        if candidate["entry_plan"].get("entry_order_type") == "NEXT_CANDLE_BREAKOUT":
            if trigger is None or float(row["high"]) < trigger:
                return None
            raw = max(raw, trigger)
        return raw

    def evaluate_pair(self, previous, row, context, strategy_id):
        from scanner.multi_strategy_engine import _EVALUATORS

        return _EVALUATORS[strategy_id](previous, row, context)
