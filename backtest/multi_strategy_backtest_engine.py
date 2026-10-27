"""R72.5.3 realistic backtesting adapter for one registered strategy."""
from __future__ import annotations

from typing import Any

import pandas as pd

from backtest.technical_realistic_engine import (
    TechnicalRealisticBacktestEngine,
    TechnicalRealisticConfig,
    TechnicalRealisticResult,
)
from scanner.multi_strategy_engine import (
    CONFIRMATION_ONLY,
    REVIEW_REQUIRED,
    MultiStrategyEngine,
)
from scanner.strategy_registry import get_strategy


class MultiStrategyBacktestEngine:
    """Backtest exactly one standalone executable registered strategy.

    Indicator columns must already be present in the frame. Strategy decisions
    are evaluated using the same R72.5.2 engine used by the live scanner.
    """

    VERSION = "R72.5.3-v1"

    def __init__(
        self,
        *,
        strategy_engine: MultiStrategyEngine | None = None,
    ) -> None:
        self.strategy_engine = strategy_engine or MultiStrategyEngine()

    @staticmethod
    def _pair(previous: pd.Series, current: pd.Series) -> pd.DataFrame:
        frame = pd.DataFrame([previous.to_dict(), current.to_dict()])
        frame.index = pd.Index([previous.name, current.name])
        return frame

    def _evaluation(
        self,
        previous: pd.Series,
        current: pd.Series,
        *,
        strategy_id: str,
        mode: str,
        interval: str,
    ) -> dict[str, Any]:
        result = self.strategy_engine.evaluate(
            self._pair(previous, current),
            mode=mode,
            interval=interval,
            source="all",
            strategy_ids=[strategy_id],
        )
        rows = result.get("evaluations") or []
        if len(rows) != 1:
            raise RuntimeError(
                f"Expected one strategy evaluation for {strategy_id}"
            )
        return dict(rows[0])

    def validate_strategy(
        self,
        strategy_id: str,
        *,
        mode: str,
    ) -> dict[str, Any]:
        strategy = get_strategy(strategy_id)
        if mode not in (strategy.get("modes") or []):
            raise ValueError(
                f"{strategy_id} is not registered for mode {mode}"
            )
        if strategy_id in REVIEW_REQUIRED:
            raise ValueError(
                f"{strategy_id} requires notebook-rule review before backtesting"
            )
        if strategy_id in CONFIRMATION_ONLY:
            raise ValueError(
                f"{strategy_id} is confirmation-only and cannot be backtested standalone"
            )
        readiness = self.strategy_engine.readiness()
        executable = set(readiness.get("executable_strategy_ids") or [])
        if strategy_id not in executable:
            raise ValueError(
                f"{strategy_id} does not have a deterministic R72.5.2 evaluator"
            )
        return strategy

    def run(
        self,
        frame: pd.DataFrame,
        *,
        strategy_id: str,
        mode: str,
        interval: str,
        initial_capital: float = 100_000.0,
        cost_bps: float = 0.0,
        slippage_bps: float = 0.0,
    ) -> TechnicalRealisticResult:
        mode_key = str(mode or "").strip().lower()
        interval_key = str(interval or "").strip().lower()
        definition = self.validate_strategy(strategy_id, mode=mode_key)
        if interval_key not in definition["intervals"]:
            raise ValueError("Strategy candle interval mismatch")

        def entry_rule(previous: pd.Series, current: pd.Series):
            row = self._evaluation(
                previous,
                current,
                strategy_id=strategy_id,
                mode=mode_key,
                interval=interval_key,
            )
            if (
                row.get("status") == "evaluated"
                and row.get("signal") == ("SELL" if definition.get("direction") == "SHORT" else "BUY")
            ):
                risk = dict(row.get("risk") or {})
                if (
                    risk.get("entry") is not None
                    and risk.get("stoploss") is not None
                ):
                    return {
                        "signal": row["signal"],
                        "strategy_id": strategy_id,
                        "entry": risk.get("entry"),
                        "stoploss": risk.get("stoploss"),
                        "target2": risk.get("target2"),
                        "reward_risk": risk.get("reward_risk") or 2.0,
                    }
            return None

        def exit_rule(previous: pd.Series, current: pd.Series):
            row = self._evaluation(
                previous,
                current,
                strategy_id=strategy_id,
                mode=mode_key,
                interval=interval_key,
            )
            if (
                row.get("status") == "evaluated"
                and row.get("signal") == "EXIT"
            ):
                return {
                    "signal": "EXIT",
                    "strategy_id": strategy_id,
                    "reason": "STRATEGY_EXIT",
                }
            return None

        engine = TechnicalRealisticBacktestEngine(
            TechnicalRealisticConfig(
                initial_capital=float(initial_capital),
                cost_bps=float(cost_bps),
                slippage_bps=float(slippage_bps),
                force_final_exit=True,
                same_bar_priority="stop",
                intraday_exit_hour=15,
                intraday_exit_minute=0,
            )
        )
        return engine.run(
            frame,
            entry_rule=entry_rule,
            exit_rule=exit_rule,
            mode=mode_key,
        )

    def readiness(self) -> dict[str, Any]:
        strategy_readiness = self.strategy_engine.readiness()
        return {
            "status": "ready",
            "version": self.VERSION,
            "execution_engine": {
                "name": "TechnicalRealisticBacktestEngine",
                "version": TechnicalRealisticBacktestEngine.ENGINE_VERSION,
                "execution_model": TechnicalRealisticBacktestEngine.EXECUTION_MODEL,
                "same_bar_priority": "stop",
                "intraday_forced_exit_ist": "15:00",
                "position_sizing": TechnicalRealisticBacktestEngine.POSITION_SIZING,
            },
            "backtestable_strategy_ids": sorted(
                set(strategy_readiness.get("executable_strategy_ids") or [])
                - set(REVIEW_REQUIRED)
                - set(CONFIRMATION_ONLY)
            ),
            "excluded_review_required": sorted(REVIEW_REQUIRED),
            "excluded_confirmation_only": sorted(CONFIRMATION_ONLY),
            "paper_orders_created": False,
            "broker_orders_allowed": False,
        }


__all__ = ["MultiStrategyBacktestEngine"]
