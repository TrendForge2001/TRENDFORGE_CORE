from __future__ import annotations

from scanner.full_pipeline import FullScannerPipeline


class StubScalePipeline(FullScannerPipeline):
    def __init__(self, *, omit_symbol: str | None = None):
        self.provider = object()
        self.omit_symbol = omit_symbol
        self.calls = []

    def analyze_many(
        self,
        symbols,
        period="6mo",
        interval="1d",
        capital=0.0,
        top_n=20,
    ):
        self.calls.append(list(symbols))
        items = []
        for symbol in symbols:
            if symbol == self.omit_symbol:
                continue
            if symbol.endswith("7"):
                items.append(
                    self._error_result(
                        symbol,
                        "fixture market data failure",
                    )
                )
            else:
                items.append(
                    {
                        "symbol": symbol,
                        "passed": True,
                        "confidence": 80.0,
                        "signal": "BUY",
                        "engines": {},
                        "execution_errors": [],
                    }
                )
        return self._finalize(items, top_n=top_n)


def test_batched_scale_gate_accounts_for_every_unique_symbol():
    pipeline = StubScalePipeline()
    symbols = [f"SYM{i}" for i in range(53)]

    result = pipeline.analyze_many_batched(
        symbols,
        batch_size=20,
        top_n=5,
    )

    gate = result["scale_gate"]
    assert gate["requested_symbols"] == 53
    assert gate["unique_symbols"] == 53
    assert gate["accounted_symbols"] == 53
    assert gate["missing_symbols"] == 0
    assert gate["batch_size"] == 20
    assert gate["batch_count"] == 3
    assert gate["completion_pct"] == 100.0
    assert len(pipeline.calls) == 3
    assert [len(batch) for batch in pipeline.calls] == [20, 20, 13]

    all_items = list(result["results"]) + list(result["rejected"])
    assert len(all_items) == 53
    assert len({item["symbol"] for item in all_items}) == 53


def test_batched_scale_gate_surfaces_symbol_errors_without_silent_loss():
    pipeline = StubScalePipeline()
    symbols = [f"SYM{i}" for i in range(20)]

    result = pipeline.analyze_many_batched(
        symbols,
        batch_size=8,
    )

    gate = result["scale_gate"]
    assert gate["error_symbols"] == 2
    assert set(gate["errors"]) == {"SYM7", "SYM17"}
    assert gate["accounted_symbols"] == 20
    assert gate["missing_symbols"] == 0

    rejected = {
        item["symbol"]: item
        for item in result["rejected"]
    }
    assert rejected["SYM7"]["signal"] == "ERROR"
    assert rejected["SYM17"]["error"] == "fixture market data failure"


def test_batched_scale_gate_converts_missing_batch_output_to_explicit_error():
    pipeline = StubScalePipeline(omit_symbol="SYM4")
    symbols = [f"SYM{i}" for i in range(10)]

    result = pipeline.analyze_many_batched(
        symbols,
        batch_size=5,
    )

    gate = result["scale_gate"]
    assert gate["missing_symbols"] == 1
    assert gate["missing"] == ["SYM4"]
    assert gate["accounted_symbols"] == 10
    assert "SYM4" in gate["errors"]

    item = next(
        row for row in result["rejected"]
        if row["symbol"] == "SYM4"
    )
    assert item["error"] == "scanner_batch_missing_result"


def test_batched_scale_gate_deduplicates_normalized_symbols():
    pipeline = StubScalePipeline()

    result = pipeline.analyze_many_batched(
        [" aaa ", "AAA", "bbb"],
        batch_size=25,
    )

    gate = result["scale_gate"]
    assert gate["requested_symbols"] == 3
    assert gate["unique_symbols"] == 2
    assert gate["accounted_symbols"] == 2
    assert pipeline.calls == [["AAA", "BBB"]]
