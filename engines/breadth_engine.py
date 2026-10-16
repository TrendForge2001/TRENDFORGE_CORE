from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional

from engines.base_engine import BaseEngine, EngineResult


class BreadthEngine(BaseEngine):
    NAME = "Breadth Engine"
    priority = 16
    mandatory = False

    def __init__(self, provider=None):
        self.provider = provider

    def evaluate(self, stock: Mapping[str, Any]) -> EngineResult:
        data = self._data(stock)
        advances = self._number(
            self._first(data, "advances", "advancing_stocks")
        )
        declines = self._number(
            self._first(data, "declines", "declining_stocks")
        )
        unchanged = self._number(
            self._first(data, "unchanged", "unchanged_stocks")
        )
        total = self._number(
            self._first(data, "total_stocks", "total")
        )

        if total is None and any(v is not None for v in (advances, declines, unchanged)):
            total = sum(v or 0.0 for v in (advances, declines, unchanged))

        ad_ratio = None
        if advances is not None and declines is not None and declines > 0:
            ad_ratio = advances / declines

        breadth_pct = None
        if total and total > 0 and advances is not None and declines is not None:
            breadth_pct = (advances - declines) / total * 100.0

        new_highs = self._number(
            self._first(data, "new_highs", "new_52w_highs")
        )
        new_lows = self._number(
            self._first(data, "new_lows", "new_52w_lows")
        )
        high_low_ratio = None
        if new_highs is not None and new_lows is not None and new_lows > 0:
            high_low_ratio = new_highs / new_lows

        direction = self._direction(ad_ratio, breadth_pct, high_low_ratio)
        score = self._score(ad_ratio, breadth_pct, high_low_ratio)
        quality = self._quality(advances, declines, total, new_highs, new_lows)

        reasons = self._reasons(direction, ad_ratio, breadth_pct, high_low_ratio)
        warnings = self._warnings(advances, declines, total)
        confidence = {"HIGH": 84.0, "MEDIUM": 67.0, "LOW": 43.0, "NONE": 15.0}[quality]

        return EngineResult(
            engine=self.NAME,
            passed=direction in ("STRONG_BULLISH", "BULLISH"),
            score=round(score, 2),
            confidence=confidence,
            grade=self._grade(score),
            reasons=self._dedupe(reasons),
            warnings=self._dedupe(warnings),
            metrics={
                "direction": direction,
                "advances": advances,
                "declines": declines,
                "unchanged": unchanged,
                "total_stocks": total,
                "advance_decline_ratio": round(ad_ratio, 3) if ad_ratio is not None else None,
                "breadth_pct": round(breadth_pct, 3) if breadth_pct is not None else None,
                "new_highs": new_highs,
                "new_lows": new_lows,
                "high_low_ratio": round(high_low_ratio, 3) if high_low_ratio is not None else None,
                "data_quality": quality,
            },
        )

    @staticmethod
    def _direction(ad_ratio: Optional[float], breadth_pct: Optional[float], high_low_ratio: Optional[float]) -> str:
        bullish = bearish = total = 0
        if ad_ratio is not None:
            total += 1
            bullish += ad_ratio >= 1.5
            bearish += ad_ratio <= 0.67
        if breadth_pct is not None:
            total += 1
            bullish += breadth_pct >= 20
            bearish += breadth_pct <= -20
        if high_low_ratio is not None:
            total += 1
            bullish += high_low_ratio >= 1.5
            bearish += high_low_ratio <= 0.67
        if total == 0:
            return "UNKNOWN"
        if bullish == total:
            return "STRONG_BULLISH"
        if bearish == total:
            return "STRONG_BEARISH"
        if bullish > bearish:
            return "BULLISH"
        if bearish > bullish:
            return "BEARISH"
        return "MIXED"

    @staticmethod
    def _score(ad_ratio: Optional[float], breadth_pct: Optional[float], high_low_ratio: Optional[float]) -> float:
        values = []
        if ad_ratio is not None and ad_ratio > 0:
            values.append(50.0 + math.tanh(math.log(ad_ratio)) * 35.0)
        if breadth_pct is not None:
            values.append(max(0.0, min(100.0, 50.0 + breadth_pct)))
        if high_low_ratio is not None and high_low_ratio > 0:
            values.append(50.0 + math.tanh(math.log(high_low_ratio)) * 35.0)
        return max(0.0, min(100.0, sum(values) / len(values))) if values else 50.0

    @staticmethod
    def _reasons(direction: str, ad_ratio: Optional[float], breadth_pct: Optional[float], high_low_ratio: Optional[float]) -> List[str]:
        reasons = []
        if direction == "STRONG_BULLISH":
            reasons.append("Market breadth is strongly supportive.")
        elif direction == "BULLISH":
            reasons.append("Market breadth is supportive.")
        elif direction == "STRONG_BEARISH":
            reasons.append("Market breadth is strongly negative.")
        elif direction == "BEARISH":
            reasons.append("Market breadth is negative.")
        if ad_ratio is not None and ad_ratio >= 1.5:
            reasons.append("Advancing stocks materially outnumber declining stocks.")
        if breadth_pct is not None and breadth_pct >= 20:
            reasons.append("Advance-decline breadth is positive.")
        if high_low_ratio is not None and high_low_ratio >= 1.5:
            reasons.append("New highs outnumber new lows.")
        return reasons

    @staticmethod
    def _warnings(advances: Optional[float], declines: Optional[float], total: Optional[float]) -> List[str]:
        warnings = []
        if advances is None:
            warnings.append("Advancing stock count unavailable.")
        if declines is None:
            warnings.append("Declining stock count unavailable.")
        if total is None:
            warnings.append("Total breadth universe unavailable.")
        return warnings

    @staticmethod
    def _quality(advances: Optional[float], declines: Optional[float], total: Optional[float], new_highs: Optional[float], new_lows: Optional[float]) -> str:
        count = sum(v is not None for v in (advances, declines, total, new_highs, new_lows))
        if count >= 4:
            return "HIGH"
        if count >= 2:
            return "MEDIUM"
        if count >= 1:
            return "LOW"
        return "NONE"

    @staticmethod
    def _first(
        data: Mapping[str, Any],
        *keys: str,
    ) -> Any:
        for key in keys:
            if key in data and data.get(key) is not None:
                return data.get(key)
        return None

    @staticmethod
    def _data(stock: Any) -> Dict[str, Any]:
        if isinstance(stock, Mapping):
            return dict(stock)
        if hasattr(stock, "__dict__"):
            try:
                return dict(vars(stock))
            except Exception:
                pass
        return {}

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            if isinstance(value, str):
                value = value.replace(",", "").replace("%", "").replace("₹", "").strip()
            result = float(value)
            return result if math.isfinite(result) else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _grade(score: float) -> str:
        if score >= 90:
            return "A+"
        if score >= 80:
            return "A"
        if score >= 70:
            return "B"
        if score >= 60:
            return "C"
        if score >= 45:
            return "D"
        return "F"

    @staticmethod
    def _dedupe(values: Iterable[str]) -> List[str]:
        result, seen = [], set()
        for value in values:
            text = str(value).strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
        return result

    def health(self) -> Dict[str, Any]:
        return {"status": "healthy", "engine": self.NAME, "priority": self.priority, "mandatory": self.mandatory}


def get_breadth_engine(provider=None) -> BreadthEngine:
    return BreadthEngine(provider=provider)


__all__ = ["BreadthEngine", "get_breadth_engine"]