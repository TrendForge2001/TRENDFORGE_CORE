from __future__ import annotations

from typing import Any, Iterable

from engines.base_engine import BaseEngine, EngineResult
from engines.fundamental_contract import FundamentalInputContract
from config.fundamental_config import FUNDAMENTAL_CONFIG


class FundamentalEngine(BaseEngine):
    NAME = "Fundamental Engine"
    MAX_SCORE = 53

    def __init__(self, input_contract=None):
        self.cfg = FUNDAMENTAL_CONFIG
        self.input_contract = input_contract or FundamentalInputContract()

    @staticmethod
    def _grade(confidence: float) -> str:
        return (
            "A+" if confidence >= 90
            else "A" if confidence >= 80
            else "B" if confidence >= 70
            else "C" if confidence >= 60
            else "D"
        )

    def _weight(self, field: str) -> float:
        config = self.cfg.get(field, {})
        try:
            return float(config.get("weight", 0))
        except (TypeError, ValueError):
            return 0.0

    def _failure(
        self,
        report,
        *,
        max_score: float | None = None,
        warnings: list[str] | None = None,
    ) -> EngineResult:
        return EngineResult(
            engine=self.NAME,
            passed=False,
            score=0.0,
            max_score=self.MAX_SCORE if max_score is None else max_score,
            confidence=0.0,
            grade="N/A",
            reasons=[],
            warnings=warnings or ["Fundamental input contract failed"],
            metrics={"input_contract": report.as_dict()},
        )

    def _score(
        self,
        stock: dict[str, Any],
        *,
        excluded_fields: Iterable[str] = (),
        data_confidence_pct: float = 100.0,
        report=None,
    ) -> EngineResult:
        excluded = tuple(dict.fromkeys(str(item) for item in excluded_fields))
        unsupported = [
            field
            for field in excluded
            if field not in self.input_contract.REQUIRED
        ]
        if unsupported:
            raise ValueError(
                "Unsupported fundamental score exclusions: "
                + ", ".join(unsupported)
            )

        effective_max = self.MAX_SCORE - sum(
            self._weight(field) for field in excluded
        )
        if effective_max <= 0:
            raise ValueError("Effective fundamental max score must be positive")

        score = 0.0
        reasons: list[str] = []
        warnings = list(getattr(report, "warnings", []) or [])
        metrics: dict[str, Any] = {
            "input_contract": report.as_dict() if report is not None else None,
            "excluded_fields": list(excluded),
            "effective_max_score": float(effective_max),
            "data_confidence_pct": round(float(data_confidence_pct), 2),
        }

        def add(name, value, tiers, warning=None):
            nonlocal score
            if name in excluded:
                metrics[name] = None
                return
            value = float(value or 0)
            metrics[name] = value
            for threshold, points in tiers:
                if value >= threshold:
                    score += points
                    return
            if warning:
                warnings.append(warning)

        roce = stock["roce"]
        add(
            "roce",
            roce,
            [(30, 8), (25, 7), (20, 6), (15, 4)],
            "Low ROCE",
        )
        if "roce" not in excluded and float(roce) >= 15:
            reasons.append("ROCE meets quality threshold")

        roe = stock["roe"]
        add(
            "roe",
            roe,
            [(20, 6), (15, 5), (10, 3)],
            "Low ROE",
        )
        if "roe" not in excluded and float(roe) >= 15:
            reasons.append("ROE meets quality threshold")

        add(
            "sales_growth",
            stock.get("sales_growth"),
            [(25, 7), (20, 6), (15, 5), (10, 3)],
        )
        add(
            "profit_growth",
            stock.get("profit_growth"),
            [(25, 7), (20, 6), (15, 5), (10, 3)],
        )
        add(
            "eps_growth",
            stock.get("eps_growth"),
            [(25, 6), (20, 5), (15, 4), (10, 2)],
        )

        if "debt_equity" not in excluded:
            debt = float(stock["debt_equity"])
            metrics["debt_equity"] = debt
            if debt <= 0.25:
                score += 8
            elif debt <= 0.5:
                score += 7
            elif debt <= 1:
                score += 5
            elif debt <= 2:
                score += 2
            else:
                warnings.append("High Debt")
        else:
            metrics["debt_equity"] = None

        if "promoter_holding" not in excluded:
            promoter = float(stock["promoter_holding"])
            metrics["promoter_holding"] = promoter
            if promoter >= 70:
                score += 6
            elif promoter >= 60:
                score += 5
            elif promoter >= 50:
                score += 4
            else:
                warnings.append("Low Promoter Holding")
        else:
            metrics["promoter_holding"] = None

        if "pledged" not in excluded:
            pledged = float(stock["pledged"])
            metrics["pledged"] = pledged
            if pledged == 0:
                score += 5
            elif pledged <= 5:
                score += 4
            elif pledged <= 10:
                score += 2
            else:
                warnings.append("Promoter Shares Pledged")
        else:
            metrics["pledged"] = None

        score = min(float(effective_max), score)
        quality_score_pct = round(score / effective_max * 100, 2)
        confidence = round(
            min(quality_score_pct, float(data_confidence_pct)),
            2,
        )
        minimum_score = (
            float(self.cfg["minimum_score"])
            if not excluded
            else float(effective_max) * float(self.cfg["pass_ratio"])
        )
        passed = score >= minimum_score
        metrics["quality_score_pct"] = quality_score_pct
        metrics["minimum_score"] = round(minimum_score, 2)

        if excluded:
            warnings.append(
                "Excluded non-meaningful fundamental metric(s): "
                + ", ".join(excluded)
            )

        return EngineResult(
            engine=self.NAME,
            passed=passed,
            score=score,
            max_score=effective_max,
            confidence=confidence,
            grade=self._grade(confidence),
            reasons=reasons,
            warnings=list(dict.fromkeys(warnings)),
            metrics=metrics,
        )

    def evaluate(self, stock):
        report = self.input_contract.validate(stock)
        if not report.ready:
            return self._failure(report)

        payload = stock if isinstance(stock, dict) else {}
        return self._score(
            payload,
            excluded_fields=(),
            data_confidence_pct=100.0,
            report=report,
        )

    def evaluate_with_exclusions(
        self,
        stock: dict[str, Any],
        *,
        excluded_fields: Iterable[str],
        data_confidence_pct: float,
    ) -> EngineResult:
        excluded = tuple(dict.fromkeys(str(item) for item in excluded_fields))
        report = self.input_contract.validate(stock)

        unexpected_missing = [
            field for field in report.missing if field not in excluded
        ]
        unexpected_invalid = [
            field for field in report.invalid if field not in excluded
        ]
        if unexpected_missing or unexpected_invalid:
            return self._failure(
                report,
                max_score=self.MAX_SCORE - sum(
                    self._weight(field) for field in excluded
                ),
            )

        payload = stock if isinstance(stock, dict) else {}
        return self._score(
            payload,
            excluded_fields=excluded,
            data_confidence_pct=data_confidence_pct,
            report=report,
        )


__all__ = ["FundamentalEngine"]
