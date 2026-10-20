"""Risk-governed scanner-to-paper entry handoff."""
from __future__ import annotations

from datetime import datetime
import math
import os
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo


class PaperAutoEntryService:
    """Convert completed scanner picks into tightly governed paper entries.

    R67.2 is deliberately paper-only. It never calls broker order endpoints.
    Execution requires BOTH the environment feature flag and an explicit
    per-scan request opt-in.
    """

    MARKET_TZ = ZoneInfo("Asia/Kolkata")

    def __init__(
        self,
        paper_service: Any,
        *,
        enabled: bool | None = None,
        notifications: Any | None = None,
    ) -> None:
        self.paper_service = paper_service
        self.notifications = notifications
        self.enabled = (
            self._env_enabled(
                "TRENDFORGE_PAPER_AUTO_ENTRY_ENABLED",
                False,
            )
            if enabled is None
            else bool(enabled)
        )
        self.capital = self._env_float(
            "TRENDFORGE_PAPER_CAPITAL",
            100000.0,
            minimum=1000.0,
            maximum=1000000000.0,
        )
        self.risk_per_trade_percent = self._env_float(
            "TRENDFORGE_PAPER_RISK_PER_TRADE_PERCENT",
            1.0,
            minimum=0.1,
            maximum=5.0,
        )
        self.max_daily_loss_percent = self._env_float(
            "TRENDFORGE_PAPER_MAX_DAILY_LOSS_PERCENT",
            3.0,
            minimum=0.1,
            maximum=20.0,
        )
        self.max_open_positions = self._env_int(
            "TRENDFORGE_PAPER_MAX_OPEN_POSITIONS",
            5,
            minimum=1,
            maximum=25,
        )
        self.max_capital_per_trade_percent = self._env_float(
            "TRENDFORGE_PAPER_MAX_CAPITAL_PER_TRADE_PERCENT",
            20.0,
            minimum=1.0,
            maximum=100.0,
        )
        self.minimum_rr = self._env_float(
            "TRENDFORGE_PAPER_MINIMUM_RR",
            2.0,
            minimum=1.0,
            maximum=10.0,
        )
        self.minimum_score = self._env_float(
            "TRENDFORGE_PAPER_AUTO_ENTRY_MIN_SCORE",
            90.0,
            minimum=0.0,
            maximum=100.0,
        )
        self.minimum_confidence = self._env_float(
            "TRENDFORGE_PAPER_AUTO_ENTRY_MIN_CONFIDENCE",
            60.0,
            minimum=0.0,
            maximum=100.0,
        )
        self.max_entries_per_scan = self._env_int(
            "TRENDFORGE_PAPER_AUTO_ENTRY_MAX_PER_SCAN",
            1,
            minimum=1,
            maximum=10,
        )
        raw_signals = os.getenv(
            "TRENDFORGE_PAPER_AUTO_ENTRY_SIGNALS",
            "STRONG BUY,BUY",
        )
        self.allowed_signals = tuple(
            dict.fromkeys(
                str(value).strip().upper()
                for value in raw_signals.split(",")
                if str(value).strip()
            )
        ) or ("STRONG BUY", "BUY")

        self.processed_scans = 0
        self.execution_attempts = 0
        self.opened_count = 0
        self.rejected_count = 0
        self.last_run_id: str | None = None
        self.last_status: str | None = None
        self.last_processed_at: str | None = None
        self.last_result: dict[str, Any] | None = None

    @staticmethod
    def _env_enabled(name: str, default: bool) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return str(value).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    @staticmethod
    def _env_float(
        name: str,
        default: float,
        *,
        minimum: float,
        maximum: float,
    ) -> float:
        raw = os.getenv(name)
        try:
            value = float(raw) if raw is not None else float(default)
        except (TypeError, ValueError):
            value = float(default)
        if not math.isfinite(value):
            value = float(default)
        return min(max(value, minimum), maximum)

    @staticmethod
    def _env_int(
        name: str,
        default: int,
        *,
        minimum: int,
        maximum: int,
    ) -> int:
        raw = os.getenv(name)
        try:
            value = int(raw) if raw is not None else int(default)
        except (TypeError, ValueError):
            value = int(default)
        return min(max(value, minimum), maximum)

    @staticmethod
    def _value(source: Any, key: str, default: Any = None) -> Any:
        if isinstance(source, dict):
            return source.get(key, default)
        return getattr(source, key, default)

    @classmethod
    def _number(
        cls,
        source: Any,
        key: str,
        default: float = 0.0,
    ) -> float:
        value = cls._value(source, key, default)
        try:
            number = float(value or 0.0)
        except (TypeError, ValueError):
            return float(default)
        return number if math.isfinite(number) else float(default)

    @classmethod
    def _signal_name(cls, candidate: dict[str, Any]) -> str:
        signal = candidate.get("signal")
        if isinstance(signal, str):
            return signal.strip().upper()
        return str(
            cls._value(signal, "signal", "HOLD") or "HOLD"
        ).strip().upper()

    @classmethod
    def _risk_metrics(
        cls,
        candidate: dict[str, Any],
    ) -> dict[str, float]:
        signal = candidate.get("signal")
        engines = candidate.get("engines")
        risk_engine = (
            engines.get("Risk Engine")
            if isinstance(engines, dict)
            else None
        )
        metrics = (
            risk_engine.get("metrics")
            if isinstance(risk_engine, dict)
            else None
        )
        metrics = metrics if isinstance(metrics, dict) else {}

        def first_number(key: str) -> float:
            from_signal = cls._number(signal, key, 0.0)
            if from_signal > 0:
                return from_signal
            return cls._number(metrics, key, 0.0)

        return {
            "entry": first_number("entry"),
            "stoploss": first_number("stoploss"),
            "target2": first_number("target2"),
            "scanner_quantity": max(
                0.0,
                first_number("quantity"),
            ),
        }

    @classmethod
    def _score_confidence(
        cls,
        candidate: dict[str, Any],
    ) -> tuple[float, float]:
        signal = candidate.get("signal")
        score = cls._number(signal, "overall_score", 0.0)
        if score <= 0:
            score = cls._number(
                candidate,
                "ranking_score",
                cls._number(candidate, "score", 0.0),
            )

        confidence = cls._number(signal, "confidence", 0.0)
        if confidence <= 0:
            confidence = cls._number(
                candidate,
                "confidence",
                0.0,
            )
        return score, confidence

    def _repository(self) -> Any | None:
        runtime = getattr(self.paper_service, "runtime", None)
        return getattr(runtime, "trades", None)

    def _open_symbols(self) -> set[str]:
        runtime = getattr(self.paper_service, "runtime", None)
        portfolio = getattr(runtime, "portfolio", None)
        positions = getattr(portfolio, "positions", {})
        if not isinstance(positions, dict):
            return set()
        return {
            str(symbol).strip().upper()
            for symbol in positions
            if str(symbol).strip()
        }

    def _daily_realized_pnl(self, date_text: str) -> float:
        repository = self._repository()
        method = getattr(
            repository,
            "realized_pnl_for_entry_date",
            None,
        )
        if not callable(method):
            return 0.0
        try:
            value = float(method(date_text) or 0.0)
        except (TypeError, ValueError):
            return 0.0
        return value if math.isfinite(value) else 0.0

    def _daily_realized_loss(self, date_text: str) -> float:
        repository = self._repository()
        method = getattr(
            repository,
            "realized_loss_for_entry_date",
            None,
        )
        if callable(method):
            try:
                value = float(method(date_text) or 0.0)
            except (TypeError, ValueError):
                return 0.0
            return max(0.0, value) if math.isfinite(value) else 0.0

        # Backward-compatible fallback for repository doubles/older stores.
        return abs(min(0.0, self._daily_realized_pnl(date_text)))

    def _traded_today(
        self,
        symbol: str,
        date_text: str,
    ) -> bool:
        repository = self._repository()
        method = getattr(
            repository,
            "has_trade_on_entry_date",
            None,
        )
        return bool(
            method(symbol, date_text)
            if callable(method)
            else False
        )

    def _quantity(
        self,
        entry: float,
        stoploss: float,
    ) -> tuple[int, float, float]:
        risk_per_share = entry - stoploss
        if risk_per_share <= 0:
            return 0, 0.0, 0.0

        risk_budget = (
            self.capital
            * self.risk_per_trade_percent
            / 100.0
        )
        max_trade_value = (
            self.capital
            * self.max_capital_per_trade_percent
            / 100.0
        )
        risk_qty = int(risk_budget / risk_per_share)
        capital_qty = int(max_trade_value / entry)
        quantity = max(0, min(risk_qty, capital_qty))
        return quantity, risk_budget, max_trade_value

    def evaluate_candidate(
        self,
        candidate: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or datetime.now(self.MARKET_TZ)
        symbol = str(candidate.get("symbol") or "").strip().upper()
        signal_name = self._signal_name(candidate)
        score, confidence = self._score_confidence(candidate)
        risk = self._risk_metrics(candidate)
        entry = risk["entry"]
        stoploss = risk["stoploss"]
        target2 = risk["target2"]

        reasons: list[str] = []

        if not symbol:
            reasons.append("symbol_missing")
        execution_eligible = candidate.get(
            "execution_eligible",
            candidate.get("eligible", False),
        )
        if not bool(execution_eligible):
            reasons.append("scanner_not_eligible")
        if candidate.get("error"):
            reasons.append("scanner_error")
        if signal_name not in self.allowed_signals:
            reasons.append("signal_not_allowed")
        if score < self.minimum_score:
            reasons.append("score_below_minimum")
        if confidence < self.minimum_confidence:
            reasons.append("confidence_below_minimum")
        if entry <= 0:
            reasons.append("entry_invalid")
        if stoploss <= 0 or stoploss >= entry:
            reasons.append("stoploss_invalid")
        if target2 <= entry:
            reasons.append("target_invalid")

        reward_risk = 0.0
        if (
            entry > 0
            and 0 < stoploss < entry
            and target2 > entry
        ):
            reward_risk = (
                (target2 - entry)
                / (entry - stoploss)
            )
            if reward_risk < self.minimum_rr:
                reasons.append("reward_risk_below_minimum")

        open_symbols = self._open_symbols()
        if symbol and symbol in open_symbols:
            reasons.append("position_already_open")
        if len(open_symbols) >= self.max_open_positions:
            reasons.append("maximum_open_positions_reached")

        date_text = current.astimezone(
            self.MARKET_TZ
        ).date().isoformat()
        if symbol and self._traded_today(symbol, date_text):
            reasons.append("symbol_already_traded_today")

        daily_realized = self._daily_realized_pnl(date_text)
        daily_loss = self._daily_realized_loss(date_text)
        daily_loss_limit = (
            self.capital
            * self.max_daily_loss_percent
            / 100.0
        )
        if daily_loss >= daily_loss_limit:
            reasons.append("maximum_daily_loss_reached")

        quantity, risk_budget, max_trade_value = self._quantity(
            entry,
            stoploss,
        )
        if quantity <= 0:
            reasons.append("position_size_zero")

        runtime = getattr(self.paper_service, "runtime", None)
        can_open = getattr(runtime, "_can_open", None)
        market_open = (
            bool(can_open(current))
            if callable(can_open)
            else True
        )
        if not market_open:
            reasons.append("outside_nse_entry_window")

        return {
            "symbol": symbol,
            "approved": not reasons,
            "reasons": list(dict.fromkeys(reasons)),
            "signal": signal_name,
            "score": round(score, 2),
            "confidence": round(confidence, 2),
            "entry": round(entry, 4),
            "stoploss": round(stoploss, 4),
            "target2": round(target2, 4),
            "reward_risk": round(reward_risk, 4),
            "quantity": quantity,
            "risk_budget": round(risk_budget, 2),
            "max_trade_value": round(max_trade_value, 2),
            "daily_realized_pnl": round(daily_realized, 2),
            "daily_loss": round(daily_loss, 2),
            "daily_loss_limit": round(daily_loss_limit, 2),
            "open_positions": len(open_symbols),
            "max_open_positions": self.max_open_positions,
            "market_entry_window_open": market_open,
            "paper_only": True,
            "broker_orders_allowed": False,
        }

    def _notify_result(
        self,
        result: dict[str, Any],
    ) -> None:
        method = getattr(
            self.notifications,
            "auto_entry_result",
            None,
        )
        if not callable(method):
            return
        try:
            method(result)
        except Exception:
            # Notification routing must never affect paper auto-entry.
            pass

    def process_scan(
        self,
        scan_result: dict[str, Any],
        *,
        run_id: str,
        execute_requested: bool,
        continuation: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or datetime.now(self.MARKET_TZ)
        self.processed_scans += 1
        self.last_run_id = str(run_id)
        self.last_processed_at = current.isoformat()

        if not execute_requested:
            result = {
                "status": "not_requested",
                "run_id": str(run_id),
                "enabled": self.enabled,
                "broker_orders_allowed": False,
                "opened": [],
                "evaluations": [],
            }
            self.last_status = result["status"]
            self.last_result = result
            self._notify_result(result)
            return result

        if not self.enabled:
            result = {
                "status": "disabled",
                "run_id": str(run_id),
                "enabled": False,
                "broker_orders_allowed": False,
                "opened": [],
                "evaluations": [],
            }
            self.last_status = result["status"]
            self.last_result = result
            self._notify_result(result)
            return result

        if continuation:
            result = {
                "status": "blocked",
                "run_id": str(run_id),
                "reason": "continuation_scan_not_execution_eligible",
                "enabled": True,
                "broker_orders_allowed": False,
                "opened": [],
                "evaluations": [],
            }
            self.last_status = result["status"]
            self.last_result = result
            self._notify_result(result)
            return result

        if str(scan_result.get("outcome") or "") != "completed":
            result = {
                "status": "blocked",
                "run_id": str(run_id),
                "reason": "scan_not_completed",
                "enabled": True,
                "broker_orders_allowed": False,
                "opened": [],
                "evaluations": [],
            }
            self.last_status = result["status"]
            self.last_result = result
            self._notify_result(result)
            return result

        if not bool(
            getattr(
                self.paper_service,
                "can_open_new_positions",
                False,
            )
        ):
            result = {
                "status": "blocked",
                "run_id": str(run_id),
                "reason": "paper_trading_not_ready",
                "enabled": True,
                "broker_orders_allowed": False,
                "opened": [],
                "evaluations": [],
            }
            self.last_status = result["status"]
            self.last_result = result
            self._notify_result(result)
            return result

        candidate_source = (
            scan_result.get("execution_top_picks")
            if isinstance(scan_result.get("execution_top_picks"), list)
            else scan_result.get("top_picks")
        )
        candidates = [
            item
            for item in (candidate_source or [])
            if isinstance(item, dict)
        ]

        evaluations: list[dict[str, Any]] = []
        opened: list[dict[str, Any]] = []

        for candidate in candidates:
            if len(opened) >= self.max_entries_per_scan:
                break

            evaluation = self.evaluate_candidate(
                candidate,
                now=current,
            )
            evaluations.append(evaluation)

            if not evaluation["approved"]:
                self.rejected_count += 1
                continue

            order = SimpleNamespace(
                symbol=evaluation["symbol"],
                side="BUY",
                quantity=evaluation["quantity"],
                price=evaluation["entry"],
                stoploss=evaluation["stoploss"],
                target2=evaluation["target2"],
                trade_mode=str(
                    candidate.get("technical_mode") or "intraday"
                ).strip().lower(),
            )

            self.execution_attempts += 1
            try:
                opened_result = self.paper_service.open(
                    order,
                    now=current,
                )
            except Exception as exc:
                evaluation["approved"] = False
                evaluation["reasons"] = [
                    *evaluation["reasons"],
                    "paper_open_failed",
                ]
                evaluation["execution_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
                self.rejected_count += 1
                continue

            opened.append(
                {
                    "symbol": evaluation["symbol"],
                    "trade_id": opened_result.get("trade_id"),
                    "quantity": evaluation["quantity"],
                    "entry": evaluation["entry"],
                    "stoploss": evaluation["stoploss"],
                    "target2": evaluation["target2"],
                    "score": evaluation["score"],
                    "confidence": evaluation["confidence"],
                    "reward_risk": evaluation["reward_risk"],
                    "trade_mode": str(
                        candidate.get("technical_mode") or "intraday"
                    ).strip().lower(),
                }
            )
            self.opened_count += 1

        result = {
            "status": (
                "executed"
                if opened
                else "no_entries"
            ),
            "run_id": str(run_id),
            "enabled": True,
            "execute_requested": True,
            "candidate_count": len(candidates),
            "evaluation_count": len(evaluations),
            "opened_count": len(opened),
            "opened": opened,
            "evaluations": evaluations,
            "broker_orders_allowed": False,
        }
        self.last_status = result["status"]
        self.last_result = result
        self._notify_result(result)
        return result

    def health(self) -> dict[str, Any]:
        return {
            "status": "ready" if self.enabled else "disabled",
            "enabled": self.enabled,
            "paper_only": True,
            "broker_orders_allowed": False,
            "allowed_signals": list(self.allowed_signals),
            "minimum_score": self.minimum_score,
            "minimum_confidence": self.minimum_confidence,
            "capital": self.capital,
            "risk_per_trade_percent": self.risk_per_trade_percent,
            "max_daily_loss_percent": self.max_daily_loss_percent,
            "max_open_positions": self.max_open_positions,
            "max_capital_per_trade_percent": (
                self.max_capital_per_trade_percent
            ),
            "minimum_rr": self.minimum_rr,
            "max_entries_per_scan": self.max_entries_per_scan,
            "processed_scans": self.processed_scans,
            "execution_attempts": self.execution_attempts,
            "opened_count": self.opened_count,
            "rejected_count": self.rejected_count,
            "last_run_id": self.last_run_id,
            "last_status": self.last_status,
            "last_processed_at": self.last_processed_at,
        }


__all__ = ["PaperAutoEntryService"]
