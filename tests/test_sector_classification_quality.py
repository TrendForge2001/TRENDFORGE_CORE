from __future__ import annotations

from engines.sector_engine import SectorEngine


def test_sector_engine_reports_classification_only_without_inventing_momentum():
    engine = SectorEngine()

    result = engine.evaluate(
        {
            "symbol": "ABC",
            "sector": {
                "sector": "Diversified",
                "industry": "Diversified",
                "_meta": {
                    "metadata_source": "NSE_NIFTY500_CSV",
                    "signal_evidence": False,
                },
            },
        }
    )

    assert result.passed is False
    assert result.score == 50.0
    assert result.confidence == 20.0
    assert result.metrics["sector"] == "Diversified"
    assert result.metrics["data_quality"] == "CLASSIFICATION_ONLY"
    assert any(
        "classification is available" in warning
        for warning in result.warnings
    )
