"""Reuse causal trigger/fill accounting with the daily VWMA strategy rules."""

from types import SimpleNamespace

from backtest.ema_pivot_engine import EmaPivotBacktestEngine
from scanner.vwma_yearly import INDICATORS, VERSION, entry_plan, evaluate


class VwmaYearlyBacktestEngine(EmaPivotBacktestEngine):
    VERSION = VERSION

    def setup_for(self, strategy_id):
        return SimpleNamespace(direction=1, trailing=False)

    def indicator_keys(self, setup):
        return INDICATORS

    def evaluate(self, previous, current, context, strategy_id):
        return evaluate(previous, current, context, strategy_id)

    def plan(self, setup, row, *, mode, tick_size, entry=None):
        return entry_plan(row, tick_size=tick_size, entry=entry)

    def move_stop_after_partial(self, setup):
        return False
