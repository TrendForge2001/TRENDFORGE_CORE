"""End-to-end canonical TrendForge scanner pipeline."""
from __future__ import annotations

from typing import Any
import math

import pandas as pd

from core.data_contract import MarketDataContract
from engines.engine_orchestrator import EngineOrchestrator
from engines.engine_orchestrator import EngineOrchestrator as _CanonicalOrchestrator
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
        self.orchestrator = orchestrator or _CanonicalOrchestrator()
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
        if signal in {"SELL", "REDUCE", "IGNORE", "ERROR", "HOLD"}:
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
    def _rank_key(result: dict[str, Any]) -> tuple[float, float, str]:
        def safe(value: Any) -> float:
            try:
                value = float(value)
                return value if math.isfinite(value) else 0.0
            except (TypeError, ValueError):
                return 0.0
        return safe(result.get("score")), safe(result.get("confidence")), str(result.get("symbol", ""))

    def _finalize(self, results: list[dict[str, Any]], top_n: int = 20) -> dict[str, Any]:
        for item in results:
            item["rejection_reasons"] = self._rejection_reasons(item)
            item["rejection_reason"] = item["rejection_reasons"][0] if item["rejection_reasons"] else None
            item["eligible"] = not item["rejection_reasons"]
        eligible = [item for item in results if item["eligible"]]
        rejected = [item for item in results if not item["eligible"]]
        ranked = sorted(eligible, key=self._rank_key, reverse=True)
        limit = max(0, int(top_n))
        return {"results": ranked, "eligible": ranked, "rejected": rejected,
                "top_picks": ranked[:limit], "count": len(ranked),
                "rejected_count": len(rejected), "scanned_count": len(results)}

    def analyze(self, symbol: str, period: str = "6mo", interval: str = "1d",
                capital: float = 0.0, fundamentals: dict[str, Any] | None = None) -> dict[str, Any]:
        candles_method = getattr(self.provider, "candles", None)
        if not callable(candles_method):
            raise ValueError("Provider must expose callable candles(symbol, period, interval)")
        candles = candles_method(symbol, period=period, interval=interval)
        stock = self._prepare(symbol, candles, capital=capital, fundamentals=fundamentals)
        stock = self._enrich(stock)
        result = self.orchestrator.evaluate(stock)
        if not isinstance(result, dict):
            raise TypeError("EngineOrchestrator must return a dict pipeline result")
        result["symbol"] = str(symbol).strip().upper()
        result["enrichment_warnings"] = stock.get("enrichment_warnings", [])
        result["enrichment_failures"] = stock.get("enrichment_failures", [])
        result["engine_input_contract"] = stock["engine_input_contract"]
        result["rejection_reasons"] = self._rejection_reasons(result)
        result["rejection_reason"] = result["rejection_reasons"][0] if result["rejection_reasons"] else None
        result["eligible"] = not result["rejection_reasons"]
        return result

    def analyze_many(self, symbols: list[str], period: str = "6mo", interval: str = "1d",
                     capital: float = 0.0, top_n: int = 20) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw_symbol in symbols:
            symbol = str(raw_symbol or "").strip().upper()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            try:
                results.append(self.analyze(symbol, period=period, interval=interval, capital=capital))
            except Exception as exc:
                results.append({"symbol": symbol, "passed": False, "score": 0.0,
                                "confidence": 0.0, "signal": "ERROR", "eligible": False,
                                "error": str(exc)})
        return self._finalize(results, top_n=top_n)


__all__ = ["FullScannerPipeline"]
