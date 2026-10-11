from __future__ import annotations

import math
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from engines.base_engine import BaseEngine, EngineResult


class SectorEngine(BaseEngine):
    """Sector rotation and relative-strength scoring engine."""

    NAME = "Sector Engine"
    priority = 6
    mandatory = False

    # Maximum contribution of each block. Sum = 100.
    MAX_MOMENTUM = 25.0
    MAX_RELATIVE_STRENGTH = 20.0
    MAX_VOLUME = 10.0
    MAX_BREADTH = 15.0
    MAX_FLOWS = 10.0
    MAX_LEADERSHIP = 10.0
    MAX_CONSISTENCY = 10.0

    # Thresholds are deliberately conservative. The engine is a confirmation
    # layer, not a standalone buy/sell generator.
    STRONG_SECTOR = 72.0
    BULLISH_SECTOR = 62.0
    NEUTRAL_SECTOR = 45.0
    WEAK_SECTOR = 35.0

    def __init__(self, provider=None, repository=None):
        self.provider = provider
        self.repository = repository

    # ==================================================================
    # PUBLIC API
    # ==================================================================

    def evaluate(self, stock: Any) -> EngineResult:
        payload = self._to_dict(stock)
        symbol = self._symbol(payload, stock)
        sector_name = self._sector_name(payload)

        snapshot = self._get_snapshot(
            symbol=symbol,
            sector=sector_name,
            payload=payload,
        )

        if snapshot is None:
            return self._empty_result(
                symbol=symbol,
                sector=sector_name,
            )

        normalized = self._normalize_snapshot(snapshot)
        components = self._score_components(normalized)

        score = self._weighted_score(components)
        confidence = self._confidence(normalized, components)
        trend = self._trend_label(score, normalized)
        bias = self._bias(score, normalized)

        reasons = self._build_reasons(
            normalized,
            components,
            score,
        )
        warnings = self._build_warnings(
            normalized,
            components,
        )

        passed = (
            score >= self.NEUTRAL_SECTOR
            and confidence >= 45.0
            and not self._hard_reject(normalized)
        )

        return EngineResult(
            engine=self.NAME,
            passed=passed,
            score=round(score, 2),
            confidence=round(confidence, 2),
            grade=self._grade(score),
            reasons=self._dedupe(reasons)[:30],
            warnings=self._dedupe(warnings)[:30],
            metrics={
                "symbol": symbol,
                "sector": sector_name or normalized.get("sector"),
                "score": round(score, 2),
                "confidence": round(confidence, 2),
                "trend": trend,
                "bias": bias,
                "sector_strength": self._sector_strength(score),
                "components": {
                    key: round(value, 2)
                    for key, value in components.items()
                },
                "snapshot": normalized,
                "hard_reject": self._hard_reject(normalized),
            },
        )

    def rank_sectors(
        self,
        snapshots: Optional[Sequence[Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Rank all available sectors from strongest to weakest."""

        if snapshots is None:
            snapshots = self._get_all_snapshots()

        results: List[Dict[str, Any]] = []

        for raw in snapshots or []:
            normalized = self._normalize_snapshot(raw)
            if not normalized.get("sector"):
                continue

            components = self._score_components(normalized)
            score = self._weighted_score(components)
            confidence = self._confidence(normalized, components)

            results.append(
                {
                    "sector": normalized["sector"],
                    "score": round(score, 2),
                    "confidence": round(confidence, 2),
                    "grade": self._grade(score),
                    "trend": self._trend_label(score, normalized),
                    "bias": self._bias(score, normalized),
                    "relative_strength": normalized.get("relative_strength"),
                    "change_1d": normalized.get("change_1d"),
                    "change_1w": normalized.get("change_1w"),
                    "change_1m": normalized.get("change_1m"),
                    "change_3m": normalized.get("change_3m"),
                    "volume_ratio": normalized.get("volume_ratio"),
                    "breadth": self._breadth_ratio(normalized),
                    "fii_flow": normalized.get("fii_flow"),
                    "dii_flow": normalized.get("dii_flow"),
                }
            )

        results.sort(
            key=lambda item: (
                item["score"],
                item["confidence"],
            ),
            reverse=True,
        )

        for rank, item in enumerate(results, start=1):
            item["rank"] = rank

        return results

    def top_sectors(
        self,
        limit: int = 10,
        snapshots: Optional[Sequence[Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Return the strongest sectors."""
        try:
            limit = max(1, int(limit))
        except (TypeError, ValueError):
            limit = 10

        return self.rank_sectors(snapshots)[:limit]

    def weak_sectors(
        self,
        limit: int = 10,
        snapshots: Optional[Sequence[Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Return the weakest sectors."""
        ranked = self.rank_sectors(snapshots)
        ranked.reverse()
        return ranked[: max(1, int(limit))]

    def sector_map(
        self,
        snapshots: Optional[Sequence[Any]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Return a sector -> score mapping useful to the scanner."""
        return {
            item["sector"]: item
            for item in self.rank_sectors(snapshots)
        }

    def health(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "engine": self.NAME,
            "priority": self.priority,
            "mandatory": self.mandatory,
            "coverage": [
                "Sector momentum",
                "Relative strength",
                "Volume participation",
                "Market breadth",
                "FII sector flow",
                "DII sector flow",
                "Leadership",
                "Trend consistency",
                "Sector ranking",
                "Sector rotation",
            ],
            "weights": {
                "momentum": self.MAX_MOMENTUM,
                "relative_strength": self.MAX_RELATIVE_STRENGTH,
                "volume": self.MAX_VOLUME,
                "breadth": self.MAX_BREADTH,
                "flows": self.MAX_FLOWS,
                "leadership": self.MAX_LEADERSHIP,
                "consistency": self.MAX_CONSISTENCY,
            },
        }

    # ==================================================================
    # DATA ACCESS
    # ==================================================================

    def _get_snapshot(
        self,
        symbol: str,
        sector: Optional[str],
        payload: Dict[str, Any],
    ) -> Optional[Any]:
        """Resolve the most specific sector snapshot available."""

        for key in (
            "sector_snapshot",
            "sector_data",
            "sector",
        ):
            value = payload.get(key)
            if self._looks_like_snapshot(value):
                return value

        if self.provider is not None:
            # Prefer symbol-aware provider methods because some providers map
            # the stock to its sector internally.
            for method_name in (
                "get_sector_for_stock",
                "get_stock_sector",
                "get_sector_snapshot",
                "get_sector",
            ):
                method = getattr(self.provider, method_name, None)
                if not callable(method):
                    continue

                for args in ((symbol,), (sector,),):
                    if not args[0]:
                        continue
                    try:
                        value = method(*args)
                        if self._looks_like_snapshot(value):
                            return value
                    except Exception:
                        continue

        if self.repository is not None:
            for method_name in (
                "get_sector_snapshot",
                "get_sector_for_stock",
                "by_sector",
            ):
                method = getattr(self.repository, method_name, None)
                if not callable(method):
                    continue

                for args in ((sector,), (symbol,),):
                    if not args[0]:
                        continue
                    try:
                        value = method(*args)
                        if self._looks_like_snapshot(value):
                            return value
                    except Exception:
                        continue

        return None

    def _get_all_snapshots(self) -> List[Any]:
        if self.provider is not None:
            for method_name in (
                "get_all_sectors",
                "get_sector_snapshots",
                "get_all_sector_snapshots",
                "fetch_all_sectors",
            ):
                method = getattr(self.provider, method_name, None)
                if not callable(method):
                    continue
                try:
                    result = method()
                    if isinstance(result, Mapping):
                        result = result.get("data", result.get("results", []))
                    if isinstance(result, (list, tuple)):
                        return list(result)
                except Exception:
                    continue

        if self.repository is not None:
            for method_name in (
                "get_all_sectors",
                "get_sector_snapshots",
                "all",
            ):
                method = getattr(self.repository, method_name, None)
                if not callable(method):
                    continue
                try:
                    result = method()
                    if isinstance(result, (list, tuple)):
                        return list(result)
                except Exception:
                    continue

        return []

    # ==================================================================
    # NORMALIZATION
    # ==================================================================

    @staticmethod
    def _to_dict(value: Any) -> Dict[str, Any]:
        if value is None:
            return {}

        if isinstance(value, Mapping):
            return dict(value)

        if is_dataclass(value):
            try:
                return asdict(value)
            except Exception:
                pass

        if hasattr(value, "__dict__"):
            try:
                return dict(vars(value))
            except Exception:
                pass

        return {}

    @classmethod
    def _normalize_snapshot(cls, raw: Any) -> Dict[str, Any]:
        source = cls._to_dict(raw)

        # Support nested provider payloads.
        for key in ("snapshot", "data", "sector_snapshot", "sector_data"):
            nested = source.get(key)
            if isinstance(nested, Mapping):
                merged = dict(nested)
                merged.update({
                    k: v
                    for k, v in source.items()
                    if k not in {key}
                })
                source = merged
                break

        normalized = {
            "sector": cls._text(
                source,
                "sector",
                "sector_name",
                "industry",
                "name",
            ),
            "index_price": cls._number(
                source,
                "index_price",
                "price",
                "close",
                "last_price",
            ),
            "change_1d": cls._number(
                source,
                "change_1d",
                "return_1d",
                "daily_return",
                "day_change",
            ),
            "change_1w": cls._number(
                source,
                "change_1w",
                "return_1w",
                "weekly_return",
                "week_change",
            ),
            "change_1m": cls._number(
                source,
                "change_1m",
                "return_1m",
                "monthly_return",
                "month_change",
            ),
            "change_3m": cls._number(
                source,
                "change_3m",
                "return_3m",
                "quarterly_return",
                "three_month_return",
            ),
            "volume_ratio": cls._number(
                source,
                "volume_ratio",
                "relative_volume",
                "volume_ma_ratio",
            ),
            "relative_strength": cls._number(
                source,
                "relative_strength",
                "rs",
                "rs_score",
                "relative_performance",
            ),
            "advancing": cls._number(
                source,
                "advancing",
                "advance",
                "advancers",
            ),
            "declining": cls._number(
                source,
                "declining",
                "decline",
                "decliners",
            ),
            "fii_flow": cls._number(
                source,
                "fii_flow",
                "fii",
                "foreign_flow",
            ),
            "dii_flow": cls._number(
                source,
                "dii_flow",
                "dii",
                "domestic_flow",
            ),
            "leadership_score": cls._number(
                source,
                "leadership_score",
                "leadership",
                "sector_leadership",
            ),
        }

        # Optional direct breadth values from providers.
        normalized["breadth_ratio"] = cls._number(
            source,
            "breadth_ratio",
            "breadth",
            "advance_decline_ratio",
        )

        # Optional ranking / metadata.
        normalized["rank"] = cls._number(
            source,
            "rank",
            "sector_rank",
        )
        normalized["market_return"] = cls._number(
            source,
            "market_return",
            "benchmark_return",
            "nifty_return",
        )
        normalized["data_timestamp"] = source.get(
            "data_timestamp",
            source.get("timestamp"),
        )

        return normalized

    @staticmethod
    def _symbol(
        payload: Dict[str, Any],
        stock: Any,
    ) -> str:
        if isinstance(stock, str):
            return stock.strip().upper()

        return str(
            payload.get("symbol")
            or payload.get("ticker")
            or payload.get("tradingsymbol")
            or ""
        ).strip().upper()

    @staticmethod
    def _sector_name(
        payload: Dict[str, Any],
    ) -> Optional[str]:
        value = (
            payload.get("sector_name")
            or payload.get("sector")
            or payload.get("industry")
        )

        if isinstance(value, Mapping):
            value = (
                value.get("sector")
                or value.get("sector_name")
                or value.get("name")
            )

        if value is None:
            return None

        text = str(value).strip()
        return text or None

    @staticmethod
    def _looks_like_snapshot(value: Any) -> bool:
        if value is None:
            return False

        source = SectorEngine._to_dict(value)
        if not source:
            return False

        keys = set(source)
        indicators = {
            "change_1d",
            "change_1w",
            "change_1m",
            "relative_strength",
            "volume_ratio",
            "leadership_score",
            "advancing",
            "declining",
        }
        return bool(keys & indicators)

    # ==================================================================
    # COMPONENT SCORING
    # ==================================================================

    def _score_components(
        self,
        snapshot: Dict[str, Any],
    ) -> Dict[str, float]:
        return {
            "momentum": self._momentum_score(snapshot),
            "relative_strength": self._relative_strength_score(snapshot),
            "volume": self._volume_score(snapshot),
            "breadth": self._breadth_score(snapshot),
            "flows": self._flow_score(snapshot),
            "leadership": self._leadership_score(snapshot),
            "consistency": self._consistency_score(snapshot),
        }

    def _weighted_score(
        self,
        components: Dict[str, float],
    ) -> float:
        # Each component is already expressed in its own maximum range.
        return self._clamp(
            sum(components.values()),
            0.0,
            100.0,
        )

    def _momentum_score(
        self,
        s: Dict[str, Any],
    ) -> float:
        values = [
            (s.get("change_1d"), 0.15),
            (s.get("change_1w"), 0.30),
            (s.get("change_1m"), 0.30),
            (s.get("change_3m"), 0.25),
        ]

        valid = [item for item in values if item[0] is not None]
        if not valid:
            return self.MAX_MOMENTUM * 0.5

        weighted = sum(float(value) * weight for value, weight in valid)
        total_weight = sum(weight for _, weight in valid)
        composite_return = weighted / total_weight

        # +/- 8% composite return maps approximately to 0..25.
        normalized = self._sigmoid_range(
            composite_return,
            low=-8.0,
            high=8.0,
        )
        return normalized * self.MAX_MOMENTUM

    def _relative_strength_score(
        self,
        s: Dict[str, Any],
    ) -> float:
        rs = s.get("relative_strength")

        if rs is None:
            # If provider did not supply an RS score, compare sector return
            # to the benchmark when possible.
            sector = self._momentum_return(s)
            benchmark = s.get("market_return")
            if sector is None or benchmark is None:
                return self.MAX_RELATIVE_STRENGTH * 0.5
            rs = sector - benchmark

            # Return spread is measured in percentage points.
            normalized = self._sigmoid_range(
                rs,
                low=-8.0,
                high=8.0,
            )
            return normalized * self.MAX_RELATIVE_STRENGTH

        # Some providers use 0..100, some use -100..100, and some provide a
        # return spread. Infer the common 0..100 representation first.
        rs_float = float(rs)
        if 0.0 <= rs_float <= 100.0:
            return self._clamp(
                rs_float / 100.0 * self.MAX_RELATIVE_STRENGTH,
                0.0,
                self.MAX_RELATIVE_STRENGTH,
            )

        return self._sigmoid_range(
            rs_float,
            low=-50.0,
            high=50.0,
        ) * self.MAX_RELATIVE_STRENGTH

    def _volume_score(
        self,
        s: Dict[str, Any],
    ) -> float:
        ratio = s.get("volume_ratio")
        if ratio is None:
            return self.MAX_VOLUME * 0.5

        # 0.5x = weak participation; 1.0x = normal; 1.5x+ = strong.
        normalized = self._linear_range(
            float(ratio),
            0.50,
            2.00,
        )
        return normalized * self.MAX_VOLUME

    def _breadth_score(
        self,
        s: Dict[str, Any],
    ) -> float:
        ratio = self._breadth_ratio(s)
        if ratio is None:
            return self.MAX_BREADTH * 0.5

        # A breadth ratio of 1 means equal advances/declines.  2 means strong
        # breadth, 0.5 means weak breadth.
        normalized = self._sigmoid_range(
            ratio,
            low=0.50,
            high=2.00,
        )
        return normalized * self.MAX_BREADTH

    def _flow_score(
        self,
        s: Dict[str, Any],
    ) -> float:
        fii = s.get("fii_flow")
        dii = s.get("dii_flow")

        values = [v for v in (fii, dii) if v is not None]
        if not values:
            return self.MAX_FLOWS * 0.5

        # Institutional flow is often provider-specific in units. We therefore
        # score the direction and use a soft saturation rather than hard units.
        positive = sum(1 for value in values if value > 0)
        negative = sum(1 for value in values if value < 0)
        neutral = len(values) - positive - negative

        direction = (positive - negative) / max(1, len(values))
        score = 0.5 + direction * 0.35

        # If both FII and DII agree, increase conviction.
        if len(values) == 2 and positive == 2:
            score += 0.15
        elif len(values) == 2 and negative == 2:
            score -= 0.15
        elif neutral:
            score -= 0.02

        return self._clamp(score, 0.0, 1.0) * self.MAX_FLOWS

    def _leadership_score(
        self,
        s: Dict[str, Any],
    ) -> float:
        value = s.get("leadership_score")
        if value is None:
            return self.MAX_LEADERSHIP * 0.5

        # Standard leadership_score is expected in 0..100.
        if 0 <= float(value) <= 100:
            normalized = float(value) / 100.0
        else:
            normalized = self._sigmoid_range(
                float(value),
                low=-50,
                high=50,
            )

        return self._clamp(
            normalized,
            0.0,
            1.0,
        ) * self.MAX_LEADERSHIP

    def _consistency_score(
        self,
        s: Dict[str, Any],
    ) -> float:
        returns = [
            s.get("change_1d"),
            s.get("change_1w"),
            s.get("change_1m"),
            s.get("change_3m"),
        ]
        returns = [float(x) for x in returns if x is not None]

        if len(returns) < 2:
            return self.MAX_CONSISTENCY * 0.5

        positive = sum(1 for x in returns if x > 0)
        negative = sum(1 for x in returns if x < 0)
        total = len(returns)

        # Strongest consistency when every available timeframe points in the
        # same direction. Slightly favour positive consistency.
        if positive == total:
            normalized = 1.0
        elif negative == total:
            normalized = 0.0
        else:
            normalized = positive / total
            if positive > negative:
                normalized += 0.10
            elif negative > positive:
                normalized -= 0.10

        return self._clamp(
            normalized,
            0.0,
            1.0,
        ) * self.MAX_CONSISTENCY

    # ==================================================================
    # INTERPRETATION
    # ==================================================================

    def _build_reasons(
        self,
        s: Dict[str, Any],
        c: Dict[str, float],
        score: float,
    ) -> List[str]:
        reasons: List[str] = []

        if c["momentum"] >= self.MAX_MOMENTUM * 0.75:
            reasons.append("Sector has strong multi-timeframe momentum")
        elif c["momentum"] <= self.MAX_MOMENTUM * 0.30:
            reasons.append("Sector momentum is weak")

        if c["relative_strength"] >= self.MAX_RELATIVE_STRENGTH * 0.75:
            reasons.append("Sector is showing strong relative strength")
        elif c["relative_strength"] <= self.MAX_RELATIVE_STRENGTH * 0.30:
            reasons.append("Sector is underperforming the benchmark")

        if c["volume"] >= self.MAX_VOLUME * 0.75:
            reasons.append("Sector participation is supported by volume")
        elif c["volume"] <= self.MAX_VOLUME * 0.30:
            reasons.append("Sector volume participation is weak")

        if c["breadth"] >= self.MAX_BREADTH * 0.75:
            reasons.append("Sector breadth is healthy")
        elif c["breadth"] <= self.MAX_BREADTH * 0.30:
            reasons.append("Sector breadth is weak")

        if c["flows"] >= self.MAX_FLOWS * 0.75:
            reasons.append("Institutional sector flows are supportive")
        elif c["flows"] <= self.MAX_FLOWS * 0.30:
            reasons.append("Institutional sector flows are negative")

        if c["leadership"] >= self.MAX_LEADERSHIP * 0.75:
            reasons.append("Sector is demonstrating market leadership")

        if c["consistency"] >= self.MAX_CONSISTENCY * 0.75:
            reasons.append("Sector trend is consistent across timeframes")

        if score >= self.STRONG_SECTOR:
            reasons.append("Sector is in a strong rotation regime")
        elif score <= self.WEAK_SECTOR:
            reasons.append("Sector is in a weak rotation regime")

        return reasons

    def _build_warnings(
        self,
        s: Dict[str, Any],
        c: Dict[str, float],
    ) -> List[str]:
        warnings: List[str] = []

        if c["breadth"] <= self.MAX_BREADTH * 0.30:
            warnings.append("Weak sector breadth")

        if c["volume"] <= self.MAX_VOLUME * 0.30:
            warnings.append("Low sector participation")

        if c["relative_strength"] <= self.MAX_RELATIVE_STRENGTH * 0.30:
            warnings.append("Sector relative weakness")

        if c["flows"] <= self.MAX_FLOWS * 0.30:
            warnings.append("Negative institutional sector flow")

        if self._momentum_return(s) is not None:
            returns = [
                s.get("change_1w"),
                s.get("change_1m"),
                s.get("change_3m"),
            ]
            valid = [float(x) for x in returns if x is not None]
            if len(valid) >= 2 and valid[-1] < valid[-2] < valid[0]:
                warnings.append("Sector momentum is deteriorating")

        return warnings

    def _trend_label(
        self,
        score: float,
        s: Dict[str, Any],
    ) -> str:
        if score >= self.STRONG_SECTOR:
            return "STRONG_UPTREND"
        if score >= self.BULLISH_SECTOR:
            return "UPTREND"
        if score >= self.NEUTRAL_SECTOR:
            return "NEUTRAL"
        if score >= self.WEAK_SECTOR:
            return "DOWNTREND"
        return "STRONG_DOWNTREND"

    def _bias(
        self,
        score: float,
        s: Dict[str, Any],
    ) -> str:
        if score >= self.STRONG_SECTOR:
            return "STRONGLY_BULLISH"
        if score >= self.BULLISH_SECTOR:
            return "BULLISH"
        if score >= self.NEUTRAL_SECTOR:
            return "NEUTRAL"
        if score >= self.WEAK_SECTOR:
            return "BEARISH"
        return "STRONGLY_BEARISH"

    def _sector_strength(self, score: float) -> str:
        if score >= self.STRONG_SECTOR:
            return "STRONG"
        if score >= self.BULLISH_SECTOR:
            return "GOOD"
        if score >= self.NEUTRAL_SECTOR:
            return "NEUTRAL"
        if score >= self.WEAK_SECTOR:
            return "WEAK"
        return "VERY_WEAK"

    def _hard_reject(
        self,
        s: Dict[str, Any],
    ) -> bool:
        # Only reject on very clear structural weakness. Missing data must not
        # be treated as a bearish event.
        returns = [
            s.get("change_1w"),
            s.get("change_1m"),
            s.get("change_3m"),
        ]
        valid = [float(x) for x in returns if x is not None]

        if len(valid) >= 2 and all(x <= -8 for x in valid):
            return True

        breadth = self._breadth_ratio(s)
        if breadth is not None and breadth <= 0.25:
            return True

        return False

    # ==================================================================
    # CONFIDENCE
    # ==================================================================

    def _confidence(
        self,
        s: Dict[str, Any],
        components: Dict[str, float],
    ) -> float:
        fields = (
            "change_1d",
            "change_1w",
            "change_1m",
            "change_3m",
            "volume_ratio",
            "relative_strength",
            "advancing",
            "declining",
            "fii_flow",
            "dii_flow",
            "leadership_score",
        )

        available = sum(
            1 for field in fields
            if s.get(field) is not None
        )
        availability = available / len(fields)

        # More independent confirmation blocks -> more confidence.
        active_components = sum(
            1
            for value in components.values()
            if value not in {
                0.0,
                5.0,
                7.5,
                10.0,
                12.5,
            }
        )
        component_factor = min(1.0, active_components / 7.0)

        confidence = 30.0
        confidence += availability * 45.0
        confidence += component_factor * 20.0

        timestamp = s.get("data_timestamp")
        if timestamp is not None:
            confidence += 5.0

        return self._clamp(confidence, 0.0, 100.0)

    # ==================================================================
    # HELPERS
    # ==================================================================

    def _breadth_ratio(
        self,
        s: Dict[str, Any],
    ) -> Optional[float]:
        direct = s.get("breadth_ratio")
        if direct is not None:
            value = float(direct)
            # Some providers use a 0..100 breadth percentage.
            if value > 10:
                return value / 100.0
            return value

        advancing = s.get("advancing")
        declining = s.get("declining")

        if advancing is None or declining is None:
            return None

        advancing = float(advancing)
        declining = float(declining)

        if declining <= 0:
            if advancing > 0:
                return 4.0
            return 1.0

        return advancing / declining

    def _momentum_return(
        self,
        s: Dict[str, Any],
    ) -> Optional[float]:
        values = (
            s.get("change_1w"),
            s.get("change_1m"),
            s.get("change_3m"),
        )
        valid = [float(x) for x in values if x is not None]
        if not valid:
            return None
        return sum(valid) / len(valid)

    @staticmethod
    def _number(
        source: Mapping[str, Any],
        *keys: str,
    ) -> Optional[float]:
        for key in keys:
            if key not in source:
                continue
            value = source.get(key)
            if value is None or value == "":
                continue
            try:
                if isinstance(value, str):
                    value = (
                        value.replace(",", "")
                        .replace("%", "")
                        .strip()
                    )
                number = float(value)
                if math.isfinite(number):
                    return number
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _text(
        source: Mapping[str, Any],
        *keys: str,
    ) -> Optional[str]:
        for key in keys:
            value = source.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return None

    @staticmethod
    def _linear_range(
        value: float,
        low: float,
        high: float,
    ) -> float:
        if high <= low:
            return 0.5
        return max(
            0.0,
            min(
                1.0,
                (value - low) / (high - low),
            ),
        )

    @staticmethod
    def _sigmoid_range(
        value: float,
        low: float,
        high: float,
    ) -> float:
        """Smoothly map value to 0..1 without overreacting to outliers."""
        if high <= low:
            return 0.5

        midpoint = (low + high) / 2.0
        scale = (high - low) / 6.0
        scale = max(scale, 1e-9)

        try:
            result = 1.0 / (
                1.0 + math.exp(
                    -(value - midpoint) / scale
                )
            )
        except OverflowError:
            result = 0.0 if value < midpoint else 1.0

        return max(0.0, min(1.0, result))

    @staticmethod
    def _clamp(
        value: float,
        low: float,
        high: float,
    ) -> float:
        try:
            value = float(value)
        except (TypeError, ValueError):
            return low
        return max(low, min(high, value))

    @staticmethod
    def _dedupe(
        values: Iterable[str],
    ) -> List[str]:
        output: List[str] = []
        seen = set()
        for value in values:
            text = str(value).strip()
            if text and text not in seen:
                seen.add(text)
                output.append(text)
        return output

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

    def _empty_result(
        self,
        symbol: str,
        sector: Optional[str],
    ) -> EngineResult:
        classification_only = bool(
            sector is not None
            and str(sector).strip()
        )
        warnings = (
            [
                "Sector classification is available, but sector "
                "momentum evidence is unavailable.",
                "Sector confirmation cannot be established.",
            ]
            if classification_only
            else [
                "Sector snapshot unavailable.",
                "Sector confirmation cannot be established.",
            ]
        )
        return EngineResult(
            engine=self.NAME,
            passed=False,
            score=50.0,
            confidence=20.0,
            grade="D",
            reasons=[],
            warnings=warnings,
            metrics={
                "symbol": symbol,
                "sector": sector,
                "data_quality": (
                    "CLASSIFICATION_ONLY"
                    if classification_only
                    else "NONE"
                ),
                "bias": "UNKNOWN",
            },
        )


# ----------------------------------------------------------------------
# Factory
# ----------------------------------------------------------------------


def get_sector_engine(provider=None, repository=None) -> SectorEngine:
    return SectorEngine(
        provider=provider,
        repository=repository,
    )


__all__ = [
    "SectorEngine",
    "get_sector_engine",
]