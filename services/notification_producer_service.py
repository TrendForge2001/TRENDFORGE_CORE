"""Best-effort event producers for canonical TrendForge notifications."""
from __future__ import annotations

from datetime import datetime, timezone
import math
import os
from typing import Any


class NotificationProducerService:
    """Translate domain outcomes into canonical notification events.

    Producer failures are intentionally non-fatal. Scanner/trading outcomes
    remain authoritative even when notification persistence or Discord fails.
    """

    def __init__(
        self,
        center: Any,
        *,
        max_scan_picks: int | None = None,
    ) -> None:
        if center is None:
            raise ValueError("notification center is required")
        self.center = center
        self.max_scan_picks = (
            self._env_int(
                "TRENDFORGE_NOTIFICATION_MAX_SCAN_PICKS",
                3,
                minimum=0,
                maximum=20,
            )
            if max_scan_picks is None
            else max(0, min(int(max_scan_picks), 20))
        )
        self.attempted = 0
        self.emitted = 0
        self.failures = 0
        self.last_event_at: str | None = None
        self.last_error: str | None = None
        self.last_result: dict[str, Any] | None = None

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
    def _number(value: Any, default: float = 0.0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return float(default)
        return number if math.isfinite(number) else float(default)

    @staticmethod
    def _signal(candidate: dict[str, Any]) -> str:
        signal = candidate.get("signal")
        if isinstance(signal, dict):
            return str(
                signal.get("signal")
                or signal.get("name")
                or "HOLD"
            ).strip().upper()
        value = getattr(signal, "signal", signal)
        return str(value or "HOLD").strip().upper()

    @classmethod
    def _score_confidence(
        cls,
        candidate: dict[str, Any],
    ) -> tuple[float, float]:
        signal = candidate.get("signal")
        if isinstance(signal, dict):
            signal_score = (
                signal.get("overall_score")
                or signal.get("score")
            )
            signal_confidence = signal.get("confidence")
        else:
            signal_score = getattr(
                signal,
                "overall_score",
                getattr(signal, "score", None),
            )
            signal_confidence = getattr(
                signal,
                "confidence",
                None,
            )

        score = cls._number(
            signal_score
            if signal_score is not None
            else candidate.get(
                "ranking_score",
                candidate.get("score", 0.0),
            )
        )
        confidence = cls._number(
            signal_confidence
            if signal_confidence is not None
            else candidate.get("confidence", 0.0)
        )
        return score, confidence

    def _emit(self, **kwargs: Any) -> dict[str, Any]:
        self.attempted += 1
        try:
            result = self.center.route_event(**kwargs)
            result = (
                dict(result)
                if isinstance(result, dict)
                else {"status": "unknown"}
            )
            self.emitted += 1
            self.last_error = None
            self.last_event_at = datetime.now(
                timezone.utc
            ).isoformat()
            self.last_result = dict(result)
            return result
        except Exception as exc:
            self.failures += 1
            self.last_error = (
                f"{type(exc).__name__}: {exc}"
            )
            self.last_event_at = datetime.now(
                timezone.utc
            ).isoformat()
            self.last_result = {
                "status": "producer_error",
                "error": self.last_error,
            }
            return dict(self.last_result)

    def scan_completed(
        self,
        result: dict[str, Any],
        *,
        run_id: str,
        continuation: bool = False,
    ) -> dict[str, Any]:
        payload = result if isinstance(result, dict) else {}
        outcome = str(
            payload.get("outcome") or "completed"
        ).strip().lower()
        picks_source = (
            payload.get("execution_top_picks")
            if isinstance(
                payload.get("execution_top_picks"),
                list,
            )
            else payload.get("top_picks")
        )
        picks = [
            item
            for item in (picks_source or [])
            if isinstance(item, dict)
        ]
        scale = payload.get("scale_gate")
        scale = scale if isinstance(scale, dict) else {}

        summary_event = self._emit(
            event_type=(
                "scanner_partial"
                if outcome == "partial"
                else "scanner_completed"
            ),
            category="scanner",
            severity=(
                "WARNING"
                if outcome == "partial"
                else "INFO"
            ),
            title=(
                "NIFTY 500 Scan Partial"
                if outcome == "partial"
                else "NIFTY 500 Scan Completed"
            ),
            message=(
                f"Run {run_id}: outcome={outcome}, "
                f"scanned={int(scale.get('requested_symbols') or payload.get('scanned_count') or 0)}, "
                f"execution picks={len(picks)}."
            ),
            source="nifty500_scanner",
            payload={
                "run_id": str(run_id),
                "outcome": outcome,
                "continuation": bool(continuation),
                "execution_pick_count": len(picks),
                "analysis_count": payload.get("analysis_count"),
                "execution_count": payload.get(
                    "execution_count",
                    payload.get("count"),
                ),
                "requested_symbols": scale.get(
                    "requested_symbols"
                ),
                "completed_symbols": scale.get(
                    "completed_symbols"
                ),
                "error_symbols": scale.get("error_symbols"),
                "deferred_symbol_count": scale.get(
                    "deferred_symbol_count"
                ),
            },
            dedupe_key=f"scanner-run:{run_id}:{outcome}",
            deliver=False,
        )

        delivered: list[dict[str, Any]] = []
        if outcome == "completed" and self.max_scan_picks > 0:
            for candidate in picks[: self.max_scan_picks]:
                symbol = str(
                    candidate.get("symbol") or ""
                ).strip().upper()
                if not symbol:
                    continue
                signal = self._signal(candidate)
                score, confidence = self._score_confidence(
                    candidate
                )
                event = self._emit(
                    event_type="scanner_pick",
                    category="scanner",
                    severity=(
                        "SUCCESS"
                        if signal in {"STRONG BUY", "BUY"}
                        else "INFO"
                    ),
                    title=f"{symbol} · {signal}",
                    message=(
                        f"Execution-eligible scanner pick. "
                        f"Score {score:.1f}, confidence {confidence:.1f}."
                    ),
                    symbol=symbol,
                    source="nifty500_scanner",
                    payload={
                        "run_id": str(run_id),
                        "signal": signal,
                        "score": round(score, 2),
                        "confidence": round(
                            confidence,
                            2,
                        ),
                        "continuation": bool(continuation),
                    },
                    dedupe_key=(
                        f"scanner-pick:{run_id}:{symbol}"
                    ),
                    deliver=True,
                )
                delivered.append(event)

        return {
            "status": "processed",
            "summary": summary_event,
            "pick_events": delivered,
            "pick_event_count": len(delivered),
            "max_scan_picks": self.max_scan_picks,
        }

    def scan_failed(
        self,
        *,
        run_id: str,
        failure_stage: str,
        message: str,
        http_status: int | None = None,
    ) -> dict[str, Any]:
        return self._emit(
            event_type="scanner_failed",
            category="system",
            severity="ERROR",
            title="NIFTY 500 Scan Failed",
            message=(
                f"Run {run_id} failed at {failure_stage}: "
                f"{str(message)[:1200]}"
            ),
            source="nifty500_scanner",
            payload={
                "run_id": str(run_id),
                "failure_stage": str(failure_stage),
                "http_status": http_status,
            },
            dedupe_key=(
                f"scanner-failed:{run_id}:"
                f"{failure_stage}"
            ),
            deliver=True,
        )

    def paper_open_blocked(
        self,
        *,
        symbol: str | None,
        reason: str,
    ) -> dict[str, Any]:
        normalized_symbol = str(
            symbol or ""
        ).strip().upper()
        normalized_reason = str(
            reason or "paper_entry_blocked"
        ).strip()
        return self._emit(
            event_type="paper_entry_blocked",
            category="risk",
            severity="WARNING",
            title="Paper Entry Blocked",
            message=(
                (
                    f"{normalized_symbol}: "
                    if normalized_symbol
                    else ""
                )
                + normalized_reason
            ),
            symbol=normalized_symbol or None,
            source="paper_trading",
            payload={
                "reason": normalized_reason,
                "paper_only": True,
            },
            dedupe_key=(
                "paper-entry-blocked:"
                + normalized_reason.lower().replace(" ", "_")
                + (
                    f":{normalized_symbol}"
                    if normalized_symbol
                    else ""
                )
            ),
            deliver=True,
        )

    def paper_opened(
        self,
        *,
        trade_id: Any,
        symbol: str,
        side: str,
        quantity: Any,
        entry_price: Any,
        stoploss: Any = None,
        target: Any = None,
        source: str = "paper_trading",
    ) -> dict[str, Any]:
        normalized_symbol = str(symbol or "").strip().upper()
        return self._emit(
            event_type="paper_position_opened",
            category="paper",
            severity="SUCCESS",
            title=f"Paper Position Opened · {normalized_symbol}",
            message=(
                f"{str(side or 'BUY').upper()} "
                f"{int(quantity or 0)} {normalized_symbol} "
                f"@ ₹{self._number(entry_price):.2f}"
            ),
            symbol=normalized_symbol or None,
            source=source,
            payload={
                "trade_id": trade_id,
                "side": str(side or "BUY").upper(),
                "quantity": int(quantity or 0),
                "entry_price": self._number(entry_price),
                "stoploss": self._number(
                    stoploss,
                    0.0,
                ),
                "target": self._number(target, 0.0),
                "paper_only": True,
            },
            dedupe_key=f"paper-open:{trade_id}",
            deliver=True,
        )

    def paper_closed(
        self,
        closed: dict[str, Any],
        *,
        source: str = "paper_trading",
    ) -> dict[str, Any]:
        row = closed if isinstance(closed, dict) else {}
        symbol = str(
            row.get("symbol") or ""
        ).strip().upper()
        pnl = self._number(row.get("pnl"))
        trade_id = row.get("trade_id")
        reason = str(
            row.get("reason") or "CLOSED"
        ).strip().upper()
        return self._emit(
            event_type="paper_position_closed",
            category="paper",
            severity=(
                "SUCCESS"
                if pnl >= 0
                else "WARNING"
            ),
            title=f"Paper Position Closed · {symbol}",
            message=(
                f"{symbol} exited @ ₹"
                f"{self._number(row.get('exit_price')):.2f}; "
                f"P&L ₹{pnl:.2f}; reason={reason}."
            ),
            symbol=symbol or None,
            source=source,
            payload={
                "trade_id": trade_id,
                "exit_price": self._number(
                    row.get("exit_price")
                ),
                "pnl": pnl,
                "reason": reason,
                "paper_only": True,
            },
            dedupe_key=(
                f"paper-close:{trade_id}"
                if trade_id is not None
                else None
            ),
            deliver=True,
        )

    def kill_switch_changed(
        self,
        *,
        enabled: bool,
    ) -> dict[str, Any]:
        return self._emit(
            event_type=(
                "paper_kill_switch_enabled"
                if enabled
                else "paper_kill_switch_disabled"
            ),
            category="risk",
            severity=(
                "WARNING"
                if enabled
                else "SUCCESS"
            ),
            title=(
                "Runtime Paper Kill Switch Enabled"
                if enabled
                else "Runtime Paper Kill Switch Disabled"
            ),
            message=(
                "Runtime kill switch blocks new paper entries."
                if enabled
                else (
                    "Runtime kill switch is open; environment "
                    "configuration may still block paper entries."
                )
            ),
            source="paper_trading",
            payload={
                "runtime_kill_switch": bool(enabled),
                "paper_only": True,
            },
            dedupe_key=(
                "paper-kill-switch:on"
                if enabled
                else "paper-kill-switch:off"
            ),
            deliver=True,
        )

    def auto_entry_result(
        self,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        payload = result if isinstance(result, dict) else {}
        run_id = str(payload.get("run_id") or "unknown")
        status = str(
            payload.get("status") or "unknown"
        ).strip().lower()
        evaluations = [
            row
            for row in (payload.get("evaluations") or [])
            if isinstance(row, dict)
        ]

        summary = self._emit(
            event_type="paper_auto_entry_evaluated",
            category="paper",
            severity=(
                "SUCCESS"
                if status == "executed"
                else "WARNING"
                if status in {"blocked", "failed_closed"}
                else "INFO"
            ),
            title="Paper Auto-Entry Evaluated",
            message=(
                f"Run {run_id}: status={status}, "
                f"evaluated={len(evaluations)}, "
                f"opened={int(payload.get('opened_count') or 0)}."
            ),
            source="paper_auto_entry",
            payload={
                "run_id": run_id,
                "status": status,
                "candidate_count": payload.get(
                    "candidate_count"
                ),
                "evaluation_count": len(evaluations),
                "opened_count": int(
                    payload.get("opened_count") or 0
                ),
                "reason": payload.get("reason"),
                "paper_only": True,
            },
            dedupe_key=f"paper-auto-entry:{run_id}:{status}",
            deliver=False,
        )

        risk_events: list[dict[str, Any]] = []
        critical_reasons = {
            "maximum_daily_loss_reached": (
                "CRITICAL",
                "Daily Paper Loss Limit Reached",
            ),
            "maximum_open_positions_reached": (
                "WARNING",
                "Maximum Paper Positions Reached",
            ),
        }

        emitted_reason_keys: set[str] = set()
        for evaluation in evaluations:
            reasons = {
                str(reason).strip()
                for reason in (
                    evaluation.get("reasons") or []
                )
                if str(reason).strip()
            }
            for reason, (
                severity,
                title,
            ) in critical_reasons.items():
                if (
                    reason not in reasons
                    or reason in emitted_reason_keys
                ):
                    continue
                emitted_reason_keys.add(reason)
                symbol = str(
                    evaluation.get("symbol") or ""
                ).strip().upper()
                risk_events.append(
                    self._emit(
                        event_type="paper_risk_block",
                        category="risk",
                        severity=severity,
                        title=title,
                        message=(
                            "Auto-entry blocked"
                            + (
                                f" for {symbol}"
                                if symbol
                                else ""
                            )
                            + f": {reason}."
                        ),
                        symbol=symbol or None,
                        source="paper_auto_entry",
                        payload={
                            "run_id": run_id,
                            "reason": reason,
                            "daily_loss": evaluation.get(
                                "daily_loss"
                            ),
                            "daily_loss_limit": evaluation.get(
                                "daily_loss_limit"
                            ),
                            "open_positions": evaluation.get(
                                "open_positions"
                            ),
                            "max_open_positions": evaluation.get(
                                "max_open_positions"
                            ),
                            "paper_only": True,
                        },
                        dedupe_key=f"paper-risk:{reason}",
                        deliver=True,
                    )
                )

        if (
            status == "blocked"
            and payload.get("reason")
            == "paper_trading_not_ready"
        ):
            risk_events.append(
                self._emit(
                    event_type="paper_runtime_block",
                    category="risk",
                    severity="WARNING",
                    title="Paper Auto-Entry Blocked",
                    message=(
                        "Paper auto-entry was requested but the "
                        "paper trading runtime is not ready."
                    ),
                    source="paper_auto_entry",
                    payload={
                        "run_id": run_id,
                        "reason": payload.get("reason"),
                        "paper_only": True,
                    },
                    dedupe_key="paper-runtime:not-ready",
                    deliver=True,
                )
            )

        return {
            "status": "processed",
            "summary": summary,
            "risk_events": risk_events,
            "risk_event_count": len(risk_events),
        }

    def monitor_failed(
        self,
        *,
        error: str,
    ) -> dict[str, Any]:
        return self._emit(
            event_type="paper_monitor_failed",
            category="system",
            severity="ERROR",
            title="Paper Quote Monitor Failed",
            message=str(error)[:1200],
            source="paper_quote_monitor",
            payload={"paper_only": True},
            dedupe_key="paper-monitor:failed",
            deliver=True,
        )

    def startup_event(
        self,
        *,
        event_type: str,
        title: str,
        message: str,
        severity: str = "INFO",
        deliver: bool = False,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._emit(
            event_type=event_type,
            category="system",
            severity=severity,
            title=title,
            message=message,
            source="application_startup",
            payload=payload or {},
            dedupe_key=f"startup:{event_type}",
            deliver=deliver,
        )

    def health(self) -> dict[str, Any]:
        return {
            "status": (
                "degraded"
                if self.last_error
                else "ready"
            ),
            "best_effort": True,
            "primary_operations_fail_closed_on_notification_error": False,
            "max_scan_picks": self.max_scan_picks,
            "attempted": self.attempted,
            "emitted": self.emitted,
            "failures": self.failures,
            "last_event_at": self.last_event_at,
            "last_error": self.last_error,
            "last_result": self.last_result,
        }


__all__ = ["NotificationProducerService"]
