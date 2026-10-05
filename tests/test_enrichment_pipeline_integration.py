from __future__ import annotations

import pandas as pd

from reconstruction.enrichment import StockEnricher
from scanner.full_pipeline import FullScannerPipeline


class FakeMarketData:
    def candles(self, symbol, period="6mo", interval="1d"):
        n = 40
        return pd.DataFrame({
            "open": [100.0] * n,
            "high": [102.0] * n,
            "low": [98.0] * n,
            "close": [101.0] * n,
            "volume": [1000.0] * n,
        })


class FakeIndicatorEngine:
    def calculate(self, frame):
        result = frame.copy()
        for column in ("EMA_9", "EMA_20", "EMA_50", "EMA_100", "EMA_200", "RSI", "MACD", "MACD_SIGNAL", "MACD_HIST", "ADX", "+DI", "-DI", "RVOL", "VWAP", "CMF", "MFI", "ATR", "ATR_PERCENT", "BB_WIDTH", "SUPPORT", "RESISTANCE", "BREAKOUT", "BREAKDOWN", "UPTREND", "DOWNTREND"):
            result[column] = 1.0
        return result

    def latest(self, frame):
        return frame.iloc[-1].to_dict()


class FakeOrchestrator:
    def evaluate(self, stock):
        assert stock["fundamentals"]["pe"] == 18
        assert stock["sector"]["name"] == "BANKING"
        assert stock["big_shark"]["score"] == 80
        assert stock["corporate_actions"][0]["type"] == "buyback"
        return {"passed": True, "score": 80, "confidence": 80, "signal": "BUY", "engines": {}}


class Provider:
    def __call__(self, symbol, payload):
        return {"symbol": symbol}


def test_enrichment_is_resolved_before_orchestrator():
    enricher = StockEnricher(providers={
        "fundamentals": lambda symbol, payload: {"pe": 18},
        "sector": lambda symbol, payload: {"name": "BANKING"},
        "big_shark": lambda symbol, payload: {"score": 80},
        "corporate_actions": lambda symbol, payload: [{"type": "buyback"}],
    })
    pipeline = FullScannerPipeline(
        provider=FakeMarketData(),
        indicator_engine=FakeIndicatorEngine(),
        orchestrator=FakeOrchestrator(),
        enricher=enricher,
    )

    result = pipeline.analyze("abc")

    assert result["symbol"] == "ABC"
    assert result["signal"] == "BUY"
    assert result["enrichment_failures"] == []


def test_existing_payload_data_is_not_refetched():
    calls = []

    def provider(symbol, payload):
        calls.append(symbol)
        return {"unexpected": True}

    enricher = StockEnricher(providers={"fundamentals": provider})
    result = enricher.enrich({"symbol": "ABC", "df": None, "fundamentals": {"pe": 15}})

    assert result.data["fundamentals"] == {"pe": 15}
    assert calls == []


def test_enrichment_failure_is_observable():
    def broken(symbol, payload):
        raise RuntimeError("provider unavailable")

    result = StockEnricher(providers={"sector": broken}).enrich({"symbol": "ABC", "df": None})

    assert result.success is False
    assert result.failures
    assert result.failures[0].startswith("sector:")
