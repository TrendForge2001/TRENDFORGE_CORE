"""End-to-end canonical TrendForge scanner pipeline."""
from __future__ import annotations

from typing import Any
import math
import time

import pandas as pd

from config.signal_weights import SIGNAL_WEIGHTS
from core.data_contract import MarketDataContract
from engines.signal_engine import SignalEngine
from engines.engine_orchestrator import EngineOrchestrator
from engines.input_contract import EngineInputContract
from indicators.indicator_engine import IndicatorEngine


class FullScannerPipeline:
    """Provider -> data contract -> indicators -> enrichment -> engine contract -> engines."""

    def __init__(self, provider: Any, orchestrator: EngineOrchestrator | None = None,
                 indicator_engine: IndicatorEngine | None = None, enricher: Any | None = None) -> None:
        if provider is None:
            raise ValueError("A market-data provider is required")
        self.provider = provider
        self.indicators = indicator_engine or IndicatorEngine()
        # Compatibility fallback for legacy callers; ApplicationFactory supplies the canonical instance.
        self.orchestrator = orchestrator or EngineOrchestrator(*())
        self.enricher = enricher
        self.data_contract = MarketDataContract
        self.engine_input_contract = EngineInputContract()

    def _prepare(self, symbol: str, candles: pd.DataFrame, capital: float = 0.0,
                 fundamentals: dict[str, Any] | None = None) -> dict[str, Any]:
        symbol = str(symbol or "").strip().upper()
        if not symbol:
            raise ValueError("Symbol is required")
        self.data_contract.assert_valid(candles)
        frame = self.indicators.calculate(candles.copy())
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise ValueError(f"Indicator calculation returned no data for {symbol}")
        latest = self.indicators.latest(frame)
        if not isinstance(latest, dict):
            raise ValueError(f"Indicator snapshot unavailable for {symbol}")
        snapshot = {"close": latest.get("close", 0), "atr": latest.get("ATR", 0),
                    "rsi": latest.get("RSI", 0), "adx": latest.get("ADX", 0),
                    "rvol": latest.get("RVOL", 0), "vwap": latest.get("VWAP", 0)}
        stock: dict[str, Any] = {"symbol": symbol, "df": frame, "data": frame,
                                 "candles": frame, "snapshot": snapshot,
                                 "capital": float(capital or 0)}
        if fundamentals:
            stock.update(fundamentals)
        report = self.engine_input_contract.validate(stock)
        if not report.ready:
            raise ValueError(f"Engine input contract failed: {report.as_dict()}")
        stock["engine_input_contract"] = report.as_dict()
        return stock

    def _enrich(self, stock: dict[str, Any]) -> dict[str, Any]:
        if self.enricher is None:
            return stock
        enrichment = self.enricher.enrich(stock)
        if hasattr(self.enricher, "merge"):
            return self.enricher.merge(stock, enrichment)
        if hasattr(enrichment, "data"):
            merged = dict(stock)
            merged.update(enrichment.data)
            merged["enrichment_warnings"] = list(getattr(enrichment, "warnings", ()))
            merged["enrichment_failures"] = list(getattr(enrichment, "failures", ()))
            return merged
        raise TypeError("Enricher must expose merge() or return an EnrichmentResult-like object")

    @staticmethod
    def _signal_name(signal: Any) -> str:
        if isinstance(signal, dict):
            signal = signal.get("signal", signal.get("name", "HOLD"))
        else:
            signal = getattr(signal, "signal", signal or "HOLD")
        return str(signal).upper().strip()

    @classmethod
    def _rejection_reasons(cls, result: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        if not isinstance(result, dict):
            return ["invalid_result"]
        if not result.get("passed", False):
            reasons.append("orchestrator_failed")
        signal = cls._signal_name(result.get("signal"))
        if signal in {"HOLD", "SELL", "REDUCE", "IGNORE", "ERROR"}:
            reasons.append(f"negative_signal:{signal.lower()}")
        if any(isinstance(engine, dict) and engine.get("metrics", {}).get("hard_block") is True
               for engine in result.get("engines", {}).values()):
            reasons.append("hard_risk_block")
        if result.get("failed_mandatory"):
            reasons.append("mandatory_engine_failed")
        if result.get("missing_mandatory"):
            reasons.append("mandatory_engine_missing")
        if result.get("execution_errors"):
            reasons.append("engine_execution_error")
        if result.get("error"):
            reasons.append("pipeline_error")
        return list(dict.fromkeys(reasons))

    @classmethod
    def _is_eligible(cls, result: dict[str, Any]) -> bool:
        return not cls._rejection_reasons(result)

    @staticmethod
    def _safe_number(value: Any) -> float:
        try:
            value = float(value)
            return value if math.isfinite(value) else 0.0
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _signal_score(cls, result: dict[str, Any]) -> float:
        signal = result.get("signal")
        if isinstance(signal, dict):
            return cls._safe_number(signal.get("overall_score"))
        return cls._safe_number(getattr(signal, "overall_score", 0.0))

    @classmethod
    def _rank_key(cls, result: dict[str, Any]) -> tuple[float, float, str]:
        # Rank on the canonical weighted final-signal score rather than the
        # raw sum of engine points. Engine maxima may legitimately differ
        # (for example 47 vs 53 for evidence-backed N/M fundamentals).
        return (
            cls._signal_score(result),
            cls._safe_number(result.get("confidence")),
            str(result.get("symbol", "")),
        )

    @classmethod
    def _fundamental_scoring_summary(
        cls,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        engines = result.get("engines")
        if not isinstance(engines, dict):
            return None
        fundamental = engines.get("Fundamental Engine")
        if not isinstance(fundamental, dict):
            return None

        score = cls._safe_number(fundamental.get("score"))
        max_score = cls._safe_number(fundamental.get("max_score"))
        normalized = round(score / max_score * 100.0, 2) if max_score > 0 else 0.0
        metrics = fundamental.get("metrics")
        metrics = metrics if isinstance(metrics, dict) else {}
        readiness = metrics.get("scoring_readiness")
        readiness = readiness if isinstance(readiness, dict) else {}
        strict = metrics.get("input_contract")
        strict = strict if isinstance(strict, dict) else {}

        available_weight_total = 0.0
        for engine_name, engine_payload in engines.items():
            if not isinstance(engine_payload, dict):
                continue
            alias = SignalEngine.ALIASES.get(engine_name)
            if alias is None:
                continue
            if cls._safe_number(engine_payload.get("max_score")) <= 0:
                continue
            weight = cls._safe_number(SIGNAL_WEIGHTS.get(alias, 0.0))
            if weight > 0:
                available_weight_total += weight

        configured_weight = cls._safe_number(SIGNAL_WEIGHTS.get("fundamental", 0.0))
        effective_weight = (
            configured_weight / available_weight_total
            if configured_weight > 0 and available_weight_total > 0
            else 0.0
        )
        weighted_points = round(normalized * effective_weight, 2)

        return {
            "state": metrics.get("scoring_state"),
            "eligible": readiness.get("eligible"),
            "score": score,
            "max_score": max_score,
            "normalized_score_pct": normalized,
            "confidence": cls._safe_number(fundamental.get("confidence")),
            "grade": fundamental.get("grade"),
            "data_confidence_pct": cls._safe_number(
                metrics.get("data_confidence_pct")
            ),
            "excluded_fields": list(metrics.get("excluded_fields") or []),
            "strict_contract_ready": bool(strict.get("ready", False)),
            "strict_missing": list(strict.get("missing") or []),
            "strict_invalid": list(strict.get("invalid") or []),
            "configured_signal_weight": configured_weight,
            "effective_signal_weight": round(effective_weight, 6),
            "weighted_signal_points_pre_penalty": weighted_points,
            "warnings": list(fundamental.get("warnings") or []),
        }

    @classmethod
    def _decision_explainability(
        cls,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        rejection_reasons = cls._rejection_reasons(result)
        eligible = not rejection_reasons
        signal_name = cls._signal_name(result.get("signal"))
        final_score = cls._signal_score(result)

        signal = result.get("signal")
        if isinstance(signal, dict):
            signal_confidence = cls._safe_number(
                signal.get("confidence")
            )
        else:
            signal_confidence = cls._safe_number(
                getattr(signal, "confidence", 0.0)
            )

        ledger = result.get("signal_explainability")
        ledger = ledger if isinstance(ledger, dict) else {}
        contributions = ledger.get("components")
        contributions = (
            list(contributions)
            if isinstance(contributions, list)
            else []
        )

        reason_messages = {
            "orchestrator_failed":
                "One or more mandatory/runtime orchestration checks failed.",
            "hard_risk_block":
                "A hard-risk block prevents scanner eligibility.",
            "mandatory_engine_failed":
                "A mandatory engine failed its decision gate.",
            "mandatory_engine_missing":
                "A mandatory engine result is unavailable.",
            "engine_execution_error":
                "At least one engine raised an execution error.",
            "pipeline_error":
                "The scanner pipeline could not complete normally.",
        }

        human_reasons: list[str] = []
        for reason in rejection_reasons:
            if reason.startswith("negative_signal:"):
                final_name = reason.split(":", 1)[1].upper()
                human_reasons.append(
                    f"Final signal {final_name} is not eligible for "
                    "actionable scanner ranking."
                )
            else:
                human_reasons.append(
                    reason_messages.get(
                        reason,
                        reason.replace("_", " ").capitalize(),
                    )
                )

        if eligible:
            summary = (
                f"Eligible: final signal {signal_name} with weighted "
                f"score {final_score:.2f}."
            )
        else:
            primary = (
                human_reasons[0]
                if human_reasons
                else "Scanner eligibility requirements were not met."
            )
            summary = (
                f"Rejected: {primary} Final weighted score "
                f"{final_score:.2f}."
            )

        return {
            "status": "ELIGIBLE" if eligible else "REJECTED",
            "eligible": eligible,
            "signal": signal_name,
            "final_score": round(final_score, 2),
            "signal_confidence": round(signal_confidence, 2),
            "orchestrator_passed": bool(result.get("passed", False)),
            "primary_rejection_reason": (
                rejection_reasons[0]
                if rejection_reasons
                else None
            ),
            "rejection_reasons": list(rejection_reasons),
            "reason_messages": human_reasons,
            "summary": summary,
            "contributions": contributions,
            "component_total_pre_adjustment": ledger.get(
                "component_total_pre_adjustment"
            ),
            "available_weight_total": ledger.get(
                "available_weight_total"
            ),
            "weights_renormalized": ledger.get(
                "weights_renormalized"
            ),
            "risk_cap": ledger.get("risk_cap"),
            "trend_penalty": ledger.get("trend_penalty"),
            "trend_alignment": ledger.get("trend_alignment"),
            "orchestrator_overrides": list(
                ledger.get("orchestrator_overrides") or []
            ),
            "score_reconciled": ledger.get("reconciled"),
        }

    def _finalize(self, results: list[dict[str, Any]], top_n: int = 20) -> dict[str, Any]:
        for item in results:
            item["rejection_reasons"] = self._rejection_reasons(item)
            item["rejection_reason"] = item["rejection_reasons"][0] if item["rejection_reasons"] else None
            item["eligible"] = not item["rejection_reasons"]
            item["decision_explainability"] = (
                self._decision_explainability(item)
            )
        eligible = [item for item in results if item["eligible"]]
        rejected = [item for item in results if not item["eligible"]]
        ranked = sorted(eligible, key=self._rank_key, reverse=True)
        limit = max(0, int(top_n))
        return {"results": ranked, "eligible": ranked, "rejected": rejected,
                "top_picks": ranked[:limit], "count": len(ranked),
                "rejected_count": len(rejected), "scanned_count": len(results)}

    def _analyze_from_candles(
        self,
        symbol: str,
        candles: pd.DataFrame,
        *,
        capital: float = 0.0,
        fundamentals: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        stock = self._prepare(
            symbol,
            candles,
            capital=capital,
            fundamentals=fundamentals,
        )
        stock = self._enrich(stock)
        result = self.orchestrator.evaluate(stock)
        if not isinstance(result, dict):
            raise TypeError(
                "EngineOrchestrator must return a dict pipeline result"
            )
        result["symbol"] = str(symbol).strip().upper()
        result["enrichment_warnings"] = stock.get(
            "enrichment_warnings",
            [],
        )
        result["enrichment_failures"] = stock.get(
            "enrichment_failures",
            [],
        )
        result["enrichment_provenance"] = stock.get(
            "enrichment_provenance",
            {},
        )
        result["fundamental_data_quality"] = stock.get(
            "fundamental_data_quality"
        )
        result["fundamental_scoring"] = (
            self._fundamental_scoring_summary(result)
        )
        result["ranking_score"] = self._signal_score(result)
        result["engine_input_contract"] = stock["engine_input_contract"]
        result["rejection_reasons"] = self._rejection_reasons(result)
        result["rejection_reason"] = (
            result["rejection_reasons"][0]
            if result["rejection_reasons"]
            else None
        )
        result["eligible"] = not result["rejection_reasons"]
        result["decision_explainability"] = (
            self._decision_explainability(result)
        )
        return result

    @staticmethod
    def _normalize_symbols(symbols: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_symbol in symbols or []:
            symbol = str(raw_symbol or "").strip().upper()
            if symbol and symbol not in seen:
                normalized.append(symbol)
                seen.add(symbol)
        return normalized

    @staticmethod
    def _error_result(symbol: str, error: Any) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "passed": False,
            "score": 0.0,
            "confidence": 0.0,
            "signal": "ERROR",
            "eligible": False,
            "error": str(error),
        }

    def analyze(
        self,
        symbol: str,
        period: str = "6mo",
        interval: str = "1d",
        capital: float = 0.0,
        fundamentals: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        candles_method = getattr(self.provider, "candles", None)
        if not callable(candles_method):
            raise ValueError(
                "Provider must expose callable "
                "candles(symbol, period, interval)"
            )
        candles = candles_method(
            symbol,
            period=period,
            interval=interval,
        )
        return self._analyze_from_candles(
            symbol,
            candles,
            capital=capital,
            fundamentals=fundamentals,
        )

    def analyze_many(
        self,
        symbols: list[str],
        period: str = "6mo",
        interval: str = "1d",
        capital: float = 0.0,
        top_n: int = 20,
    ) -> dict[str, Any]:
        normalized = self._normalize_symbols(symbols)
        results: list[dict[str, Any]] = []

        batch_method = getattr(
            self.provider,
            "batch_candles_with_errors",
            None,
        )
        if callable(batch_method) and normalized:
            try:
                candles_by_symbol, market_failures = batch_method(
                    normalized,
                    period=period,
                    interval=interval,
                )
            except Exception as exc:
                candles_by_symbol = {}
                market_failures = {
                    symbol: str(exc)
                    for symbol in normalized
                }

            for symbol in normalized:
                if symbol in market_failures:
                    results.append(
                        self._error_result(
                            symbol,
                            market_failures[symbol],
                        )
                    )
                    continue

                candles = candles_by_symbol.get(symbol)
                if candles is None:
                    results.append(
                        self._error_result(
                            symbol,
                            "market_data_missing_from_batch",
                        )
                    )
                    continue

                try:
                    results.append(
                        self._analyze_from_candles(
                            symbol,
                            candles,
                            capital=capital,
                        )
                    )
                except Exception as exc:
                    results.append(
                        self._error_result(symbol, exc)
                    )
        else:
            for symbol in normalized:
                try:
                    results.append(
                        self.analyze(
                            symbol,
                            period=period,
                            interval=interval,
                            capital=capital,
                        )
                    )
                except Exception as exc:
                    results.append(
                        self._error_result(symbol, exc)
                    )

        finalized = self._finalize(results, top_n=top_n)
        finalized["requested_symbols"] = len(symbols or [])
        finalized["unique_symbols"] = len(normalized)
        finalized["duplicate_symbols_removed"] = (
            len(symbols or []) - len(normalized)
        )
        return finalized

    def analyze_many_batched(
        self,
        symbols: list[str],
        *,
        period: str = "6mo",
        interval: str = "1d",
        capital: float = 0.0,
        top_n: int = 20,
        batch_size: int = 25,
    ) -> dict[str, Any]:
        normalized = self._normalize_symbols(symbols)
        size = max(1, min(int(batch_size), 100))
        started = time.perf_counter()

        combined: list[dict[str, Any]] = []
        batch_reports: list[dict[str, Any]] = []

        for batch_number, offset in enumerate(
            range(0, len(normalized), size),
            start=1,
        ):
            batch = normalized[offset: offset + size]
            batch_started = time.perf_counter()
            result = self.analyze_many(
                batch,
                period=period,
                interval=interval,
                capital=capital,
                top_n=len(batch),
            )
            items = list(result.get("results") or [])
            items.extend(list(result.get("rejected") or []))
            combined.extend(items)

            errors = [
                str(item.get("symbol"))
                for item in items
                if item.get("error")
            ]
            batch_reports.append(
                {
                    "batch": batch_number,
                    "requested": len(batch),
                    "accounted": len(items),
                    "errors": len(errors),
                    "error_symbols": errors,
                    "duration_sec": round(
                        time.perf_counter() - batch_started,
                        3,
                    ),
                }
            )

        by_symbol = {
            str(item.get("symbol") or "").strip().upper(): item
            for item in combined
            if str(item.get("symbol") or "").strip()
        }
        missing = [
            symbol
            for symbol in normalized
            if symbol not in by_symbol
        ]
        for symbol in missing:
            item = self._error_result(
                symbol,
                "scanner_batch_missing_result",
            )
            combined.append(item)
            by_symbol[symbol] = item

        finalized = self._finalize(
            [by_symbol[symbol] for symbol in normalized],
            top_n=top_n,
        )
        error_symbols = [
            symbol
            for symbol in normalized
            if by_symbol[symbol].get("error")
        ]
        completed_symbols = [
            symbol
            for symbol in normalized
            if not by_symbol[symbol].get("error")
        ]
        error_details = {
            symbol: str(by_symbol[symbol].get("error"))
            for symbol in error_symbols
        }
        enrichment_failure_symbols = [
            symbol
            for symbol in normalized
            if by_symbol[symbol].get("enrichment_failures")
        ]
        execution_error_symbols = [
            symbol
            for symbol in normalized
            if by_symbol[symbol].get("execution_errors")
        ]
        duration = round(time.perf_counter() - started, 3)

        finalized["scale_gate"] = {
            "requested_symbols": len(symbols or []),
            "unique_symbols": len(normalized),
            "accounted_symbols": len(by_symbol),
            "completed_symbols": len(completed_symbols),
            "error_symbols": len(error_symbols),
            "missing_symbols": len(missing),
            "completion_pct": round(
                (
                    len(by_symbol) / len(normalized) * 100.0
                    if normalized
                    else 100.0
                ),
                2,
            ),
            "batch_size": size,
            "batch_count": len(batch_reports),
            "duration_sec": duration,
            "errors": error_symbols,
            "error_details": error_details,
            "enrichment_failure_symbols": enrichment_failure_symbols,
            "enrichment_failures": len(enrichment_failure_symbols),
            "execution_error_symbols": execution_error_symbols,
            "execution_errors": len(execution_error_symbols),
            "missing": missing,
            "batches": batch_reports,
        }
        return finalized


__all__ = ["FullScannerPipeline"]
