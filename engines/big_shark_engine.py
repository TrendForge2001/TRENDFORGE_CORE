"""
TrendForge v2
Big Shark / Institutional Activity Engine

Purpose
-------
Scores institutional accumulation/distribution for the Signal Engine.

Coverage
--------
- FII / foreign institutional investors
- DII
- Mutual funds
- Insurance institutions
- Promoter holding
- Promoter pledge
- Shareholding changes
- Block deals
- Bulk deals
- Large named shareholder movements
- Institutional breadth and conviction
- Data quality / confidence

Design
------
The engine is deliberately data-source agnostic.  It accepts data already
attached to the stock payload and can optionally query a provider/repository.

IMPORTANT:
This engine NEVER invents institutional activity when data is unavailable.
Missing data lowers confidence rather than producing a fake bullish score.
"""

from __future__ import annotations

import math
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from engines.base_engine import BaseEngine, EngineResult


class BigSharkEngine(BaseEngine):
    """Institutional activity scoring engine."""

    NAME = "Big Shark Engine"

    priority = 5
    mandatory = False

    MAX_OWNERSHIP = 30.0
    MAX_CHANGE = 25.0
    MAX_DEALS = 20.0
    MAX_PROMOTER = 15.0
    MAX_CONVICTION = 10.0

    BUY_WORDS = (
        "BUY",
        "BOUGHT",
        "PURCHASE",
        "PURCHASED",
        "ACCUMULATE",
        "ACCUMULATION",
        "ADDED",
        "INCREASE",
        "INCREASED",
    )

    SELL_WORDS = (
        "SELL",
        "SOLD",
        "SALE",
        "EXIT",
        "EXITED",
        "REDUCE",
        "REDUCED",
        "DECREASE",
        "DECREASED",
        "DISTRIBUTION",
    )

    RISK_WORDS = (
        "FRAUD",
        "DEFAULT",
        "INSOLVENCY",
        "BANKRUPTCY",
        "DELISTING",
    )

    CATEGORY_MAP = {
        "FII": "fii",
        "FOREIGN INSTITUTION": "fii",
        "FOREIGN INSTITUTIONAL": "fii",
        "FPI": "fii",
        "DII": "dii",
        "DOMESTIC INSTITUTION": "dii",
        "DOMESTIC INSTITUTIONAL": "dii",
        "MUTUAL FUND": "mutual_fund",
        "MUTUAL FUNDS": "mutual_fund",
        "MF": "mutual_fund",
        "INSURANCE": "insurance",
        "INSURER": "insurance",
        "PROMOTER": "promoter",
    }

    def __init__(self, provider=None, repository=None):
        self.provider = provider
        self.repository = repository
        # External acquisition is intentionally disabled; the canonical pipeline owns enrichment.

    # ==================================================================
    # PUBLIC
    # ==================================================================

    def evaluate(self, stock: Any) -> EngineResult:
        payload = self._normalise(stock)
        symbol = self._symbol(payload, stock)

        data = self._collect(symbol, payload)

        ownership = self._ownership(data)
        changes = self._changes(data)
        deals = self._deals(data)
        promoter = self._promoter(data)

        ownership_score, ownership_reasons = self._score_ownership(ownership)
        change_score, change_reasons = self._score_changes(changes)
        deal_score, deal_reasons = self._score_deals(deals)
        promoter_score, promoter_reasons = self._score_promoter(promoter)
        conviction_score, conviction_reasons = self._score_conviction(
            changes,
            deals,
        )

        score = self._clamp(
            ownership_score
            + change_score
            + deal_score
            + promoter_score
            + conviction_score,
            0.0,
            100.0,
        )

        quality = self._data_quality(data)
        confidence = self._confidence(
            score,
            quality,
            ownership,
            changes,
            deals,
            promoter,
        )

        hard_block = self._hard_block(
            promoter,
            data,
        )

        reasons = self._dedupe(
            ownership_reasons
            + change_reasons
            + deal_reasons
            + promoter_reasons
            + conviction_reasons
        )

        warnings = self._warnings(
            ownership,
            changes,
            deals,
            promoter,
            data,
        )

        if not quality:
            warnings.append(
                "Institutional/shareholding data unavailable."
            )

        passed = (
            score >= 55
            and not hard_block
        )

        return EngineResult(
            engine=self.NAME,
            passed=passed,
            score=round(score, 2),
            confidence=round(confidence, 2),
            grade=self._grade(score),
            reasons=reasons[:30],
            warnings=self._dedupe(warnings)[:20],
            metrics={
                "symbol": symbol,
                "score": round(score, 2),
                "confidence": round(confidence, 2),
                "data_quality": quality,
                "hard_block": hard_block,
                "institutional_bias": self._bias(
                    ownership,
                    changes,
                    deals,
                ),
                "ownership": ownership,
                "holding_changes": changes,
                "deals": deals[:25],
                "promoter": promoter,
                "conviction": self._conviction_metrics(
                    changes,
                    deals,
                ),
            },
        )

    # ==================================================================
    # DATA DISCOVERY
    # ==================================================================

    def _discover_dependencies(self):
        return

    def _collect(
        self,
        symbol: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:

        data: Dict[str, Any] = {}

        keys = (
            "shareholding",
            "shareholding_snapshot",
            "shareholders",
            "institutional_holders",
            "institutional_activity",
            "holding_changes",
            "fii",
            "dii",
            "mutual_fund",
            "mutual_funds",
            "insurance",
            "promoter",
            "block_deals",
            "bulk_deals",
            "deals",
        )

        for key in keys:
            value = payload.get(key)
            if value not in (None, "", [], {}):
                data[key] = value

        return data

    def _provider_data(self, symbol: str) -> Dict[str, Any]:
        if self.provider is None:
            return {}

        methods = (
            "get_shareholding",
            "get_shareholding_snapshot",
            "get_institutional_activity",
            "get_institutional_holders",
            "get_holders",
            "fetch_shareholding",
            "fetch_institutional_activity",
        )

        for method_name in methods:
            method = getattr(
                self.provider,
                method_name,
                None,
            )

            if not callable(method):
                continue

            try:
                result = method(symbol)
                result = self._to_dict(result)

                if result:
                    return result
            except Exception:
                continue

        return {}

    def _repository_data(self, symbol: str) -> Dict[str, Any]:
        if self.repository is None:
            return {}

        data: Dict[str, Any] = {}

        for method_name in (
            "by_symbol",
            "get_by_symbol",
            "latest_by_symbol",
            "shareholding_by_symbol",
        ):
            method = getattr(
                self.repository,
                method_name,
                None,
            )

            if not callable(method):
                continue

            try:
                value = method(symbol)

                if value:
                    data["shareholders"] = value
                    break
            except Exception:
                continue

        return data

    # ==================================================================
    # NORMALISATION
    # ==================================================================

    @staticmethod
    def _normalise(stock: Any) -> Dict[str, Any]:
        if isinstance(stock, Mapping):
            return dict(stock)

        if is_dataclass(stock):
            try:
                return asdict(stock)
            except Exception:
                pass

        result: Dict[str, Any] = {}

        for key in (
            "symbol",
            "ticker",
            "tradingsymbol",
            "shareholding",
            "shareholders",
            "institutional_activity",
            "holding_changes",
            "block_deals",
            "bulk_deals",
            "deals",
            "promoter",
        ):
            try:
                value = getattr(stock, key)
            except Exception:
                continue

            if value is not None:
                result[key] = value

        return result

    @staticmethod
    def _symbol(
        payload: Dict[str, Any],
        original: Any,
    ) -> str:

        if isinstance(original, str):
            return original.upper().strip()

        return str(
            payload.get("symbol")
            or payload.get("ticker")
            or payload.get("tradingsymbol")
            or ""
        ).upper().strip()

    # ==================================================================
    # OWNERSHIP
    # ==================================================================

    def _ownership(
        self,
        data: Dict[str, Any],
    ) -> Dict[str, Optional[float]]:

        source = (
            data.get("shareholding_snapshot")
            or data.get("shareholding")
            or data.get("institutional_activity")
            or {}
        )

        source = self._to_dict(source)

        institutional = self._to_dict(
            source.get("institutional")
        )

        result = {
            "promoter": self._first_num(
                source,
                "promoter",
                "promoter_holding",
            ),
            "fii": self._first_num(
                source,
                "fii",
                "fii_holding",
                "foreign_institutional",
                "foreign_institutional_holding",
            ),
            "dii": self._first_num(
                source,
                "dii",
                "dii_holding",
                "domestic_institutional",
                "domestic_institutional_holding",
            ),
            "mutual_fund": self._first_num(
                source,
                "mutual_fund",
                "mutual_funds",
                "mf",
                "mf_holding",
            ),
            "insurance": self._first_num(
                source,
                "insurance",
                "insurance_holding",
            ),
            "public": self._first_num(
                source,
                "public",
                "public_holding",
            ),
        }

        for key in (
            "fii",
            "dii",
            "mutual_fund",
            "insurance",
        ):
            if result[key] is None:
                result[key] = self._first_num(
                    institutional,
                    key,
                    f"{key}_holding",
                )

        return result

    # ==================================================================
    # HOLDING CHANGES
    # ==================================================================

    def _changes(
        self,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:

        raw = (
            data.get("holding_changes")
            or data.get("shareholders")
            or data.get("institutional_holders")
            or []
        )

        rows = self._rows(raw)

        result = {
            "fii": 0.0,
            "dii": 0.0,
            "mutual_fund": 0.0,
            "insurance": 0.0,
            "promoter": 0.0,
            "other": 0.0,
            "positive_entities": 0,
            "negative_entities": 0,
            "large_accumulators": 0,
            "large_distributors": 0,
            "rows": [],
        }

        for row in rows:
            category = self._category(row)
            change = self._change(row)

            value = self._first_num(
                row,
                "value",
                "value_crore",
                "transaction_value",
                "holding_value",
            )

            name = str(
                row.get("name")
                or row.get("holder")
                or row.get("shareholder")
                or row.get("client_name")
                or ""
            ).strip()

            if category in result:
                result[category] += change
            else:
                result["other"] += change

            if change > 0:
                result["positive_entities"] += 1

                if value is not None and value >= 25:
                    result["large_accumulators"] += 1

            elif change < 0:
                result["negative_entities"] += 1

                if value is not None and value >= 25:
                    result["large_distributors"] += 1

            result["rows"].append(
                {
                    "name": name,
                    "category": category,
                    "change": round(change, 4),
                    "value": value,
                    "quarter": (
                        row.get("quarter")
                        or row.get("period")
                        or row.get("date")
                    ),
                }
            )

        return result

    # ==================================================================
    # DEALS
    # ==================================================================

    def _deals(
        self,
        data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:

        raw = (
            data.get("deals")
            or data.get("block_deals")
            or data.get("bulk_deals")
            or []
        )

        result: List[Dict[str, Any]] = []

        for row in self._rows(raw):
            side = str(
                row.get("side")
                or row.get("transaction_type")
                or row.get("buy_sell")
                or row.get("type")
                or ""
            ).upper()

            value = self._first_num(
                row,
                "value",
                "value_crore",
                "transaction_value",
                "amount",
            )

            quantity = self._first_num(
                row,
                "quantity",
                "qty",
                "shares",
            )

            buyer = str(
                row.get("buyer")
                or row.get("client_name")
                or row.get("acquirer")
                or ""
            ).strip()

            seller = str(
                row.get("seller")
                or row.get("transferor")
                or ""
            ).strip()

            result.append(
                {
                    "side": side,
                    "value": value,
                    "quantity": quantity,
                    "buyer": buyer,
                    "seller": seller,
                    "date": (
                        row.get("date")
                        or row.get("trade_date")
                    ),
                }
            )

        return result

    # ==================================================================
    # PROMOTER
    # ==================================================================

    def _promoter(
        self,
        data: Dict[str, Any],
    ) -> Dict[str, Optional[float]]:

        raw = self._to_dict(
            data.get("promoter")
        )

        current = self._first_num(
            raw,
            "holding",
            "current",
            "current_holding",
            "promoter",
        )

        previous = self._first_num(
            raw,
            "previous",
            "previous_holding",
            "last_quarter",
            "prior_holding",
        )

        pledge = self._first_num(
            raw,
            "pledge",
            "pledged",
            "pledge_percent",
            "pledged_percent",
        )

        pledge_change = self._first_num(
            raw,
            "pledge_change",
            "pledge_change_percent",
            "pledged_change",
        )

        change = (
            current - previous
            if current is not None
            and previous is not None
            else 0.0
        )

        return {
            "current": current,
            "previous": previous,
            "change": change,
            "pledge": pledge,
            "pledge_change": pledge_change or 0.0,
        }

    # ==================================================================
    # SCORING: OWNERSHIP
    # ==================================================================

    def _score_ownership(
        self,
        ownership: Dict[str, Optional[float]],
    ) -> Tuple[float, List[str]]:

        score = 0.0
        reasons: List[str] = []

        configs = (
            ("fii", "FII", 8.0, 8.0),
            ("dii", "DII", 7.0, 7.0),
            ("mutual_fund", "Mutual Fund", 7.0, 7.0),
            ("insurance", "Insurance", 5.0, 5.0),
        )

        for key, label, cap, saturation in configs:
            value = ownership.get(key)

            if value is None:
                continue

            points = self._ownership_points(
                value,
                cap,
                saturation,
            )

            score += points

            if value >= saturation * 2:
                reasons.append(
                    f"Strong {label} ownership: {value:.2f}%"
                )
            elif value >= saturation:
                reasons.append(
                    f"Healthy {label} ownership: {value:.2f}%"
                )

        if score <= 0:
            reasons.append(
                "No institutional ownership data available"
            )

        return (
            self._clamp(
                score,
                0,
                self.MAX_OWNERSHIP,
            ),
            reasons,
        )

    # ==================================================================
    # SCORING: CHANGES
    # ==================================================================

    def _score_changes(
        self,
        changes: Dict[str, Any],
    ) -> Tuple[float, List[str]]:

        score = 0.0
        reasons: List[str] = []

        weights = (
            ("fii", "FII", 8.0),
            ("dii", "DII", 6.0),
            ("mutual_fund", "Mutual Fund", 6.0),
            ("insurance", "Insurance", 3.0),
        )

        for key, label, weight in weights:
            change = float(
                changes.get(key) or 0
            )

            if change > 0:
                points = min(
                    weight,
                    change * weight / 2,
                )
                score += points

                if change >= 0.5:
                    reasons.append(
                        f"{label} accumulation: +{change:.2f}%"
                    )

            elif change < 0:
                points = max(
                    -weight / 2,
                    change * weight / 2,
                )
                score += points

                if change <= -0.5:
                    reasons.append(
                        f"{label} distribution: {change:.2f}%"
                    )

        accumulators = int(
            changes.get("large_accumulators") or 0
        )

        distributors = int(
            changes.get("large_distributors") or 0
        )

        if accumulators:
            score += min(
                5,
                accumulators * 1.5,
            )
            reasons.append(
                "Large institutional accumulation detected"
            )

        if distributors:
            score -= min(
                5,
                distributors * 1.5,
            )
            reasons.append(
                "Large institutional distribution detected"
            )

        return (
            self._clamp(
                score,
                0,
                self.MAX_CHANGE,
            ),
            reasons,
        )

    # ==================================================================
    # SCORING: DEALS
    # ==================================================================

    def _score_deals(
        self,
        deals: List[Dict[str, Any]],
    ) -> Tuple[float, List[str]]:

        if not deals:
            return 0.0, []

        score = 0.0
        reasons: List[str] = []

        for deal in deals:
            side = str(
                deal.get("side") or ""
            ).upper()

            value = deal.get("value")

            if (
                "BUY" in side
                or "PURCHASE" in side
                or "ACQUIRE" in side
            ):
                score += 6

                reasons.append(
                    "Institutional block/bulk deal BUY detected"
                )

                if value is not None and value >= 100:
                    score += 4
                    reasons.append(
                        "Large-value institutional purchase"
                    )

            elif (
                "SELL" in side
                or "SALE" in side
                or "TRANSFER" in side
            ):
                score -= 5

                reasons.append(
                    "Institutional block/bulk deal SELL detected"
                )

                if value is not None and value >= 100:
                    score -= 3
                    reasons.append(
                        "Large-value institutional distribution"
                    )

        return (
            self._clamp(
                score,
                0,
                self.MAX_DEALS,
            ),
            reasons,
        )

    # ==================================================================
    # SCORING: PROMOTER
    # ==================================================================

    def _score_promoter(
        self,
        promoter: Dict[str, Optional[float]],
    ) -> Tuple[float, List[str]]:

        score = 0.0
        reasons: List[str] = []

        change = float(
            promoter.get("change") or 0
        )

        pledge = promoter.get("pledge")

        pledge_change = float(
            promoter.get("pledge_change") or 0
        )

        if change > 0:
            score += min(
                8,
                change * 2,
            )

            reasons.append(
                f"Promoter holding increased: +{change:.2f}%"
            )

        elif change < 0:
            score += max(
                0,
                4 + change * 2,
            )

            reasons.append(
                f"Promoter holding decreased: {change:.2f}%"
            )

        else:
            score += 4

        if pledge is not None:
            if pledge <= 2:
                score += 5
                reasons.append(
                    "Promoter pledge is low"
                )

            elif pledge <= 10:
                score += 3
                reasons.append(
                    "Moderate promoter pledge"
                )

            elif pledge <= 25:
                score += 1
                reasons.append(
                    "Elevated promoter pledge"
                )

            else:
                reasons.append(
                    "High promoter pledge risk"
                )

        if pledge_change > 0.5:
            score -= min(
                5,
                pledge_change,
            )

            reasons.append(
                "Promoter pledge is increasing"
            )

        elif pledge_change < -0.5:
            score += 2

            reasons.append(
                "Promoter pledge is declining"
            )

        return (
            self._clamp(
                score,
                0,
                self.MAX_PROMOTER,
            ),
            reasons,
        )

    # ==================================================================
    # SCORING: CONVICTION
    # ==================================================================

    def _score_conviction(
        self,
        changes: Dict[str, Any],
        deals: List[Dict[str, Any]],
    ) -> Tuple[float, List[str]]:

        positive = int(
            changes.get("positive_entities") or 0
        )

        negative = int(
            changes.get("negative_entities") or 0
        )

        large = int(
            changes.get("large_accumulators") or 0
        )

        large += int(
            changes.get("large_distributors") or 0
        )

        score = 0.0
        reasons: List[str] = []

        if positive > negative:
            score += min(
                6,
                (positive - negative) * 1.5,
            )

            reasons.append(
                "Institutional activity has positive breadth"
            )

        elif negative > positive:
            score += max(
                0,
                3 - (negative - positive),
            )

            reasons.append(
                "Institutional activity has negative breadth"
            )

        if large >= 2:
            score += 4

            reasons.append(
                "Multiple large institutional transactions"
            )

        elif large == 1:
            score += 2

        if len(deals) >= 3:
            score += 1

        return (
            self._clamp(
                score,
                0,
                self.MAX_CONVICTION,
            ),
            reasons,
        )

    def _conviction_metrics(
        self,
        changes,
        deals,
    ):
        return {
            "positive_entities": int(
                changes.get("positive_entities") or 0
            ),
            "negative_entities": int(
                changes.get("negative_entities") or 0
            ),
            "large_transactions": (
                int(changes.get("large_accumulators") or 0)
                + int(changes.get("large_distributors") or 0)
            ),
            "deal_count": len(deals),
        }

    # ==================================================================
    # RISK
    # ==================================================================

    def _hard_block(
        self,
        promoter: Dict[str, Optional[float]],
        data: Dict[str, Any],
    ) -> bool:

        pledge = promoter.get("pledge")

        pledge_change = float(
            promoter.get("pledge_change") or 0
        )

        if pledge is not None and pledge >= 60:
            return True

        if pledge_change >= 20:
            return True

        risk_text = str(
            data.get("risk") or ""
        ).upper()

        if any(
            word in risk_text
            for word in self.RISK_WORDS
        ):
            return True

        # Also inspect raw event/holder data for hard risk terms.
        raw_text = str(
            data.get("institutional_activity")
            or data.get("shareholding")
            or data.get("shareholders")
            or ""
        ).upper()

        return any(
            word in raw_text
            for word in self.RISK_WORDS
        )

    def _warnings(
        self,
        ownership,
        changes,
        deals,
        promoter,
        data,
    ) -> List[str]:

        warnings: List[str] = []

        pledge = promoter.get("pledge")

        pledge_change = float(
            promoter.get("pledge_change") or 0
        )

        if pledge is not None and pledge > 25:
            warnings.append(
                f"High promoter pledge: {pledge:.2f}%"
            )

        if pledge_change > 0.5:
            warnings.append(
                "Promoter pledge is increasing"
            )

        if changes.get("large_distributors"):
            warnings.append(
                "Large institutional selling detected"
            )

        if any(
            "SELL" in str(
                deal.get("side") or ""
            ).upper()
            for deal in deals
        ):
            warnings.append(
                "Recent block/bulk deal selling present"
            )

        if (
            ownership.get("fii") is None
            and ownership.get("dii") is None
            and ownership.get("mutual_fund") is None
        ):
            warnings.append(
                "Institutional ownership unavailable"
            )

        return warnings

    # ==================================================================
    # BIAS
    # ==================================================================

    def _bias(
        self,
        ownership,
        changes,
        deals,
    ) -> str:

        positive = 0.0
        negative = 0.0

        for key in (
            "fii",
            "dii",
            "mutual_fund",
            "insurance",
        ):
            value = ownership.get(key)

            if value is not None:
                positive += max(
                    0,
                    value,
                )

        for key in (
            "fii",
            "dii",
            "mutual_fund",
            "insurance",
        ):
            change = float(
                changes.get(key) or 0
            )

            if change > 0:
                positive += change * 10
            elif change < 0:
                negative += abs(change) * 10

        for deal in deals:
            side = str(
                deal.get("side") or ""
            ).upper()

            value = (
                deal.get("value")
                or 1
            )

            if "BUY" in side:
                positive += min(
                    20,
                    value / 10,
                )

            elif "SELL" in side:
                negative += min(
                    20,
                    value / 10,
                )

        if positive > negative * 1.25:
            return "ACCUMULATION"

        if negative > positive * 1.25:
            return "DISTRIBUTION"

        return "NEUTRAL"

    # ==================================================================
    # CONFIDENCE
    # ==================================================================

    def _confidence(
        self,
        score,
        quality,
        ownership,
        changes,
        deals,
        promoter,
    ) -> float:

        available = 0

        for value in (
            ownership.get("fii"),
            ownership.get("dii"),
            ownership.get("mutual_fund"),
            ownership.get("insurance"),
        ):
            if value is not None:
                available += 1

        if changes.get("rows"):
            available += 2

        if deals:
            available += 2

        if promoter.get("current") is not None:
            available += 1

        if promoter.get("pledge") is not None:
            available += 1

        quality_factor = min(
            1.0,
            available / 8,
        )

        confidence = (
            30
            + quality_factor * 40
            + score * 0.30
        )

        return self._clamp(
            confidence,
            0,
            100,
        )

    @staticmethod
    def _data_quality(
        data: Dict[str, Any],
    ) -> bool:

        return bool(
            data.get("shareholding")
            or data.get("shareholding_snapshot")
            or data.get("shareholders")
            or data.get("institutional_holders")
            or data.get("institutional_activity")
            or data.get("holding_changes")
            or data.get("deals")
            or data.get("block_deals")
            or data.get("bulk_deals")
        )

    # ==================================================================
    # GENERIC UTILITIES
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
                return {}

        if hasattr(value, "__dict__"):
            try:
                return dict(vars(value))
            except Exception:
                return {}

        return {}

    @classmethod
    def _rows(
        cls,
        value: Any,
    ) -> List[Dict[str, Any]]:

        if value is None:
            return []

        if isinstance(value, Mapping):
            for key in (
                "data",
                "results",
                "items",
                "rows",
                "shareholders",
                "holders",
                "deals",
            ):
                nested = value.get(key)

                if isinstance(
                    nested,
                    (list, tuple),
                ):
                    return [
                        cls._to_dict(item)
                        for item in nested
                    ]

            return [
                dict(value)
            ]

        if isinstance(
            value,
            (list, tuple, set),
        ):
            return [
                cls._to_dict(item)
                for item in value
            ]

        return []

    @staticmethod
    def _first_num(
        source: Mapping[str, Any],
        *keys: str,
    ) -> Optional[float]:

        for key in keys:
            if key not in source:
                continue

            try:
                value = source[key]

                if value is None:
                    continue

                if isinstance(
                    value,
                    str,
                ):
                    value = (
                        value
                        .replace(",", "")
                        .replace("%", "")
                        .strip()
                    )

                value = float(value)

                if math.isfinite(value):
                    return value

            except (
                TypeError,
                ValueError,
            ):
                continue

        return None

    @classmethod
    def _change(
        cls,
        row: Mapping[str, Any],
    ) -> float:

        direct = cls._first_num(
            row,
            "change",
            "change_percent",
            "holding_change",
            "qoq_change",
            "change_pct",
        )

        if direct is not None:
            return direct

        current = cls._first_num(
            row,
            "holding",
            "current_holding",
            "current",
        )

        previous = cls._first_num(
            row,
            "previous_holding",
            "previous",
            "last_quarter",
            "prior_holding",
        )

        if (
            current is not None
            and previous is not None
        ):
            return current - previous

        return 0.0

    @classmethod
    def _category(
        cls,
        row: Mapping[str, Any],
    ) -> str:

        text = str(
            row.get("category")
            or row.get("type")
            or row.get("holder_type")
            or row.get("classification")
            or row.get("investor_type")
            or ""
        ).upper()

        for key, value in cls.CATEGORY_MAP.items():
            if key in text:
                return value

        # Infer from holder name where provider omits type.
        name = str(
            row.get("name")
            or row.get("holder")
            or row.get("shareholder")
            or ""
        ).upper()

        for key, value in cls.CATEGORY_MAP.items():
            if key in name:
                return value

        return "other"

    @staticmethod
    def _ownership_points(
        value: float,
        cap: float,
        saturation: float,
    ) -> float:

        if value <= 0:
            return 0.0

        # Diminishing returns prevent ownership percentage from dominating
        # technical, price-action and risk confirmation.
        return min(
            cap,
            cap * (
                1
                - math.exp(
                    -value / saturation
                )
            ),
        )

    @staticmethod
    def _clamp(
        value: float,
        low: float,
        high: float,
    ) -> float:

        try:
            value = float(value)
        except (
            TypeError,
            ValueError,
        ):
            return low

        return max(
            low,
            min(
                high,
                value,
            ),
        )

    @staticmethod
    def _dedupe(
        values: Iterable[str],
    ) -> List[str]:

        result: List[str] = []
        seen = set()

        for value in values:
            text = str(
                value
            ).strip()

            if (
                text
                and text not in seen
            ):
                seen.add(text)
                result.append(text)

        return result

    @staticmethod
    def _grade(
        score: float,
    ) -> str:

        if score >= 90:
            return "A+"

        if score >= 80:
            return "A"

        if score >= 70:
            return "B"

        if score >= 60:
            return "C"

        return "D"

    # ==================================================================
    # HEALTH
    # ==================================================================

    def health(self) -> Dict[str, Any]:

        return {
            "status": "healthy",
            "engine": self.NAME,
            "priority": self.priority,
            "mandatory": self.mandatory,
            "coverage": [
                "FII",
                "DII",
                "Mutual Funds",
                "Insurance",
                "Promoter Holdings",
                "Promoter Pledge",
                "Shareholder Changes",
                "Block Deals",
                "Bulk Deals",
                "Institutional Breadth",
            ],
            "score_weights": {
                "ownership": self.MAX_OWNERSHIP,
                "holding_change": self.MAX_CHANGE,
                "deals": self.MAX_DEALS,
                "promoter": self.MAX_PROMOTER,
                "conviction": self.MAX_CONVICTION,
            },
        }