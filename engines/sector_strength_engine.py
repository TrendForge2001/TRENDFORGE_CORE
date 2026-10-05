from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional

from models.sector_score import SectorScore


class SectorStrengthEngine:

    NAME = "Sector Strength Engine"

    def __init__(self, provider=None):
        self.provider = provider
        self._discover_provider()

    def evaluate(self) -> Dict[str, SectorScore]:
        snapshots = self._get_snapshots()
        results = {}

        for snapshot in snapshots:
            data = self._normalize(snapshot)

            sector = str(
                data.get("sector")
                or data.get("name")
                or ""
            ).strip()

            if not sector:
                continue

            score = self._score(data)
            confidence = self._confidence(data)
            trend = self._trend(data)

            results[sector] = SectorScore(
                sector=sector,
                score=round(score, 2),
                rank=0,
                confidence=round(confidence, 2),
                trend=trend,
                reasons=self._reasons(data, trend),
            )

        ranked = sorted(
            results.values(),
            key=lambda x: x.score,
            reverse=True,
        )

        for rank, result in enumerate(
            ranked,
            start=1,
        ):
            result.rank = rank

        return {
            result.sector: result
            for result in ranked
        }

    def _discover_provider(self):
        if self.provider is not None:
            return

        self.provider = None

    def _get_snapshots(self) -> List[Any]:
        if self.provider is None:
            return []

        method = getattr(
            self.provider,
            "get_all_sectors",
            None,
        )

        if not callable(method):
            return []

        try:
            result = method()
        except Exception:
            return []

        if isinstance(result, Mapping):
            result = (
                result.get("data")
                or result.get("sectors")
                or result.get("results")
                or []
            )

        if not isinstance(
            result,
            (list, tuple, set),
        ):
            return []

        return list(result)

    def _score(
        self,
        data: Dict[str, Any],
    ) -> float:

        components = []

        momentum = self._momentum(data)

        if momentum is not None:
            components.append(
                (momentum, 40.0)
            )

        rs = self._relative_strength(data)

        if rs is not None:
            components.append(
                (rs, 20.0)
            )

        volume = self._volume(data)

        if volume is not None:
            components.append(
                (volume, 10.0)
            )

        breadth = self._breadth(data)

        if breadth is not None:
            components.append(
                (breadth, 15.0)
            )

        flows = self._flows(data)

        if flows is not None:
            components.append(
                (flows, 10.0)
            )

        leadership = self._number(
            data.get("leadership_score")
        )

        if leadership is not None:
            components.append(
                (
                    self._scale_100(leadership),
                    5.0,
                )
            )

        if not components:
            return 50.0

        weighted = sum(
            value * weight
            for value, weight in components
        )

        weights = sum(
            weight
            for _, weight in components
        )

        return self._clamp(
            weighted / weights,
            0.0,
            100.0,
        )

    def _momentum(
        self,
        data: Dict[str, Any],
    ) -> Optional[float]:

        values = []

        for key, weight in (
            ("change_1d", 0.15),
            ("change_1w", 0.25),
            ("change_1m", 0.35),
            ("change_3m", 0.25),
        ):
            value = self._number(
                data.get(key)
            )

            if value is not None:
                values.append(
                    (
                        self._return_score(value),
                        weight,
                    )
                )

        if not values:
            return None

        return sum(
            value * weight
            for value, weight in values
        ) / sum(
            weight
            for _, weight in values
        )

    def _relative_strength(
        self,
        data: Dict[str, Any],
    ) -> Optional[float]:

        value = self._number(
            data.get("relative_strength")
        )

        if value is None:
            return None

        if 0 <= value <= 100:
            return value

        return self._clamp(
            50 + value * 5,
            0,
            100,
        )

    def _volume(
        self,
        data: Dict[str, Any],
    ) -> Optional[float]:

        value = self._number(
            data.get("volume_ratio")
        )

        if value is None:
            return None

        if value >= 2:
            return 100.0
        if value >= 1.5:
            return 85.0
        if value >= 1.2:
            return 70.0
        if value >= 1:
            return 55.0
        if value >= 0.8:
            return 35.0

        return 15.0

    def _breadth(
        self,
        data: Dict[str, Any],
    ) -> Optional[float]:

        advancing = self._number(
            data.get("advancing")
        )

        declining = self._number(
            data.get("declining")
        )

        if (
            advancing is None
            or declining is None
        ):
            return None

        total = advancing + declining

        if total <= 0:
            return None

        return (
            advancing
            / total
            * 100
        )

    def _flows(
        self,
        data: Dict[str, Any],
    ) -> Optional[float]:

        fii = self._number(
            data.get("fii_flow")
        )

        dii = self._number(
            data.get("dii_flow")
        )

        values = [
            value
            for value in (
                fii,
                dii,
            )
            if value is not None
        ]

        if not values:
            return None

        average = sum(values) / len(values)

        return self._clamp(
            50 + average / 10,
            0,
            100,
        )

    def _trend(
        self,
        data: Dict[str, Any],
    ) -> str:

        score = self._score(data)

        if score >= 75:
            return "STRONG_BULLISH"

        if score >= 60:
            return "BULLISH"

        if score <= 30:
            return "STRONG_BEARISH"

        if score <= 45:
            return "BEARISH"

        return "NEUTRAL"

    def _confidence(
        self,
        data: Dict[str, Any],
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
            data.get(key) is not None
            for key in fields
        )

        if available >= 9:
            return 90.0

        if available >= 7:
            return 80.0

        if available >= 5:
            return 68.0

        if available >= 3:
            return 50.0

        if available >= 1:
            return 30.0

        return 10.0

    def _reasons(
        self,
        data: Dict[str, Any],
        trend: str,
    ) -> List[str]:

        reasons = []

        if trend in (
            "STRONG_BULLISH",
            "BULLISH",
        ):
            reasons.append(
                "Sector momentum is positive."
            )

        elif trend in (
            "STRONG_BEARISH",
            "BEARISH",
        ):
            reasons.append(
                "Sector momentum is weak."
            )

        rs = self._number(
            data.get("relative_strength")
        )

        if rs is not None:
            if (
                rs >= 60
                or rs > 2
            ):
                reasons.append(
                    "Sector is showing relative strength."
                )
            elif (
                rs <= 40
                or rs < -2
            ):
                reasons.append(
                    "Sector is showing relative weakness."
                )

        volume = self._number(
            data.get("volume_ratio")
        )

        if volume is not None and volume >= 1.2:
            reasons.append(
                "Sector participation is above average."
            )

        advancing = self._number(
            data.get("advancing")
        )

        declining = self._number(
            data.get("declining")
        )

        if (
            advancing is not None
            and declining is not None
            and advancing > declining
        ):
            reasons.append(
                "Sector breadth is positive."
            )

        leadership = self._number(
            data.get("leadership_score")
        )

        if leadership is not None and leadership >= 70:
            reasons.append(
                "Sector is acting as a rotation leader."
            )

        return self._dedupe(reasons)

    @staticmethod
    def _return_score(
        value: float,
    ) -> float:

        return max(
            0.0,
            min(
                100.0,
                50.0 + value * 5.0,
            ),
        )

    @staticmethod
    def _scale_100(
        value: float,
    ) -> float:

        if 0 <= value <= 100:
            return value

        return max(
            0.0,
            min(
                100.0,
                50.0 + value * 5.0,
            ),
        )

    @staticmethod
    def _normalize(
        value: Any,
    ) -> Dict[str, Any]:

        if isinstance(value, Mapping):
            return dict(value)

        if is_dataclass(value):
            try:
                return asdict(value)
            except Exception:
                return {}

        if hasattr(value, "__dict__"):
            try:
                return dict(vars(value))
            except Exception:
                return {}

        return {}

    @staticmethod
    def _number(
        value: Any,
    ) -> Optional[float]:

        if value is None or value == "":
            return None

        try:
            if isinstance(value, str):
                value = (
                    value.replace(",", "")
                    .replace("%", "")
                    .replace("₹", "")
                    .strip()
                )

            result = float(value)

            if result != result:
                return None

            return result

        except (
            TypeError,
            ValueError,
        ):
            return None

    @staticmethod
    def _clamp(
        value: float,
        low: float,
        high: float,
    ) -> float:

        return max(
            low,
            min(
                high,
                float(value),
            ),
        )

    @staticmethod
    def _dedupe(
        values: Iterable[str],
    ) -> List[str]:

        result = []
        seen = set()

        for value in values:
            text = str(value).strip()

            if text and text not in seen:
                seen.add(text)
                result.append(text)

        return result


__all__ = [
    "SectorStrengthEngine",
]