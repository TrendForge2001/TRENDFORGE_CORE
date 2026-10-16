"""End-to-end canonical TrendForge scanner pipeline."""
from __future__ import annotations

from typing import Any
import math
import time

import pandas as pd

from providers.market_data_provider import ProviderAuthenticationError

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
    def _execution_rejection_reasons(
        cls,
        result: dict[str, Any],
    ) -> list[str]:
        """Strict action gate used by R67.2/R67.3 execution paths."""
        reasons: list[str] = []
        if not isinstance(result, dict):
            return ["invalid_result"]
        if not result.get("passed", False):
            reasons.append("orchestrator_failed")
        signal = cls._signal_name(result.get("signal"))
        if signal in {"HOLD", "SELL", "REDUCE", "IGNORE", "ERROR"}:
            reasons.append(f"negative_signal:{signal.lower()}")
        if any(
            isinstance(engine, dict)
            and engine.get("metrics", {}).get("hard_block") is True
            for engine in result.get("engines", {}).values()
        ):
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
    def _analysis_rejection_reasons(
        cls,
        result: dict[str, Any],
    ) -> list[str]:
        """Reject only results that cannot be trusted for analysis/ranking.

        Market-regime vetoes, weak/negative signals, failed decision thresholds,
        and incomplete fundamental scoring may block execution without erasing
        an otherwise successfully computed relative-strength ranking.
        """
        if not isinstance(result, dict):
            return ["invalid_result"]

        reasons: list[str] = []
        if result.get("error"):
            reasons.append("pipeline_error")
        if result.get("execution_errors"):
            reasons.append("engine_execution_error")
        if result.get("missing_mandatory"):
            reasons.append("mandatory_engine_missing")
        if cls._signal_name(result.get("signal")) == "ERROR":
            reasons.append("analysis_signal_error")
        return list(dict.fromkeys(reasons))

    @classmethod
    def _rejection_reasons(cls, result: dict[str, Any]) -> list[str]:
        """Backward-compatible alias for the strict execution gate."""
        return cls._execution_rejection_reasons(result)

    @classmethod
    def _is_eligible(cls, result: dict[str, Any]) -> bool:
        """Backward-compatible execution eligibility."""
        return not cls._execution_rejection_reasons(result)

    @classmethod
    def _is_analysis_eligible(cls, result: dict[str, Any]) -> bool:
        return not cls._analysis_rejection_reasons(result)

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
        analysis_rejection_reasons = cls._analysis_rejection_reasons(result)
        execution_rejection_reasons = cls._execution_rejection_reasons(result)
        analysis_eligible = not analysis_rejection_reasons
        execution_eligible = not execution_rejection_reasons
        signal_name = cls._signal_name(result.get("signal"))
        final_score = cls._signal_score(result)

        signal = result.get("signal")
        if isinstance(signal, dict):
            signal_confidence = cls._safe_number(signal.get("confidence"))
        else:
            signal_confidence = cls._safe_number(
                getattr(signal, "confidence", 0.0)
            )

        ledger = result.get("signal_explainability")
        ledger = ledger if isinstance(ledger, dict) else {}
        contributions = ledger.get("components")
        contributions = list(contributions) if isinstance(contributions, list) else []

        reason_messages = {
            "orchestrator_failed":
                "One or more mandatory decision gates failed.",
            "hard_risk_block":
                "A hard-risk block prevents execution.",
            "mandatory_engine_failed":
                "A mandatory engine failed its execution decision gate.",
            "mandatory_engine_missing":
                "A mandatory engine result is unavailable.",
            "engine_execution_error":
                "At least one engine raised an execution error.",
            "pipeline_error":
                "The scanner pipeline could not complete normally.",
            "analysis_signal_error":
                "The final signal could not be computed reliably.",
        }

        human_reasons: list[str] = []
        for reason in execution_rejection_reasons:
            if reason.startswith("negative_signal:"):
                final_name = reason.split(":", 1)[1].upper()
                human_reasons.append(
                    f"Final signal {final_name} is not execution eligible."
                )
            else:
                human_reasons.append(
                    reason_messages.get(
                        reason,
                        reason.replace("_", " ").capitalize(),
                    )
                )

        if execution_eligible:
            summary = (
                f"Execution eligible: final signal {signal_name} with weighted "
                f"score {final_score:.2f}."
            )
        elif analysis_eligible:
            primary = (
                human_reasons[0]
                if human_reasons
                else "Execution requirements were not met."
            )
            summary = (
                f"Analysis only: ranked for monitoring, but execution is "
                f"blocked. {primary} Final weighted score {final_score:.2f}."
            )
        else:
            primary = (
                reason_messages.get(
                    analysis_rejection_reasons[0],
                    analysis_rejection_reasons[0].replace("_", " ").capitalize(),
                )
                if analysis_rejection_reasons
                else "Analysis requirements were not met."
            )
            summary = (
                f"Rejected from analysis: {primary} Final weighted score "
                f"{final_score:.2f}."
            )

        return {
            # Legacy fields continue to describe strict execution eligibility.
            "status": "ELIGIBLE" if execution_eligible else "REJECTED",
            "eligible": execution_eligible,
            "primary_rejection_reason": (
                execution_rejection_reasons[0]
                if execution_rejection_reasons
                else None
            ),
            "rejection_reasons": list(execution_rejection_reasons),
            "reason_messages": human_reasons,
            # R67.3 exposes both gates explicitly.
            "analysis_status": "RANKED" if analysis_eligible else "REJECTED",
            "analysis_eligible": analysis_eligible,
            "analysis_rejection_reasons": list(analysis_rejection_reasons),
            "execution_status": (
                "ELIGIBLE" if execution_eligible else "BLOCKED"
            ),
            "execution_eligible": execution_eligible,
            "execution_rejection_reasons": list(execution_rejection_reasons),
            "signal": signal_name,
            "final_score": round(final_score, 2),
            "signal_confidence": round(signal_confidence, 2),
            "orchestrator_passed": bool(result.get("passed", False)),
            "summary": summary,
            "contributions": contributions,
            "component_total_pre_adjustment": ledger.get(
                "component_total_pre_adjustment"
            ),
            "available_weight_total": ledger.get("available_weight_total"),
            "weights_renormalized": ledger.get("weights_renormalized"),
            "risk_cap": ledger.get("risk_cap"),
            "trend_penalty": ledger.get("trend_penalty"),
            "trend_alignment": ledger.get("trend_alignment"),
            "orchestrator_overrides": list(
                ledger.get("orchestrator_overrides") or []
            ),
            "score_reconciled": ledger.get("reconciled"),
        }

    def _finalize(
        self,
        results: list[dict[str, Any]],
        top_n: int = 20,
    ) -> dict[str, Any]:
        for item in results:
            analysis_reasons = self._analysis_rejection_reasons(item)
            execution_reasons = self._execution_rejection_reasons(item)

            item["analysis_rejection_reasons"] = analysis_reasons
            item["analysis_rejection_reason"] = (
                analysis_reasons[0] if analysis_reasons else None
            )
            item["analysis_eligible"] = not analysis_reasons

            item["execution_rejection_reasons"] = execution_reasons
            item["execution_rejection_reason"] = (
                execution_reasons[0] if execution_reasons else None
            )
            item["execution_eligible"] = not execution_reasons

            # Backward compatibility: eligible/rejection_* remain the strict
            # execution gate used by R67.2 auto-entry and existing consumers.
            item["rejection_reasons"] = list(execution_reasons)
            item["rejection_reason"] = item["execution_rejection_reason"]
            item["eligible"] = item["execution_eligible"]
            item["decision_explainability"] = (
                self._decision_explainability(item)
            )

        analysis_ranked = sorted(
            [item for item in results if item["analysis_eligible"]],
            key=self._rank_key,
            reverse=True,
        )
        analysis_rejected = [
            item for item in results if not item["analysis_eligible"]
        ]

        execution_ranked = sorted(
            [item for item in results if item["execution_eligible"]],
            key=self._rank_key,
            reverse=True,
        )
        execution_rejected = [
            item for item in results if not item["execution_eligible"]
        ]

        limit = max(0, int(top_n))
        return {
            # Legacy execution-gated response contract.
            "results": execution_ranked,
            "eligible": execution_ranked,
            "rejected": execution_rejected,
            "top_picks": execution_ranked[:limit],
            "count": len(execution_ranked),
            "rejected_count": len(execution_rejected),
            # R67.3 correction-aware analysis/ranking contract.
            "analysis_ranked": analysis_ranked,
            "analysis_top_picks": analysis_ranked[:limit],
            "analysis_eligible": analysis_ranked,
            "analysis_rejected": analysis_rejected,
            "analysis_count": len(analysis_ranked),
            "analysis_rejected_count": len(analysis_rejected),
            "execution_eligible": execution_ranked,
            "execution_top_picks": execution_ranked[:limit],
            "execution_rejected": execution_rejected,
            "execution_count": len(execution_ranked),
            "execution_rejected_count": len(execution_rejected),
            "eligibility_semantics_version": "R67.3",
            "scanned_count": len(results),
        }

    def _evaluate_enriched_stock(
        self,
        stock: dict[str, Any],
    ) -> dict[str, Any]:
        result = self.orchestrator.evaluate(stock)
        if not isinstance(result, dict):
            raise TypeError(
                "EngineOrchestrator must return a dict pipeline result"
            )

        symbol = str(stock.get("symbol") or "").strip().upper()
        result["symbol"] = symbol
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
        analysis_reasons = self._analysis_rejection_reasons(result)
        execution_reasons = self._execution_rejection_reasons(result)
        result["analysis_rejection_reasons"] = analysis_reasons
        result["analysis_rejection_reason"] = (
            analysis_reasons[0] if analysis_reasons else None
        )
        result["analysis_eligible"] = not analysis_reasons
        result["execution_rejection_reasons"] = execution_reasons
        result["execution_rejection_reason"] = (
            execution_reasons[0] if execution_reasons else None
        )
        result["execution_eligible"] = not execution_reasons
        result["rejection_reasons"] = list(execution_reasons)
        result["rejection_reason"] = result["execution_rejection_reason"]
        result["eligible"] = result["execution_eligible"]
        result["decision_explainability"] = (
            self._decision_explainability(result)
        )
        return result

    def _merge_enrichment_result(
        self,
        stock: dict[str, Any],
        enrichment: Any,
    ) -> dict[str, Any]:
        if self.enricher is None:
            return stock

        merge = getattr(self.enricher, "merge", None)
        if callable(merge):
            return merge(stock, enrichment)

        if hasattr(enrichment, "data"):
            merged = dict(stock)
            merged.update(enrichment.data)
            merged["enrichment_warnings"] = list(
                getattr(enrichment, "warnings", ())
            )
            merged["enrichment_failures"] = list(
                getattr(enrichment, "failures", ())
            )
            return merged

        raise TypeError(
            "Enricher must expose merge() or return an "
            "EnrichmentResult-like object"
        )

    def _evaluate_prepared_many(
        self,
        prepared: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        if not prepared:
            return {}

        if self.enricher is None:
            output: dict[str, dict[str, Any]] = {}
            for symbol, stock in prepared.items():
                try:
                    output[symbol] = self._evaluate_enriched_stock(stock)
                except Exception as exc:
                    output[symbol] = self._error_result(symbol, exc)
            return output

        enrich_many = getattr(self.enricher, "enrich_many", None)
        if not callable(enrich_many):
            output = {}
            for symbol, stock in prepared.items():
                try:
                    enriched = self._enrich(stock)
                    output[symbol] = self._evaluate_enriched_stock(
                        enriched
                    )
                except Exception as exc:
                    output[symbol] = self._error_result(symbol, exc)
            return output

        try:
            enrichments = enrich_many(prepared)
        except Exception as exc:
            return {
                symbol: self._error_result(
                    symbol,
                    f"batch_enrichment_failed:{exc}",
                )
                for symbol in prepared
            }

        output = {}
        for symbol, stock in prepared.items():
            enrichment = (
                enrichments.get(symbol)
                if isinstance(enrichments, dict)
                else None
            )
            if enrichment is None:
                output[symbol] = self._error_result(
                    symbol,
                    "batch_enrichment_missing_result",
                )
                continue

            try:
                enriched = self._merge_enrichment_result(
                    stock,
                    enrichment,
                )
                output[symbol] = self._evaluate_enriched_stock(
                    enriched
                )
            except Exception as exc:
                output[symbol] = self._error_result(symbol, exc)

        return output

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
        return self._evaluate_enriched_stock(stock)

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
            "analysis_eligible": False,
            "execution_eligible": False,
            "eligible": False,
            "analysis_rejection_reasons": ["pipeline_error"],
            "execution_rejection_reasons": [
                "orchestrator_failed",
                "negative_signal:error",
                "pipeline_error",
            ],
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
        by_symbol: dict[str, dict[str, Any]] = {}
        prepared: dict[str, dict[str, Any]] = {}

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
            except ProviderAuthenticationError:
                raise
            except Exception as exc:
                candles_by_symbol = {}
                market_failures = {
                    symbol: str(exc)
                    for symbol in normalized
                }

            for symbol in normalized:
                if symbol in market_failures:
                    by_symbol[symbol] = self._error_result(
                        symbol,
                        market_failures[symbol],
                    )
                    continue

                candles = candles_by_symbol.get(symbol)
                if candles is None:
                    by_symbol[symbol] = self._error_result(
                        symbol,
                        "market_data_missing_from_batch",
                    )
                    continue

                try:
                    prepared[symbol] = self._prepare(
                        symbol,
                        candles,
                        capital=capital,
                    )
                except Exception as exc:
                    by_symbol[symbol] = self._error_result(
                        symbol,
                        exc,
                    )
        else:
            candles_method = getattr(self.provider, "candles", None)
            if not callable(candles_method):
                for symbol in normalized:
                    by_symbol[symbol] = self._error_result(
                        symbol,
                        "Provider must expose callable "
                        "candles(symbol, period, interval)",
                    )
            else:
                for symbol in normalized:
                    try:
                        candles = candles_method(
                            symbol,
                            period=period,
                            interval=interval,
                        )
                        prepared[symbol] = self._prepare(
                            symbol,
                            candles,
                            capital=capital,
                        )
                    except Exception as exc:
                        by_symbol[symbol] = self._error_result(
                            symbol,
                            exc,
                        )

        by_symbol.update(
            self._evaluate_prepared_many(prepared)
        )

        ordered = [
            by_symbol.get(
                symbol,
                self._error_result(
                    symbol,
                    "scanner_batch_missing_result",
                ),
            )
            for symbol in normalized
        ]

        finalized = self._finalize(ordered, top_n=top_n)
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
        batch_pause_seconds: float = 1.0,
        scan_time_budget_seconds: float | None = 450.0,
        batch_time_budget_seconds: float | None = 60.0,
    ) -> dict[str, Any]:
        """Analyze a universe in bounded batches.

        Time budgets are enforced at safe batch boundaries. An in-flight batch
        is never force-cancelled; if a budget is crossed while it is running,
        the current batch is retained and remaining symbols are returned as
        deferred time-budget results.
        """
        normalized = self._normalize_symbols(symbols)
        size = max(1, min(int(batch_size), 100))
        pause = max(0.0, min(float(batch_pause_seconds), 10.0))
        scan_budget = (
            None
            if scan_time_budget_seconds is None
            else max(0.001, float(scan_time_budget_seconds))
        )
        batch_budget = (
            None
            if batch_time_budget_seconds is None
            else max(0.001, float(batch_time_budget_seconds))
        )
        started = time.perf_counter()

        combined: list[dict[str, Any]] = []
        batch_reports: list[dict[str, Any]] = []
        next_offset = 0
        stop_reason: str | None = None
        stop_batch: int | None = None

        for batch_number, offset in enumerate(
            range(0, len(normalized), size),
            start=1,
        ):
            elapsed_before_batch = time.perf_counter() - started
            if (
                scan_budget is not None
                and elapsed_before_batch >= scan_budget
            ):
                stop_reason = "scan_time_budget_exhausted_before_batch"
                stop_batch = batch_number
                next_offset = offset
                break

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
            next_offset = offset + len(batch)

            errors = [
                str(item.get("symbol"))
                for item in items
                if item.get("error")
            ]
            batch_duration = time.perf_counter() - batch_started
            batch_budget_exceeded = (
                batch_budget is not None
                and batch_duration >= batch_budget
            )
            batch_budget_headroom = (
                None
                if batch_budget is None
                else round(batch_budget - batch_duration, 3)
            )
            batch_budget_utilization_pct = (
                None
                if batch_budget is None
                else round(
                    batch_duration / batch_budget * 100.0,
                    2,
                )
            )
            batch_reports.append(
                {
                    "batch": batch_number,
                    "requested": len(batch),
                    "accounted": len(items),
                    "errors": len(errors),
                    "error_symbols": errors,
                    "duration_sec": round(batch_duration, 3),
                    "time_budget_seconds": batch_budget,
                    "time_budget_exceeded": batch_budget_exceeded,
                    "sla_met": not batch_budget_exceeded,
                    "budget_headroom_sec": batch_budget_headroom,
                    "budget_utilization_pct": (
                        batch_budget_utilization_pct
                    ),
                }
            )

            total_elapsed = time.perf_counter() - started
            if batch_budget_exceeded and next_offset < len(normalized):
                stop_reason = "batch_time_budget_exceeded"
                stop_batch = batch_number
                break

            if (
                scan_budget is not None
                and total_elapsed >= scan_budget
                and next_offset < len(normalized)
            ):
                stop_reason = "scan_time_budget_exhausted_after_batch"
                stop_batch = batch_number
                break

            if pause > 0 and next_offset < len(normalized):
                if scan_budget is not None:
                    remaining = scan_budget - (
                        time.perf_counter() - started
                    )
                    if remaining <= pause:
                        stop_reason = (
                            "scan_time_budget_exhausted_before_pause"
                        )
                        stop_batch = batch_number
                        break
                time.sleep(pause)

        deferred_symbols = normalized[next_offset:]
        if deferred_symbols:
            reason = stop_reason or "scan_time_budget_exhausted"
            for symbol in deferred_symbols:
                combined.append(
                    self._error_result(
                        symbol,
                        f"time_budget_deferred:{reason}",
                    )
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
        enrichment_failure_details = {
            symbol: list(
                by_symbol[symbol].get("enrichment_failures") or []
            )
            for symbol in enrichment_failure_symbols
        }
        enrichment_failure_fields: dict[str, int] = {}
        enrichment_failure_events = 0
        for failures in enrichment_failure_details.values():
            for failure in failures:
                enrichment_failure_events += 1
                field = str(failure).split(":", 1)[0] or "unknown"
                enrichment_failure_fields[field] = (
                    enrichment_failure_fields.get(field, 0) + 1
                )
        execution_error_symbols = [
            symbol
            for symbol in normalized
            if by_symbol[symbol].get("execution_errors")
        ]
        duration = round(time.perf_counter() - started, 3)
        processed_symbols = len(normalized) - len(deferred_symbols)
        time_budget_exhausted = bool(deferred_symbols)
        total_symbols = len(normalized)

        def pct(count: int) -> float:
            return round(
                (
                    count / total_symbols * 100.0
                    if total_symbols
                    else 100.0
                ),
                2,
            )

        accounted_pct = pct(len(by_symbol))
        processed_pct = pct(processed_symbols)
        successful_pct = pct(len(completed_symbols))
        error_pct = pct(len(error_symbols))
        deferred_pct = pct(len(deferred_symbols))
        missing_pct = pct(len(missing))

        batch_durations = [
            float(report.get("duration_sec") or 0.0)
            for report in batch_reports
        ]
        max_batch_duration = (
            max(batch_durations)
            if batch_durations
            else 0.0
        )
        avg_batch_duration = (
            sum(batch_durations) / len(batch_durations)
            if batch_durations
            else 0.0
        )
        batch_budget_breach_count = sum(
            1
            for report in batch_reports
            if bool(report.get("time_budget_exceeded"))
        )
        scan_budget_headroom = (
            None
            if scan_budget is None
            else round(scan_budget - duration, 3)
        )
        scan_budget_utilization_pct = (
            None
            if scan_budget is None
            else round(duration / scan_budget * 100.0, 2)
        )
        peak_batch_budget_utilization_pct = (
            None
            if batch_budget is None
            else round(
                max_batch_duration / batch_budget * 100.0,
                2,
            )
        )
        scan_sla_met = (
            True
            if scan_budget is None
            else duration <= scan_budget
        )
        batch_sla_met = batch_budget_breach_count == 0
        sla_met = bool(
            scan_sla_met
            and batch_sla_met
            and not time_budget_exhausted
        )
        sla_status = (
            "met"
            if sla_met
            else "breached"
            if time_budget_exhausted or not scan_sla_met or not batch_sla_met
            else "unknown"
        )

        finalized["outcome"] = (
            "partial"
            if time_budget_exhausted
            else "completed"
        )
        finalized["scale_gate"] = {
            "requested_symbols": len(symbols or []),
            "unique_symbols": total_symbols,
            "accounted_symbols": len(by_symbol),
            "completed_symbols": len(completed_symbols),
            "error_symbols": len(error_symbols),
            "missing_symbols": len(missing),
            "progress_semantics_version": "R66.7",
            "accounted_pct": accounted_pct,
            "processed_pct": processed_pct,
            "successful_pct": successful_pct,
            "error_pct": error_pct,
            "deferred_pct": deferred_pct,
            "missing_pct": missing_pct,
            "completion_pct": accounted_pct,
            "completion_pct_semantics": (
                "legacy_alias_of_accounted_pct"
            ),
            "processed_symbols": processed_symbols,
            "deferred_symbols": list(deferred_symbols),
            "deferred_symbol_count": len(deferred_symbols),
            "graceful_degradation": time_budget_exhausted,
            "time_budget_exhausted": time_budget_exhausted,
            "time_budget_stop_reason": stop_reason,
            "time_budget_stop_batch": stop_batch,
            "scan_time_budget_seconds": scan_budget,
            "batch_time_budget_seconds": batch_budget,
            "budget_remaining_sec": (
                None
                if scan_budget is None
                else round(max(0.0, scan_budget - duration), 3)
            ),
            "scan_budget_headroom_sec": scan_budget_headroom,
            "scan_budget_utilization_pct": scan_budget_utilization_pct,
            "scan_sla_met": scan_sla_met,
            "batch_sla_met": batch_sla_met,
            "sla_met": sla_met,
            "sla_status": sla_status,
            "max_batch_duration_sec": round(max_batch_duration, 3),
            "avg_batch_duration_sec": round(avg_batch_duration, 3),
            "batch_budget_breach_count": batch_budget_breach_count,
            "peak_batch_budget_utilization_pct": (
                peak_batch_budget_utilization_pct
            ),
            "batch_size": size,
            "batch_pause_seconds": pause,
            "batch_count": len(batch_reports),
            "duration_sec": duration,
            "errors": error_symbols,
            "error_details": error_details,
            "enrichment_failure_symbols": enrichment_failure_symbols,
            "enrichment_failures": len(enrichment_failure_symbols),
            "enrichment_failure_events": enrichment_failure_events,
            "enrichment_failure_fields": enrichment_failure_fields,
            "enrichment_failure_details": enrichment_failure_details,
            "execution_error_symbols": execution_error_symbols,
            "execution_errors": len(execution_error_symbols),
            "missing": missing,
            "batches": batch_reports,
        }
        return finalized


__all__ = ["FullScannerPipeline"]
