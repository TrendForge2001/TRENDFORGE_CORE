"""TrendForge scoring engine.

This module is intentionally small and deterministic. It combines the scoring
categories already present in the repository without changing the project's
strategy semantics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
WEIGHTS_FILE = CONFIG_DIR / "scoring_weights.json"


@dataclass(slots=True)
class ScoreResult:
    total: float = 0.0
    technical: float = 0.0
    fundamental: float = 0.0
    options: float = 0.0
    corporate: float = 0.0
    risk: float = 0.0
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)


class ScoringEngine:
    """Calculate the repository's configured component scores."""

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = dict(weights) if weights is not None else self.load_weights()

    def add(
        self,
        result: ScoreResult,
        key: str,
        condition: bool,
        category: str,
        reason: str,
    ) -> None:
        if not condition:
            return
        value = float(self.weights.get(key, 0))
        result.total += value
        if hasattr(result, category):
            setattr(result, category, getattr(result, category) + value)
        result.reasons.append(reason)

    def technical_score(self, latest: Any, rules: Any, result: ScoreResult) -> None:
        self.add(result, "EMA_ALIGNMENT", rules.ema_bullish(latest), "technical", "EMA Alignment")
        self.add(result, "RSI", rules.rsi_bullish(latest), "technical", "Healthy RSI")
        self.add(result, "MACD", rules.macd_bullish(latest), "technical", "MACD Bullish")
        self.add(result, "ADX", rules.adx_strong(latest), "technical", "Strong ADX")
        self.add(result, "RVOL", rules.high_volume(latest), "technical", "High Relative Volume")
        self.add(result, "BREAKOUT", rules.breakout(latest), "technical", "20-Day Breakout")

    def fundamental_score(self, fundamentals: Any, rules: Any, result: ScoreResult) -> None:
        if fundamentals is None:
            return
        self.add(result, "ROE", fundamentals.roe > 15, "fundamental", "ROE > 15%")
        self.add(result, "ROCE", fundamentals.roce > 15, "fundamental", "ROCE > 15%")
        self.add(result, "PE", 0 < fundamentals.pe < 30, "fundamental", "Healthy PE")
        self.add(result, "DEBT", fundamentals.debt_to_equity < 0.5, "fundamental", "Low Debt")
        self.add(result, "SALES_GROWTH", fundamentals.sales_growth > 10, "fundamental", "Sales Growth")
        self.add(result, "PROFIT_GROWTH", fundamentals.profit_growth > 10, "fundamental", "Profit Growth")

    def options_score(self, latest: Any, rules: Any, result: ScoreResult) -> None:
        self.add(result, "LONG_BUILDUP", rules.long_buildup(latest), "options", "Long Build-up")
        self.add(result, "SHORT_COVERING", rules.short_covering(latest), "options", "Short Covering")

    def corporate_score(self, fundamentals: Any, rules: Any, result: ScoreResult) -> None:
        if fundamentals is None:
            return
        self.add(result, "EARNINGS", rules.earnings_today(fundamentals), "corporate", "Earnings Event")
        self.add(result, "BONUS", rules.bonus_issue(fundamentals), "corporate", "Bonus Issue")
        self.add(result, "DIVIDEND", rules.dividend_today(fundamentals), "corporate", "Dividend")

    def calculate_confidence(self, result: ScoreResult) -> None:
        maximum = sum(float(v) for v in self.weights.values() if isinstance(v, (int, float)))
        result.confidence = round(min(100.0, (result.total / maximum) * 100.0), 2) if maximum else 0.0

    def score(self, latest: Any, rules: Any, fundamentals: Any = None) -> ScoreResult:
        result = ScoreResult()
        self.technical_score(latest, rules, result)
        self.fundamental_score(fundamentals, rules, result)
        self.options_score(latest, rules, result)
        self.corporate_score(fundamentals, rules, result)
        self.calculate_confidence(result)
        return result

    def update_weight(self, key: str, value: float) -> None:
        self.weights[key] = float(value)
        self.save_weights()

    def reset_weights(self) -> None:
        self.weights = self.load_weights()

    def health(self) -> dict[str, Any]:
        return {"status": "healthy", "weights_loaded": len(self.weights), "version": "2.0"}

    @staticmethod
    def load_weights() -> dict[str, float]:
        if not WEIGHTS_FILE.exists():
            return {}
        with WEIGHTS_FILE.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("scoring_weights.json must contain an object")
        return {str(key): float(value) for key, value in data.items() if isinstance(value, (int, float))}

    def save_weights(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with WEIGHTS_FILE.open("w", encoding="utf-8") as handle:
            json.dump(self.weights, handle, indent=4)
