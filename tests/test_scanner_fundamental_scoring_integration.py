from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from core.database import initialize_database
from database.repositories.fundamental_field_evidence_repository import (
    FundamentalFieldEvidenceRepository,
)
from database.repositories.fundamentals_repository import FundamentalsRepository
from engines.base_engine import BaseEngine, EngineResult
from engines.contracted_fundamental_engine import ContractedFundamentalEngine
from engines.engine_orchestrator import EngineOrchestrator
from providers.sqlite_fundamental_provider import SQLiteFundamentalProvider
from reconstruction.enrichment import StockEnricher
from scanner.full_pipeline import FullScannerPipeline


class FakeProvider:
    def candles(
        self,
        symbol: str,
        period: str = "6mo",
        interval: str = "1d",
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "open": [100.0, 101.0],
                "high": [102.0, 103.0],
                "low": [99.0, 100.0],
                "close": [101.0, 102.0],
                "volume": [1000.0, 1200.0],
            }
        )


class FakeIndicatorEngine:
    def calculate(self, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.copy()
        frame["ATR"] = 2.0
        frame["RSI"] = 60.0
        frame["ADX"] = 30.0
        frame["RVOL"] = 1.5
        frame["VWAP"] = frame["close"]
        return frame

    def latest(self, frame: pd.DataFrame) -> dict:
        return frame.iloc[-1].to_dict()


class FixedEngine(BaseEngine):
    mandatory = True

    def __init__(
        self,
        name: str,
        *,
        score: float = 90.0,
        max_score: float = 100.0,
        confidence: float = 90.0,
        metrics: dict | None = None,
    ) -> None:
        self.NAME = name
        self._score = score
        self._max_score = max_score
        self._confidence = confidence
        self._metrics = dict(metrics or {})

    def evaluate(self, stock: dict) -> EngineResult:
        return EngineResult(
            engine=self.NAME,
            passed=True,
            score=self._score,
            max_score=self._max_score,
            confidence=self._confidence,
            grade="A",
            metrics=dict(self._metrics),
        )


def _nm_evidence(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "field": "eps_growth",
        "value": None,
        "value_status": "N/M",
        "period_type": "CAGR",
        "period_label": "FY2023-FY2026",
        "period_start": "FY2023",
        "period_end": "FY2026",
        "methodology": "3Y_CAGR",
        "source_type": "SCREENER",
        "source": "Screener",
        "source_ref": f"https://example.test/{symbol}",
        "as_of": "2026-03-31",
        "reason": "NEGATIVE_BASE",
    }


def _seed_nm_rows(db_path: str) -> None:
    repository = FundamentalsRepository(db_path=db_path)
    evidence = FundamentalFieldEvidenceRepository(db_path=db_path)
    now = datetime.now(timezone.utc).isoformat()
    try:
        # 45 / 47 fundamental score.
        repository.save(
            {
                "symbol": "GVT&D",
                "roce": 30.0,
                "roe": 57.0,
                "sales_growth": 25.0,
                "profit_growth": 25.0,
                "eps_growth": None,
                "debt_to_equity": 0.20,
                "promoter_holding": 51.0,
                "pledged": 0.0,
                "source": "test",
                "as_of": now,
            }
        )
        # 37 / 47 fundamental score, including a >10% pledge warning.
        repository.save(
            {
                "symbol": "JYOTICNC",
                "roce": 30.0,
                "roe": 18.0,
                "sales_growth": 25.0,
                "profit_growth": 15.0,
                "eps_growth": None,
                "debt_to_equity": 0.50,
                "promoter_holding": 62.55,
                "pledged": 12.35,
                "source": "test",
                "as_of": now,
            }
        )
        evidence.add_many(
            [_nm_evidence("GVT&D"), _nm_evidence("JYOTICNC")]
        )
    finally:
        repository.close()
        evidence.close()


def _orchestrator() -> EngineOrchestrator:
    return EngineOrchestrator(
        engines=[
            FixedEngine(
                "Market Regime Engine",
                metrics={"regime": "BULLISH"},
            ),
            FixedEngine("Sector Engine"),
            ContractedFundamentalEngine(),
            FixedEngine("Corporate Action Engine"),
            FixedEngine("Big Shark Engine"),
            FixedEngine(
                "Technical Engine",
                metrics={
                    "close": 120.0,
                    "EMA_20": 115.0,
                    "EMA_50": 110.0,
                    "EMA_200": 100.0,
                },
            ),
            FixedEngine(
                "Price Action Engine",
                metrics={"direction": "BULLISH", "entry": 102.0},
            ),
            FixedEngine("Risk Engine", metrics={"entry": 102.0}),
        ]
    )


def _pipeline(db_path: str) -> FullScannerPipeline:
    provider = SQLiteFundamentalProvider(
        db_path=db_path,
        max_age_days=365,
    )
    enricher = StockEnricher(providers={"fundamentals": provider})
    return FullScannerPipeline(
        FakeProvider(),
        orchestrator=_orchestrator(),
        indicator_engine=FakeIndicatorEngine(),
        enricher=enricher,
    )


def test_scanner_exposes_gvtd_nm_fundamental_summary(tmp_path):
    db_path = str(tmp_path / "trendforge.db")
    initialize_database(db_path)
    _seed_nm_rows(db_path)

    result = _pipeline(db_path).analyze("GVT&D")
    summary = result["fundamental_scoring"]

    assert summary["state"] == "EVIDENCE_COMPLETE_NM"
    assert summary["eligible"] is True
    assert summary["score"] == 45.0
    assert summary["max_score"] == 47.0
    assert summary["normalized_score_pct"] == 95.74
    assert summary["confidence"] == 87.5
    assert summary["data_confidence_pct"] == 87.5
    assert summary["grade"] == "A"
    assert summary["excluded_fields"] == ["eps_growth"]
    assert summary["strict_contract_ready"] is False
    assert summary["strict_missing"] == ["eps_growth"]
    assert summary["configured_signal_weight"] == 0.20
    assert summary["effective_signal_weight"] == 0.20
    assert summary["weighted_signal_points_pre_penalty"] == 19.15

    assert result["engines"]["Fundamental Engine"]["max_score"] == 47.0
    assert result["signal"].overall_score == 91.15
    assert result["ranking_score"] == 91.15
    assert result["signal"].signal == "BUY"
    assert result["eligible"] is True


def test_scanner_exposes_jyoticnc_nm_score_and_pledge_warning(tmp_path):
    db_path = str(tmp_path / "trendforge.db")
    initialize_database(db_path)
    _seed_nm_rows(db_path)

    result = _pipeline(db_path).analyze("JYOTICNC")
    summary = result["fundamental_scoring"]

    assert summary["state"] == "EVIDENCE_COMPLETE_NM"
    assert summary["score"] == 37.0
    assert summary["max_score"] == 47.0
    assert summary["normalized_score_pct"] == 78.72
    assert summary["confidence"] == 78.72
    assert summary["data_confidence_pct"] == 87.5
    assert summary["grade"] == "B"
    assert summary["weighted_signal_points_pre_penalty"] == 15.74
    assert "High promoter pledge" in summary["warnings"]
    assert "Promoter Shares Pledged" in summary["warnings"]

    assert result["signal"].overall_score == 87.74
    assert result["ranking_score"] == 87.74
    assert result["signal"].signal == "ACCUMULATE"
    assert result["eligible"] is True


def test_analyze_many_ranks_on_final_weighted_signal_score(tmp_path):
    db_path = str(tmp_path / "trendforge.db")
    initialize_database(db_path)
    _seed_nm_rows(db_path)

    result = _pipeline(db_path).analyze_many(
        ["JYOTICNC", "GVT&D"],
        top_n=2,
    )

    assert result["count"] == 2
    assert [item["symbol"] for item in result["results"]] == [
        "GVT&D",
        "JYOTICNC",
    ]
    assert result["results"][0]["ranking_score"] == 91.15
    assert result["results"][1]["ranking_score"] == 87.74


def test_rank_key_prefers_final_signal_score_over_raw_engine_sum():
    class SignalLike:
        def __init__(self, score):
            self.overall_score = score

    high_raw_lower_signal = {
        "symbol": "NUMERIC",
        "score": 700.0,
        "confidence": 90.0,
        "signal": SignalLike(88.0),
    }
    lower_raw_higher_signal = {
        "symbol": "NM",
        "score": 695.0,
        "confidence": 87.5,
        "signal": SignalLike(91.0),
    }

    ranked = sorted(
        [high_raw_lower_signal, lower_raw_higher_signal],
        key=FullScannerPipeline._rank_key,
        reverse=True,
    )

    assert [item["symbol"] for item in ranked] == ["NM", "NUMERIC"]
