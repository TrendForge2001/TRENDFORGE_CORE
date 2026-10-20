"""R72.5.2 multi-strategy technical evaluation engine.

This module turns the declarative R72.5.1 registry into deterministic,
explainable strategy evaluations.  It does not place paper or broker orders.
Ambiguous notebook strategies are intentionally returned as review-required
instead of being silently reinterpreted.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable

import pandas as pd

from scanner.strategy_registry import get_strategy, list_strategies

ENGINE_VERSION = "R72.5.2-v1"

REVIEW_REQUIRED = frozenset(
    {
        "tf_intraday_supertrend_vwap_pivots",
        "tf_swing_macd_trend",
        "tf_medium_ema50_100",
        "tf_long_ema100_200",
        "tf_rsi_mean_reversion",
    }
)

CONFIRMATION_ONLY = frozenset({"tf_rsi_momentum_confirmation"})


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    mode: str
    interval: str


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _gt(row: pd.Series, left: str, right: str) -> bool:
    a = _finite(row.get(left))
    b = _finite(row.get(right))
    return bool(a is not None and b is not None and a > b)


def _gte_value(row: pd.Series, key: str, value: float) -> bool:
    number = _finite(row.get(key))
    return bool(number is not None and number >= value)


def _lte_value(row: pd.Series, key: str, value: float) -> bool:
    number = _finite(row.get(key))
    return bool(number is not None and number <= value)


def _cross_above(previous: pd.Series, current: pd.Series, fast: str, slow: str) -> bool:
    p_fast = _finite(previous.get(fast))
    p_slow = _finite(previous.get(slow))
    c_fast = _finite(current.get(fast))
    c_slow = _finite(current.get(slow))
    if None in (p_fast, p_slow, c_fast, c_slow):
        return False
    return bool(p_fast <= p_slow and c_fast > c_slow)


def _cross_below(previous: pd.Series, current: pd.Series, fast: str, slow: str) -> bool:
    p_fast = _finite(previous.get(fast))
    p_slow = _finite(previous.get(slow))
    c_fast = _finite(current.get(fast))
    c_slow = _finite(current.get(slow))
    if None in (p_fast, p_slow, c_fast, c_slow):
        return False
    return bool(p_fast >= p_slow and c_fast < c_slow)


def _proximity(row: pd.Series, left: str, right: str, pct: float = 1.0) -> bool:
    a = _finite(row.get(left))
    b = _finite(row.get(right))
    if a is None or b is None or b == 0:
        return False
    return abs(a - b) / abs(b) * 100.0 <= pct


def _bool(row: pd.Series, key: str) -> bool:
    value = row.get(key)
    if isinstance(value, bool):
        return value
    number = _finite(value)
    if number is not None:
        return bool(number)
    return str(value or "").strip().lower() in {"true", "yes", "1", "bullish"}


def _volume_above(row: pd.Series, key: str = "VOL_SMA_20") -> bool:
    return _gt(row, "volume", key)


def _score(checks: dict[str, bool]) -> float:
    if not checks:
        return 0.0
    return round(sum(1 for value in checks.values() if value) / len(checks) * 100.0, 2)


def _risk(row: pd.Series, mode: str, reward_risk: float = 2.0) -> dict[str, float | None]:
    close = _finite(row.get("close"))
    atr = _finite(row.get("ATR"))
    result: dict[str, float | None] = {
        "entry": close,
        "stoploss": None,
        "target2": None,
        "reward_risk": reward_risk,
    }
    if close is None or close <= 0 or atr is None or atr <= 0:
        return result
    multiplier = {"intraday": 1.5, "swing": 2.0, "positional": 2.5}.get(mode, 2.0)
    stop = max(0.01, close - multiplier * atr)
    result["stoploss"] = round(stop, 6)
    result["target2"] = round(close + reward_risk * (close - stop), 6)
    return result


def _decision(
    *,
    strategy_id: str,
    checks: dict[str, bool],
    entry_required: tuple[str, ...],
    exit_now: bool,
    current: pd.Series,
    mode: str,
    reward_risk: float = 2.0,
    signal_override: str | None = None,
    limitations: tuple[str, ...] = (),
) -> dict[str, Any]:
    passed = all(checks.get(name, False) for name in entry_required)
    score = _score(checks)
    signal = signal_override or ("BUY" if passed else "EXIT" if exit_now else "HOLD")
    return {
        "strategy_id": strategy_id,
        "status": "evaluated",
        "signal": signal,
        "score": score,
        "checks": checks,
        "passed_checks": [name for name, value in checks.items() if value],
        "failed_checks": [name for name, value in checks.items() if not value],
        "risk": _risk(current, mode, reward_risk=reward_risk),
        "limitations": list(limitations),
    }


def _review_required(strategy_id: str) -> dict[str, Any]:
    strategy = get_strategy(strategy_id)
    return {
        "strategy_id": strategy_id,
        "status": "review_required",
        "signal": "REVIEW_REQUIRED",
        "score": 0.0,
        "checks": {},
        "passed_checks": [],
        "failed_checks": [],
        "risk": {},
        "limitations": list(strategy.get("ambiguities") or [])
        or ["Notebook wording requires an explicit execution interpretation."],
    }


def _ema9_20(previous: pd.Series, current: pd.Series, ctx: EvaluationContext) -> dict[str, Any]:
    checks = {
        "ema9_cross_above_ema20": _cross_above(previous, current, "EMA_9", "EMA_20"),
        "rsi14_gte_60": _gte_value(current, "RSI_14", 60.0),
        "volume_above_ma20": _volume_above(current),
    }
    stamp = pd.Timestamp(current.name)
    if ctx.mode == "intraday" and stamp is not pd.NaT:
        try:
            local = stamp.tz_convert("Asia/Kolkata") if stamp.tzinfo else stamp
            checks["entry_after_0945_ist"] = (local.hour, local.minute) >= (9, 45)
        except Exception:
            checks["entry_after_0945_ist"] = False
    else:
        checks["entry_after_0945_ist"] = True
    return _decision(
        strategy_id="tf_intraday_ema9_20_momentum",
        checks=checks,
        entry_required=tuple(checks),
        exit_now=_cross_below(previous, current, "EMA_9", "EMA_20")
        or _lte_value(current, "RSI_14", 40.0),
        current=current,
        mode=ctx.mode,
        reward_risk=1.5,
    )


def _ema20_50(previous: pd.Series, current: pd.Series, ctx: EvaluationContext, strategy_id: str) -> dict[str, Any]:
    checks = {
        "ema20_cross_above_ema50": _cross_above(previous, current, "EMA_20", "EMA_50"),
        "close_within_1pct_ema20": _proximity(current, "close", "EMA_20", 1.0),
        "rsi14_gt_60": bool((_finite(current.get("RSI_14")) or -1.0) > 60.0),
        "volume_above_ma20": _volume_above(current),
    }
    if ctx.mode == "intraday":
        stamp = pd.Timestamp(current.name)
        try:
            local = stamp.tz_convert("Asia/Kolkata") if stamp.tzinfo else stamp
            checks["entry_after_0945_ist"] = (local.hour, local.minute) >= (9, 45)
        except Exception:
            checks["entry_after_0945_ist"] = False
    return _decision(
        strategy_id=strategy_id,
        checks=checks,
        entry_required=tuple(checks),
        exit_now=_cross_below(previous, current, "EMA_20", "EMA_50"),
        current=current,
        mode=ctx.mode,
        reward_risk=1.5 if ctx.mode == "intraday" else 2.0,
        limitations=(
            "Swing notebook also mentions bearish candle reversal and persistent low-volume exits; those undefined persistence/reversal semantics are not used for entry ranking.",
        ) if ctx.mode == "swing" else (),
    )


def _vwma9_26(previous: pd.Series, current: pd.Series, ctx: EvaluationContext, strategy_id: str) -> dict[str, Any]:
    checks = {
        "vwma9_cross_above_vwma26": _cross_above(previous, current, "VWMA_9", "VWMA_26"),
        "close_within_1pct_vwma9": _proximity(current, "close", "VWMA_9", 1.0),
        "rsi14_gt_60": bool((_finite(current.get("RSI_14")) or -1.0) > 60.0),
        "volume_above_ma20": _volume_above(current),
    }
    return _decision(
        strategy_id=strategy_id,
        checks=checks,
        entry_required=tuple(checks),
        exit_now=_cross_below(previous, current, "VWMA_9", "VWMA_26")
        or _lte_value(current, "RSI_14", 40.0),
        current=current,
        mode=ctx.mode,
        reward_risk=1.5 if ctx.mode == "intraday" else 2.0,
    )


def _golden_cross(previous: pd.Series, current: pd.Series, ctx: EvaluationContext) -> dict[str, Any]:
    checks = {"ema50_cross_above_ema200": _cross_above(previous, current, "EMA_50", "EMA_200")}
    return _decision(
        strategy_id="tf_golden_cross_50_200",
        checks=checks,
        entry_required=tuple(checks),
        exit_now=_cross_below(previous, current, "EMA_50", "EMA_200"),
        current=current,
        mode=ctx.mode,
    )


def _rsi_confirmation(previous: pd.Series, current: pd.Series, ctx: EvaluationContext) -> dict[str, Any]:
    bullish = {
        "rsi14_gte_60": _gte_value(current, "RSI_14", 60.0),
        "ema20_above_ema50": _gt(current, "EMA_20", "EMA_50"),
        "volume_above_ma20": _volume_above(current),
    }
    bearish = (
        _lte_value(current, "RSI_14", 40.0)
        and _gt(current, "EMA_50", "EMA_20")
        and _volume_above(current)
    )
    if all(bullish.values()):
        signal = "CONFIRM_BUY"
    elif bearish:
        signal = "CONFIRM_SELL"
    else:
        signal = "NEUTRAL"
    return _decision(
        strategy_id="tf_rsi_momentum_confirmation",
        checks=bullish,
        entry_required=tuple(bullish),
        exit_now=False,
        current=current,
        mode=ctx.mode,
        signal_override=signal,
        limitations=("Confirmation-only; never creates a standalone candidate.",),
    )


def _supertrend_template(previous: pd.Series, current: pd.Series, ctx: EvaluationContext) -> dict[str, Any]:
    checks = {
        "supertrend_bullish": (_finite(current.get("SUPERTREND_DIR")) or 0.0) > 0,
        "rsi14_gt_55": bool((_finite(current.get("RSI_14")) or -1.0) > 55.0),
    }
    return _decision(
        strategy_id="tpl_supertrend_rsi",
        checks=checks,
        entry_required=tuple(checks),
        exit_now=(_finite(current.get("SUPERTREND_DIR")) or 0.0) < 0
        or _lte_value(current, "RSI_14", 50.0),
        current=current,
        mode=ctx.mode,
    )


def _ema_adx_template(previous: pd.Series, current: pd.Series, ctx: EvaluationContext) -> dict[str, Any]:
    checks = {
        "ema20_above_ema50": _gt(current, "EMA_20", "EMA_50"),
        "adx_gte_20": _gte_value(current, "ADX", 20.0),
        "plus_di_above_minus_di": _gt(current, "+DI", "-DI"),
    }
    return _decision(
        strategy_id="tpl_ema_adx_trend",
        checks=checks,
        entry_required=tuple(checks),
        exit_now=_gt(current, "EMA_50", "EMA_20") or _gt(current, "-DI", "+DI"),
        current=current,
        mode=ctx.mode,
    )


def _vwap_breakout_template(previous: pd.Series, current: pd.Series, ctx: EvaluationContext) -> dict[str, Any]:
    fresh = _bool(current, "BREAKOUT") and not _bool(previous, "BREAKOUT")
    checks = {
        "fresh_breakout": fresh,
        "close_above_vwap": _gt(current, "close", "VWAP"),
        "rvol_gt_1_2": bool((_finite(current.get("RVOL")) or 0.0) > 1.2),
    }
    return _decision(
        strategy_id="tpl_vwap_volume_breakout",
        checks=checks,
        entry_required=tuple(checks),
        exit_now=not _gt(current, "close", "VWAP"),
        current=current,
        mode=ctx.mode,
    )


def _macd_template(previous: pd.Series, current: pd.Series, ctx: EvaluationContext) -> dict[str, Any]:
    checks = {
        "macd_cross_above_signal": _cross_above(previous, current, "MACD", "MACD_SIGNAL"),
        "ema20_above_ema50": _gt(current, "EMA_20", "EMA_50"),
    }
    return _decision(
        strategy_id="tpl_macd_trend_confirmation",
        checks=checks,
        entry_required=tuple(checks),
        exit_now=_cross_below(previous, current, "MACD", "MACD_SIGNAL"),
        current=current,
        mode=ctx.mode,
    )


def _bollinger_template(previous: pd.Series, current: pd.Series, ctx: EvaluationContext) -> dict[str, Any]:
    checks = {
        "close_above_upper_band": _gt(current, "close", "BB_UPPER"),
        "rvol_gte_1_2": _gte_value(current, "RVOL", 1.2),
    }
    return _decision(
        strategy_id="tpl_bollinger_breakout",
        checks=checks,
        entry_required=tuple(checks),
        exit_now=not _gt(current, "close", "BB_MID"),
        current=current,
        mode=ctx.mode,
        limitations=("Template defines elevated relative volume as RVOL >= 1.2 in R72.5.2.",),
    )


def _volume_breakout_template(previous: pd.Series, current: pd.Series, ctx: EvaluationContext) -> dict[str, Any]:
    checks = {
        "fresh_breakout": _bool(current, "BREAKOUT") and not _bool(previous, "BREAKOUT"),
        "volume_above_ma20": _volume_above(current),
        "rvol_gt_1_2": bool((_finite(current.get("RVOL")) or 0.0) > 1.2),
    }
    return _decision(
        strategy_id="tpl_volume_breakout",
        checks=checks,
        entry_required=tuple(checks),
        exit_now=_bool(current, "BREAKDOWN"),
        current=current,
        mode=ctx.mode,
    )


def _high52_template(previous: pd.Series, current: pd.Series, ctx: EvaluationContext) -> dict[str, Any]:
    distance = _finite(current.get("DIST_52W_HIGH_PCT"))
    checks = {
        "within_5pct_52week_high": bool(distance is not None and 0.0 <= distance <= 5.0),
        "rsi14_gte_60": _gte_value(current, "RSI_14", 60.0),
        "volume_above_ma20": _volume_above(current),
    }
    return _decision(
        strategy_id="tpl_52week_high_momentum",
        checks=checks,
        entry_required=tuple(checks),
        exit_now=False,
        current=current,
        mode=ctx.mode,
    )


_EVALUATORS: dict[str, Callable[[pd.Series, pd.Series, EvaluationContext], dict[str, Any]]] = {
    "tf_intraday_ema9_20_momentum": _ema9_20,
    "tf_intraday_ema20_50_rsi_volume": lambda p, c, x: _ema20_50(p, c, x, "tf_intraday_ema20_50_rsi_volume"),
    "tf_intraday_vwma9_26_rsi_volume": lambda p, c, x: _vwma9_26(p, c, x, "tf_intraday_vwma9_26_rsi_volume"),
    "tf_swing_ema20_50_rsi_volume": lambda p, c, x: _ema20_50(p, c, x, "tf_swing_ema20_50_rsi_volume"),
    "tf_swing_vwma9_26_rsi_volume": lambda p, c, x: _vwma9_26(p, c, x, "tf_swing_vwma9_26_rsi_volume"),
    "tf_golden_cross_50_200": _golden_cross,
    "tf_rsi_momentum_confirmation": _rsi_confirmation,
    "tpl_supertrend_rsi": _supertrend_template,
    "tpl_ema_adx_trend": _ema_adx_template,
    "tpl_vwap_volume_breakout": _vwap_breakout_template,
    "tpl_macd_trend_confirmation": _macd_template,
    "tpl_bollinger_breakout": _bollinger_template,
    "tpl_volume_breakout": _volume_breakout_template,
    "tpl_52week_high_momentum": _high52_template,
}


class MultiStrategyEngine:
    VERSION = ENGINE_VERSION

    def strategies(
        self,
        *,
        mode: str,
        source: str = "all",
        strategy_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        mode_key = str(mode or "").strip().lower()
        source_key = str(source or "all").strip().lower()
        if mode_key not in {"intraday", "swing", "positional"}:
            raise ValueError("mode must be intraday, swing or positional")
        if source_key not in {"all", "user_notebook", "template"}:
            raise ValueError("source must be all, user_notebook or template")
        rows = list_strategies(mode=mode_key)
        if source_key != "all":
            rows = [row for row in rows if row.get("source") == source_key]
        if strategy_ids:
            requested = {str(item).strip().lower() for item in strategy_ids if str(item).strip()}
            unknown = sorted(requested.difference({row["strategy_id"] for row in rows}))
            if unknown:
                raise ValueError(
                    "strategy_ids are unknown or incompatible with mode/source: "
                    + ", ".join(unknown)
                )
            rows = [row for row in rows if row["strategy_id"] in requested]
        if not rows:
            raise ValueError("No strategies match the requested mode/source")
        return rows

    def evaluate(
        self,
        frame: pd.DataFrame,
        *,
        mode: str,
        interval: str,
        source: str = "all",
        strategy_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(frame, pd.DataFrame) or len(frame) < 2:
            raise ValueError("At least two completed indicator bars are required")
        previous = frame.iloc[-2]
        current = frame.iloc[-1]
        context = EvaluationContext(mode=str(mode).lower(), interval=interval)
        strategies = self.strategies(mode=context.mode, source=source, strategy_ids=strategy_ids)

        evaluations: list[dict[str, Any]] = []
        for strategy in strategies:
            strategy_id = strategy["strategy_id"]
            if strategy_id in REVIEW_REQUIRED:
                result = _review_required(strategy_id)
            else:
                evaluator = _EVALUATORS.get(strategy_id)
                if evaluator is None:
                    result = {
                        "strategy_id": strategy_id,
                        "status": "not_implemented",
                        "signal": "NOT_IMPLEMENTED",
                        "score": 0.0,
                        "checks": {},
                        "passed_checks": [],
                        "failed_checks": [],
                        "risk": {},
                        "limitations": ["No deterministic evaluator is registered yet."],
                    }
                else:
                    result = evaluator(previous, current, context)
            result["name"] = strategy.get("name")
            result["source"] = strategy.get("source")
            result["family"] = strategy.get("family")
            result["paper_eligible"] = bool(strategy.get("paper_eligible"))
            result["confirmation_only"] = strategy_id in CONFIRMATION_ONLY
            evaluations.append(result)

        buys = [
            item for item in evaluations
            if item.get("status") == "evaluated"
            and item.get("signal") == "BUY"
            and not item.get("confirmation_only")
        ]
        confirms = [
            item for item in evaluations
            if item.get("status") == "evaluated"
            and item.get("signal") == "CONFIRM_BUY"
        ]
        exits = [
            item for item in evaluations
            if item.get("status") == "evaluated"
            and item.get("signal") in {"EXIT", "CONFIRM_SELL"}
        ]
        notebook_buys = [item for item in buys if item.get("source") == "user_notebook"]
        template_buys = [item for item in buys if item.get("source") == "template"]

        if buys:
            mean_score = sum(float(item.get("score") or 0.0) for item in buys) / len(buys)
            consensus_score = min(
                100.0,
                mean_score * 0.75
                + min(len(buys), 3) * 5.0
                + min(len(confirms), 2) * 5.0,
            )
        else:
            mean_score = 0.0
            consensus_score = min(25.0, len(confirms) * 10.0)

        if notebook_buys and len(buys) >= 2 and consensus_score >= 80.0:
            consensus = "STRONG_BUY"
        elif buys:
            consensus = "BUY"
        elif confirms:
            consensus = "WATCH"
        elif exits:
            consensus = "EXIT"
        else:
            consensus = "NEUTRAL"

        primary = max(buys, key=lambda item: float(item.get("score") or 0.0)) if buys else None
        return {
            "consensus": consensus,
            "consensus_score": round(consensus_score, 2),
            "buy_strategy_count": len(buys),
            "notebook_buy_count": len(notebook_buys),
            "template_buy_count": len(template_buys),
            "bullish_confirmation_count": len(confirms),
            "exit_strategy_count": len(exits),
            "mean_buy_score": round(mean_score, 2),
            "buy_strategy_ids": [item["strategy_id"] for item in buys],
            "confirmation_strategy_ids": [item["strategy_id"] for item in confirms],
            "primary_strategy_id": primary.get("strategy_id") if primary else None,
            "risk": dict(primary.get("risk") or {}) if primary else {},
            "evaluations": evaluations,
        }

    def readiness(self) -> dict[str, Any]:
        executable = sorted(_EVALUATORS)
        return {
            "status": "ready",
            "version": self.VERSION,
            "supported_modes": ["intraday", "swing", "positional"],
            "executable_strategy_ids": executable,
            "review_required_strategy_ids": sorted(REVIEW_REQUIRED),
            "confirmation_only_strategy_ids": sorted(CONFIRMATION_ONLY),
            "paper_execution_allowed": False,
            "broker_orders_allowed": False,
        }


__all__ = [
    "CONFIRMATION_ONLY",
    "ENGINE_VERSION",
    "MultiStrategyEngine",
    "REVIEW_REQUIRED",
]
