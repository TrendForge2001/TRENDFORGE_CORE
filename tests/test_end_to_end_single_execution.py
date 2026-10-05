from __future__ import annotations

from typing import Any

import pandas as pd

from api.scanner_service import ScannerService
from scanner.full_pipeline import FullScannerPipeline
from engines.engine_orchestrator import EngineOrchestrator


class CountingProvider:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame
        self.calls = 0

    def candles(self, symbol: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
        self.calls += 1
        return self.frame.copy()


class CountingIndicators:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame
        self.calls = 0

    def calculate(self, candles: pd.DataFrame) -> pd.DataFrame:
        self.calls += 1
        return self.frame.copy()

    def latest(self, frame: pd.DataFrame) -> dict[str, Any]:
        row = frame.iloc[-1]
        return row.to_dict()


class CountingEnricher:
    def __init__(self):
        self.calls = 0

    def enrich(self, stock: dict[str, Any]):
        self.calls += 1
        return {"shareholding": {"promoter": 50, "fii": 20, "dii": 15}}

    def merge(self, stock, enrichment):
        merged = dict(stock)
        merged.update(enrichment)
        return merged


def _frame(rows: int = 35) -> pd.DataFrame:
    values = list(range(100, 100 + rows))
    return pd.DataFrame({
        "open": values,
        "high": [v + 2 for v in values],
        "low": [v - 2 for v in values],
        "close": values,
        "volume": [1000] * rows,
        "EMA_9": values,
        "EMA_20": values,
        "EMA_50": values,
        "EMA_100": values,
        "EMA_200": values,
        "RSI": [65] * rows,
        "MACD": [1] * rows,
        "MACD_SIGNAL": [0.5] * rows,
        "MACD_HIST": [0.5] * rows,
        "ADX": [30] * rows,
        "+DI": [25] * rows,
        "-DI": [15] * rows,
        "RVOL": [1.2] * rows,
        "VWAP": values,
        "CMF": [0.2] * rows,
        "MFI": [60] * rows,
        "ATR": [2] * rows,
        "ATR_PERCENT": [2] * rows,
        "BB_WIDTH": [4] * rows,
        "SUPPORT": [95] * rows,
        "RESISTANCE": [140] * rows,
        "BREAKOUT": [False] * rows,
        "BREAKDOWN": [False] * rows,
        "UPTREND": [True] * rows,
        "DOWNTREND": [False] * rows,
    })


def test_full_application_chain_has_single_provider_and_indicator_execution():
    frame = _frame()
    provider = CountingProvider(frame)
    indicators = CountingIndicators(frame)
    enricher = CountingEnricher()
    pipeline = FullScannerPipeline(provider, indicator_engine=indicators, enricher=enricher,
                                    orchestrator=EngineOrchestrator())
    service = ScannerService(pipeline)

    result = service.scan("ABC")

    assert result["symbol"] == "ABC"
    assert provider.calls == 1
    assert indicators.calls == 1
    assert enricher.calls == 1
    assert "engines" in result
    assert "input_contract" in result


def test_batch_scan_deduplicates_symbols_at_the_application_boundary():
    frame = _frame()
    provider = CountingProvider(frame)
    indicators = CountingIndicators(frame)
    pipeline = FullScannerPipeline(provider, indicator_engine=indicators, orchestrator=EngineOrchestrator())
    service = ScannerService(pipeline)

    service.scan_many(["ABC", "ABC", "DEF", "def"])

    assert provider.calls == 2
    assert indicators.calls == 2
