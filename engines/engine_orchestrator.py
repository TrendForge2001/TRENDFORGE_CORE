"""Canonical TrendForge analysis pipeline."""

from __future__ import annotations

from typing import Any

from engines.base_engine import EngineResult
from engines.canonical_engine_chain import (
    ContractedMarketRegimeEngine,
    ContractedSectorEngine,
    ContractedFundamentalEngine,
    ContractedTechnicalEngine,
    ContractedPriceActionEngine,
    ContractedRiskEngine,
    ContractedSignalEngine,
    ContractedCorporateActionEngine,
    ContractedBigSharkEngine,
    CanonicalTechnicalEngine,
    CanonicalPriceActionEngine,
    CanonicalMarketRegimeEngine,
    CanonicalBigSharkEngine,
    CanonicalSectorEngine,
    CanonicalCorporateActionEngine,
)
from engines.input_contract import EngineInputContract
from engines.trend_alignment import evaluate_trend_alignment


class EngineOrchestrator:
    """Run the canonical engine chain and aggregate its final signal."""

    NAME = "Engine Orchestrator"

    def __init__(self, engines: list[Any] | None = None, input_contract: EngineInputContract | None = None) -> None:
        self.engines = engines or [
            ContractedMarketRegimeEngine(engine=CanonicalMarketRegimeEngine()),
            ContractedSectorEngine(engine=CanonicalSectorEngine()),
            ContractedFundamentalEngine(),
            ContractedCorporateActionEngine(engine=CanonicalCorporateActionEngine()),
            ContractedBigSharkEngine(engine=CanonicalBigSharkEngine()),
            ContractedTechnicalEngine(engine=CanonicalTechnicalEngine()),
            ContractedPriceActionEngine(engine=CanonicalPriceActionEngine()),
            ContractedRiskEngine(),
        ]
        self.signal_engine = ContractedSignalEngine()
        self.input_contract = input_contract or EngineInputContract()

    @staticmethod
    def _engine_name(engine: Any) -> str:
        """Return the stable public name used by orchestration health checks."""
        return str(getattr(engine, "NAME", engine.__class__.__name__))

    def _explain_signal(
        self,
        symbol: str,
        results: dict[str, EngineResult],
    ) -> dict[str, Any]:
        explain = getattr(
            self.signal_engine,
            "explain_from_results",
            None,
        )
        if callable(explain):
            return explain(symbol, results)

        # Preserve compatibility with injected/test signal generators that
        # predate explainability while keeping production scoring canonical.
        from engines.signal_engine import SignalEngine

        return SignalEngine().explain_from_results(symbol, results)

    @staticmethod
    def _clarify_price_action_reasons(result: EngineResult) -> EngineResult:
        """Make price-action horizon explicit without changing raw indicators."""
        if result.engine != "Price Action Engine":
            return result
        replacements = {
            "Confirmed price uptrend": "Short-term price-structure uptrend",
            "Confirmed price downtrend": "Short-term price-structure downtrend",
        }
        result.reasons = [replacements.get(reason, reason) for reason in (result.reasons or [])]
        return result

    def evaluate(self, stock: dict[str, Any]) -> dict[str, Any]:
        report = self.input_contract.validate(stock)
        symbol = str(stock.get("symbol") or stock.get("ticker") or stock.get("tradingsymbol") or "").upper()
        if not report.ready and any(getattr(engine, "mandatory", False) for engine in self.engines):
            alignment = evaluate_trend_alignment({})
            signal = self.signal_engine.generate_from_results(symbol, {})
            signal.signal = "HOLD"
            signal_explainability = self._explain_signal(
                symbol,
                {},
            )
            signal_explainability["orchestrator_overrides"] = [{
                "type": "input_contract_failure",
                "from_signal": "HOLD",
                "to_signal": "HOLD",
                "details": report.as_dict(),
            }]
            signal_explainability["final_signal"] = signal.signal
            signal_explainability["final_score"] = round(
                float(
                    getattr(
                        signal,
                        "overall_score",
                        signal_explainability.get("final_score", 0.0),
                    )
                    or 0.0
                ),
                2,
            )
            signal_explainability["final_confidence"] = round(
                float(
                    getattr(
                        signal,
                        "confidence",
                        signal_explainability.get("confidence", 0.0),
                    )
                    or 0.0
                ),
                2,
            )
            signal_explainability["orchestrator_passed"] = False
            contract_errors = [f"missing:{item}" for item in report.missing]
            contract_errors.extend(f"invalid:{item}" for item in report.invalid)
            signal.warnings = list(signal.warnings or []) + contract_errors
            return {"passed": False, "score": 0.0, "max_score": 0.0, "confidence": 0.0,
                    "signal": signal, "engines": {}, "input_contract": report.as_dict(),
                    "trend_alignment": alignment.as_dict(),
                    "signal_explainability": signal_explainability,
                    "execution_errors": [], "missing_mandatory": [], "failed_mandatory": []}

        results: dict[str, EngineResult] = {}
        execution_errors: list[str] = []
        for engine in self.engines:
            try:
                result = engine.evaluate(stock)
                if not isinstance(result, EngineResult):
                    raise TypeError(f"{engine.NAME} returned {type(result).__name__}; expected EngineResult")
            except Exception as exc:
                execution_errors.append(f"{engine.NAME}: {exc}")
                result = EngineResult(engine=engine.NAME, passed=False, score=0.0,
                                      max_score=100.0, confidence=0.0, grade="ERROR",
                                      warnings=[f"Engine execution failed: {exc}"])
            result = self._clarify_price_action_reasons(result)
            result_key = result.engine
            if result_key in results:
                suffix = 2
                while f"{result.engine}#{suffix}" in results:
                    suffix += 1
                result_key = f"{result.engine}#{suffix}"
            results[result_key] = result

        total_max = sum(max(float(r.max_score or 0), 0.0) for r in results.values())
        total_score = sum(max(min(float(r.score or 0), float(r.max_score or 0)), 0.0) for r in results.values())
        confidence = round((total_score / total_max) * 100, 2) if total_max else 0.0
        mandatory = [e for e in self.engines if getattr(e, "mandatory", False)]
        missing_mandatory = [e.NAME for e in mandatory if e.NAME not in results]
        failed_mandatory = [e.NAME for e in mandatory if e.NAME in results and not results[e.NAME].passed]
        passed = not missing_mandatory and not failed_mandatory and not execution_errors
        alignment = evaluate_trend_alignment(results)

        signal = self.signal_engine.generate_from_results(symbol, results)
        signal_explainability = self._explain_signal(
            symbol,
            results,
        )
        signal_overrides: list[dict[str, Any]] = []
        if not any(
            name in {
                "Market Regime Engine", "Sector Engine", "Fundamental Engine",
                "Corporate Action Engine", "Big Shark Engine", "Technical Engine",
                "Price Action Engine", "Risk Engine",
            }
            for name in results
        ) and total_max:
            previous_signal = signal.signal
            previous_score = float(
                getattr(
                    signal,
                    "overall_score",
                    signal_explainability.get("final_score", 0.0),
                )
                or 0.0
            )
            if confidence >= 95:
                signal.signal = "STRONG BUY"
            elif confidence >= 90:
                signal.signal = "BUY"
            elif confidence >= 85:
                signal.signal = "ACCUMULATE"
            elif confidence >= 75:
                signal.signal = "WATCHLIST"
            elif confidence >= 60:
                signal.signal = "HOLD"
            elif confidence >= 40:
                signal.signal = "REDUCE"
            else:
                signal.signal = "SELL"
            signal.overall_score = round(confidence, 2)
            signal_overrides.append(
                {
                    "type": "noncanonical_fallback_scoring",
                    "from_signal": previous_signal,
                    "to_signal": signal.signal,
                    "score_before": previous_score,
                    "score_after": signal.overall_score,
                }
            )
            signal_explainability["scoring_mode"] = "orchestrator_fallback"
            signal_explainability["fallback_score"] = signal.overall_score
        vetoes = [r.engine for r in results.values() if (r.metrics or {}).get("hard_block") is True]
        if vetoes:
            previous_signal = signal.signal
            if signal.signal in {"STRONG BUY", "BUY", "ACCUMULATE"}:
                signal.signal = "HOLD"
                signal.warnings.append("BUY vetoed by a hard-risk event: " + ", ".join(vetoes))
            signal.warnings.append("Hard-risk veto active: " + ", ".join(vetoes))
            signal_overrides.append({
                "type": "hard_risk_veto",
                "from_signal": previous_signal,
                "to_signal": signal.signal,
                "engines": list(vetoes),
            })
            passed = False
        if missing_mandatory:
            previous_signal = signal.signal
            signal.signal = "HOLD"
            signal.warnings.append("Mandatory engines missing: " + ", ".join(missing_mandatory))
            signal_overrides.append({
                "type": "mandatory_engine_missing",
                "from_signal": previous_signal,
                "to_signal": signal.signal,
                "engines": list(missing_mandatory),
            })
        if failed_mandatory:
            previous_signal = signal.signal
            signal.signal = "HOLD"
            signal.warnings.append("Mandatory engines failed: " + ", ".join(failed_mandatory))
            signal_overrides.append({
                "type": "mandatory_engine_failed",
                "from_signal": previous_signal,
                "to_signal": signal.signal,
                "engines": list(failed_mandatory),
            })
        if execution_errors:
            signal.warnings.extend(execution_errors)
            signal_overrides.append({
                "type": "engine_execution_error",
                "from_signal": signal.signal,
                "to_signal": signal.signal,
                "errors": list(execution_errors),
            })

        signal_explainability["orchestrator_overrides"] = signal_overrides
        signal_explainability["final_signal"] = signal.signal
        signal_explainability["final_score"] = round(
            float(
                getattr(
                    signal,
                    "overall_score",
                    signal_explainability.get("final_score", 0.0),
                )
                or 0.0
            ),
            2,
        )
        signal_explainability["final_confidence"] = round(
            float(
                getattr(
                    signal,
                    "confidence",
                    signal_explainability.get("confidence", confidence),
                )
                or 0.0
            ),
            2,
        )
        signal_explainability["orchestrator_passed"] = passed
        signal_explainability["hard_risk_vetoes"] = list(vetoes)
        signal_explainability["missing_mandatory"] = list(missing_mandatory)
        signal_explainability["failed_mandatory"] = list(failed_mandatory)
        signal_explainability["execution_errors"] = list(execution_errors)

        return {"passed": passed, "score": round(total_score, 2), "max_score": round(total_max, 2),
                "confidence": confidence, "signal": signal,
                "engines": {name: result.as_dict() for name, result in results.items()},
                "input_contract": report.as_dict(), "trend_alignment": alignment.as_dict(),
                "signal_explainability": signal_explainability,
                "execution_errors": execution_errors,
                "missing_mandatory": missing_mandatory, "failed_mandatory": failed_mandatory}

    def health(self) -> dict[str, Any]:
        """Report configuration health without claiming runtime evaluation succeeded."""
        names = [self._engine_name(engine) for engine in self.engines]
        duplicate_names = sorted({name for name in names if names.count(name) > 1})
        invalid_engines = [
            name for name, engine in zip(names, self.engines)
            if not callable(getattr(engine, "evaluate", None))
        ]
        signal_methods = {
            "generate_from_results": callable(getattr(self.signal_engine, "generate_from_results", None)),
            "evaluate": callable(getattr(self.signal_engine, "evaluate", None)),
        }
        invalid_signal_methods = [name for name, available in signal_methods.items() if not available]

        status = "configured"
        if not names or duplicate_names or invalid_engines or invalid_signal_methods:
            status = "degraded"

        result: dict[str, Any] = {
            "status": status,
            "engine_count": len(self.engines),
            "engines": names,
            "signal_engine": getattr(self.signal_engine, "NAME", self.signal_engine.__class__.__name__),
        }
        if duplicate_names:
            result["duplicate_engines"] = duplicate_names
        if invalid_engines:
            result["invalid_engines"] = invalid_engines
        if invalid_signal_methods:
            result["invalid_signal_methods"] = invalid_signal_methods
        result["signal_methods"] = signal_methods
        return result


__all__ = ["EngineOrchestrator"]
