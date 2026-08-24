"""End-to-end contract tests for the canonical ScanPipeline."""
from __future__ import annotations

import pandas as pd

from pipeline.scan_pipeline import ScanPipeline


class Result:
    def __init__(self, symbol, score, signal="BUY"):
        self.symbol = symbol
        self.score = score
        self.overall_score = score
        self.confidence = score
        self.signal = signal


class Scanner:
    def scan_payload_many(self, payloads, capital=0):
        return [Result(symbol, float(len(payload["df"]))) for symbol, payload in payloads.items()]


class Ranking:
    def rank(self, signals):
        return sorted(signals, key=lambda item: item.score, reverse=True)


class Dashboard:
    def build(self, signals):
        return {"total": len(signals)}


def frame(rows=40):
    return pd.DataFrame({
        "open": range(rows), "high": range(1, rows + 1),
        "low": range(rows), "close": range(1, rows + 1),
        "volume": [1000] * rows,
    })


def test_pipeline_runs_end_to_end_and_ranks_results():
    sizes = {"AAA": 40, "BBB": 50}
    pipeline = ScanPipeline(
        scanner=Scanner(), ranking=Ranking(), dashboard=Dashboard(),
        data_loader=lambda symbol: frame(sizes[symbol]),
    )
    result = pipeline.run(symbols=["AAA", "BBB"], top_n=1)
    assert result["universe_size"] == 2
    assert result["market_data_loaded"] == 2
    assert result["analyzed_count"] == 2
    assert result["ranked"][0].symbol == "BBB"
    assert len(result["top_picks"]) == 1
    assert result["summary"]["total"] == 2


def test_pipeline_isolates_loader_failure():
    def loader(symbol):
        if symbol == "BAD":
            raise RuntimeError("feed unavailable")
        return frame(40)

    pipeline = ScanPipeline(
        scanner=Scanner(), ranking=Ranking(), dashboard=Dashboard(), data_loader=loader
    )
    result = pipeline.run(symbols=["GOOD", "BAD"])
    assert result["analyzed_count"] == 1
    assert result["rejected_count"] == 1
    assert result["rejected"][0]["symbol"] == "BAD"


def test_pipeline_health_reports_runtime_configuration():
    pipeline = ScanPipeline(Scanner(), Ranking(), Dashboard(), data_loader=lambda _: frame())
    health = pipeline.health()
    assert health["status"] == "healthy"
    assert health["market_data_configured"] is True
    assert health["normalizer_configured"] is True
