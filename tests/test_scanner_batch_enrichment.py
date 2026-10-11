from __future__ import annotations

from reconstruction.contracts import EnrichmentResult
from scanner.full_pipeline import FullScannerPipeline


class BatchMarketProvider:
    def __init__(self):
        self.calls = 0

    def batch_candles_with_errors(
        self,
        symbols,
        period="6mo",
        interval="1d",
    ):
        self.calls += 1
        return ({symbol: object() for symbol in symbols}, {})


class TrackingEnricher:
    def __init__(self):
        self.batch_calls = 0
        self.seen = []

    def enrich_many(self, stocks):
        self.batch_calls += 1
        self.seen.append(list(stocks))
        return {
            symbol: EnrichmentResult(
                symbol=symbol,
                data={"batch_marker": symbol},
                warnings=("fixture_warning",),
                failures=(),
            )
            for symbol in stocks
        }

    def merge(self, stock, result):
        merged = dict(stock)
        merged.update(result.data)
        merged["enrichment_warnings"] = list(result.warnings)
        merged["enrichment_failures"] = list(result.failures)
        return merged


class BatchPipeline(FullScannerPipeline):
    def _prepare(
        self,
        symbol,
        candles,
        capital=0.0,
        fundamentals=None,
    ):
        return {
            "symbol": symbol,
            "engine_input_contract": {"ready": True},
        }

    def _evaluate_enriched_stock(self, stock):
        assert stock["batch_marker"] == stock["symbol"]
        return {
            "symbol": stock["symbol"],
            "passed": True,
            "confidence": 80.0,
            "signal": "BUY",
            "engines": {},
            "execution_errors": [],
            "enrichment_warnings": stock.get(
                "enrichment_warnings",
                [],
            ),
            "enrichment_failures": stock.get(
                "enrichment_failures",
                [],
            ),
        }


def test_analyze_many_batches_enrichment_once_for_prepared_symbols():
    market = BatchMarketProvider()
    enricher = TrackingEnricher()
    pipeline = BatchPipeline(
        provider=market,
        enricher=enricher,
    )

    result = pipeline.analyze_many(
        ["AAA", "BBB", "CCC"],
        top_n=3,
    )

    assert market.calls == 1
    assert enricher.batch_calls == 1
    assert enricher.seen == [["AAA", "BBB", "CCC"]]
    assert result["scanned_count"] == 3
    assert result["rejected_count"] == 0
    assert [item["symbol"] for item in result["results"]] == [
        "CCC",
        "BBB",
        "AAA",
    ]


def test_scale_gate_groups_enrichment_failures_by_field():
    class FailurePipeline(FullScannerPipeline):
        def __init__(self):
            self.provider = object()

        def analyze_many(
            self,
            symbols,
            period="6mo",
            interval="1d",
            capital=0.0,
            top_n=20,
        ):
            items = [
                {
                    "symbol": symbol,
                    "passed": False,
                    "confidence": 0.0,
                    "signal": "HOLD",
                    "engines": {},
                    "execution_errors": [],
                    "enrichment_failures": [
                        "sector:live:blocked",
                        "corporate_actions:live:blocked",
                    ],
                }
                for symbol in symbols
            ]
            return self._finalize(items, top_n=top_n)

    pipeline = FailurePipeline()
    result = pipeline.analyze_many_batched(
        ["AAA", "BBB"],
        batch_size=2,
        batch_pause_seconds=0,
    )

    gate = result["scale_gate"]
    assert gate["enrichment_failures"] == 2
    assert gate["enrichment_failure_events"] == 4
    assert gate["enrichment_failure_fields"] == {
        "sector": 2,
        "corporate_actions": 2,
    }
    assert gate["enrichment_failure_details"]["AAA"] == [
        "sector:live:blocked",
        "corporate_actions:live:blocked",
    ]
