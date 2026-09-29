from __future__ import annotations

import math
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional

from engines.base_engine import BaseEngine, EngineResult


class BlockDealEngine(BaseEngine):

    NAME = "Block Deal Engine"
    priority = 7
    mandatory = False

    def __init__(self, provider=None):
        self.provider = provider
        self._discover_provider()

    def evaluate(self, stock: Dict[str, Any]) -> EngineResult:
        payload = self._to_dict(stock)
        symbol = self._symbol(payload)
        deals = self._get_deals(symbol, payload)

        if not deals:
            return EngineResult(
                engine=self.NAME,
                passed=True,
                score=50.0,
                confidence=20.0,
                grade="D",
                warnings=["No block/bulk deal data available."],
                metrics={
                    "symbol": symbol,
                    "deal_count": 0,
                    "direction": "UNKNOWN",
                    "data_quality": "NONE",
                },
            )

        scored = [self._score_deal(d) for d in deals]
        recent = [d for d in scored if d["time_bucket"] in ("today", "recent")]

        buy_value = sum(
            d["weighted_value"] for d in scored
            if d["direction"] == "BUY"
        )
        sell_value = sum(
            d["weighted_value"] for d in scored
            if d["direction"] == "SELL"
        )

        buy_count = sum(d["direction"] == "BUY" for d in scored)
        sell_count = sum(d["direction"] == "SELL" for d in scored)

        net_value = buy_value - sell_value
        total_value = buy_value + sell_value

        if total_value > 0:
            buy_ratio = buy_value / total_value
        else:
            buy_ratio = 0.5

        score = self._score(
            net_value=net_value,
            total_value=total_value,
            recent=recent,
            buy_count=buy_count,
            sell_count=sell_count,
        )

        direction = self._direction(
            net_value,
            buy_count,
            sell_count,
        )

        quality = self._quality(scored)
        confidence = self._confidence(
            scored,
            quality,
            total_value,
        )

        reasons = self._reasons(
            scored,
            direction,
            buy_ratio,
        )
        warnings = self._warnings(
            scored,
            direction,
        )

        return EngineResult(
            engine=self.NAME,
            passed=not (
                direction == "STRONG_SELL"
                and score < 35
            ),
            score=round(score, 2),
            confidence=round(confidence, 2),
            grade=self._grade(score),
            reasons=reasons[:20],
            warnings=warnings[:20],
            metrics={
                "symbol": symbol,
                "deal_count": len(scored),
                "recent_deal_count": len(recent),
                "buy_count": buy_count,
                "sell_count": sell_count,
                "buy_value": round(buy_value, 2),
                "sell_value": round(sell_value, 2),
                "net_value": round(net_value, 2),
                "buy_value_ratio": round(buy_ratio, 4),
                "direction": direction,
                "data_quality": quality,
                "deals": scored[:50],
            },
        )

    def _discover_provider(self):
        # Provider acquisition belongs to the application composition root.
        return

    def _get_deals(
        self,
        symbol: str,
        payload: Dict[str, Any],
    ) -> List[Dict[str, Any]]:

        raw = []

        for key in (
            "block_deals",
            "bulk_deals",
            "block_bulk_deals",
            "deals",
        ):
            value = payload.get(key)
            if value:
                raw.extend(self._rows(value))

        if self.provider is not None:
            for method_name in (
                "get_block_deals",
                "get_bulk_deals",
                "get_block_bulk_deals",
                "get_bulk_block_deals",
                "fetch_block_deals",
                "fetch_bulk_deals",
            ):
                method = getattr(
                    self.provider,
                    method_name,
                    None,
                )
                if not callable(method):
                    continue

                try:
                    value = method(symbol)
                    if value:
                        raw.extend(self._rows(value))
                        break
                except Exception:
                    continue

        result = []
        seen = set()

        for row in raw:
            deal = self._normalize_deal(row)

            if not deal["symbol"]:
                deal["symbol"] = symbol

            if (
                deal["symbol"]
                and symbol
                and deal["symbol"] != symbol
            ):
                continue

            fingerprint = self._fingerprint(deal)

            if fingerprint in seen:
                continue

            seen.add(fingerprint)
            result.append(deal)

        return result

    def _normalize_deal(
        self,
        row: Mapping[str, Any],
    ) -> Dict[str, Any]:

        symbol = str(
            row.get("symbol")
            or row.get("ticker")
            or row.get("security")
            or row.get("scrip")
            or row.get("stock")
            or ""
        ).strip().upper()

        client = str(
            row.get("client_name")
            or row.get("client")
            or row.get("clientName")
            or row.get("name")
            or ""
        ).strip()

        deal_type = str(
            row.get("deal_type")
            or row.get("type")
            or row.get("category")
            or ""
        ).strip().upper()

        action = str(
            row.get("action")
            or row.get("side")
            or row.get("transaction_type")
            or row.get("buy_sell")
            or ""
        ).strip().upper()

        quantity = self._number(
            row.get("quantity")
            or row.get("qty")
            or row.get("shares")
            or row.get("volume")
        )

        price = self._number(
            row.get("price")
            or row.get("trade_price")
            or row.get("avg_price")
        )

        value = self._number(
            row.get("value")
            or row.get("deal_value")
            or row.get("transaction_value")
        )

        if value is None and quantity and price:
            value = quantity * price

        event_date = self._parse_date(
            row.get("date")
            or row.get("trade_date")
            or row.get("deal_date")
            or row.get("timestamp")
        )

        direction = self._direction_from_row(
            action,
            row,
        )

        return {
            "symbol": symbol,
            "client": client,
            "deal_type": deal_type,
            "action": action,
            "direction": direction,
            "quantity": quantity,
            "price": price,
            "value": value,
            "date": event_date,
            "raw": dict(row),
        }

    def _score_deal(
        self,
        deal: Dict[str, Any],
    ) -> Dict[str, Any]:

        direction = deal["direction"]
        value = deal["value"] or 0.0

        time_bucket, time_factor = self._time_factor(
            deal["date"]
        )

        size_factor = self._size_factor(value)

        weighted_value = (
            value
            * time_factor
            * size_factor
        )

        if direction == "BUY":
            signed_score = self._deal_score(
                value,
                time_factor,
                size_factor,
            )
        elif direction == "SELL":
            signed_score = -self._deal_score(
                value,
                time_factor,
                size_factor,
            )
        else:
            signed_score = 0.0

        return {
            "symbol": deal["symbol"],
            "client": deal["client"][:200],
            "deal_type": deal["deal_type"],
            "action": deal["action"],
            "direction": direction,
            "quantity": deal["quantity"],
            "price": deal["price"],
            "value": round(value, 2),
            "date": self._iso(deal["date"]),
            "time_bucket": time_bucket,
            "time_factor": round(time_factor, 3),
            "size_factor": round(size_factor, 3),
            "weighted_value": round(
                weighted_value,
                2,
            ),
            "signed_score": round(
                signed_score,
                2,
            ),
        }

    def _score(
        self,
        net_value: float,
        total_value: float,
        recent: List[Dict[str, Any]],
        buy_count: int,
        sell_count: int,
    ) -> float:

        if total_value <= 0:
            return 50.0

        imbalance = net_value / total_value

        score = 50.0 + imbalance * 40.0

        recent_net = sum(
            d["signed_score"]
            for d in recent
        )

        score += self._clamp(
            recent_net * 0.5,
            -10,
            10,
        )

        if buy_count >= 2 and buy_count > sell_count:
            score += 5

        if sell_count >= 2 and sell_count > buy_count:
            score -= 5

        return self._clamp(
            score,
            0,
            100,
        )

    def _direction(
        self,
        net_value: float,
        buy_count: int,
        sell_count: int,
    ) -> str:

        if net_value == 0:
            return "NEUTRAL"

        if net_value > 0:
            if buy_count >= sell_count + 2:
                return "STRONG_BUY"
            return "BUY"

        if sell_count >= buy_count + 2:
            return "STRONG_SELL"

        return "SELL"

    def _deal_score(
        self,
        value: float,
        time_factor: float,
        size_factor: float,
    ) -> float:

        if value <= 0:
            return 0.0

        base = math.log10(
            max(value, 1.0)
        )

        return self._clamp(
            base
            * 3.0
            * time_factor
            * size_factor,
            0,
            20,
        )

    def _size_factor(
        self,
        value: float,
    ) -> float:

        if value >= 1000:
            return 1.50
        if value >= 500:
            return 1.35
        if value >= 100:
            return 1.20
        if value >= 25:
            return 1.05
        return 0.80

    def _time_factor(
        self,
        event_date: Optional[date],
    ):

        if event_date is None:
            return "unknown", 0.60

        delta = (
            date.today() - event_date
        ).days

        if delta <= 0:
            return "today", 1.50
        if delta <= 2:
            return "recent", 1.35
        if delta <= 5:
            return "recent", 1.20
        if delta <= 15:
            return "recent", 0.90
        if delta <= 30:
            return "older", 0.65

        return "historical", 0.35

    def _quality(
        self,
        deals: List[Dict[str, Any]],
    ) -> str:

        if not deals:
            return "NONE"

        dated = sum(
            d["date"] is not None
            for d in deals
        )

        valued = sum(
            (d["value"] or 0) > 0
            for d in deals
        )

        directional = sum(
            d["direction"] != "UNKNOWN"
            for d in deals
        )

        ratio = (
            dated
            + valued
            + directional
        ) / (3 * len(deals))

        if ratio >= 0.85:
            return "HIGH"
        if ratio >= 0.60:
            return "MEDIUM"
        return "LOW"

    def _confidence(
        self,
        deals: List[Dict[str, Any]],
        quality: str,
        total_value: float,
    ) -> float:

        base = {
            "HIGH": 75.0,
            "MEDIUM": 58.0,
            "LOW": 38.0,
            "NONE": 15.0,
        }.get(
            quality,
            20.0,
        )

        base += min(
            len(deals) * 2,
            12,
        )

        if total_value >= 500:
            base += 8
        elif total_value >= 100:
            base += 5

        return self._clamp(
            base,
            0,
            100,
        )

    def _reasons(
        self,
        deals: List[Dict[str, Any]],
        direction: str,
        buy_ratio: float,
    ) -> List[str]:

        reasons = []

        if direction == "STRONG_BUY":
            reasons.append(
                "Strong net buying in block/bulk deals."
            )
        elif direction == "BUY":
            reasons.append(
                "Net buying detected in block/bulk deals."
            )
        elif direction == "STRONG_SELL":
            reasons.append(
                "Strong net selling in block/bulk deals."
            )
        elif direction == "SELL":
            reasons.append(
                "Net selling detected in block/bulk deals."
            )

        if buy_ratio >= 0.70:
            reasons.append(
                "Buying accounts for most deal value."
            )

        elif buy_ratio <= 0.30:
            reasons.append(
                "Selling accounts for most deal value."
            )

        for deal in sorted(
            deals,
            key=lambda x: abs(x["signed_score"]),
            reverse=True,
        )[:5]:

            if deal["direction"] == "BUY":
                reasons.append(
                    f"Large buyer transaction: "
                    f"{deal['client'] or 'disclosed participant'}"
                )

            elif deal["direction"] == "SELL":
                reasons.append(
                    f"Large seller transaction: "
                    f"{deal['client'] or 'disclosed participant'}"
                )

        return self._dedupe(reasons)

    def _warnings(
        self,
        deals: List[Dict[str, Any]],
        direction: str,
    ) -> List[str]:

        warnings = []

        if direction in (
            "SELL",
            "STRONG_SELL",
        ):
            warnings.append(
                "Block/bulk deal flow is negative."
            )

        unknown = sum(
            d["direction"] == "UNKNOWN"
            for d in deals
        )

        if unknown:
            warnings.append(
                f"{unknown} deal(s) have unknown transaction direction."
            )

        if any(
            d["time_bucket"] == "unknown"
            for d in deals
        ):
            warnings.append(
                "Some deal dates are unavailable."
            )

        return warnings

    @staticmethod
    def _direction_from_row(
        action: str,
        row: Mapping[str, Any],
    ) -> str:

        text = (
            action
            + " "
            + str(
                row.get("buy_sell")
                or row.get("transaction_type")
                or ""
            )
        ).upper()

        if any(
            token in text
            for token in (
                "BUY",
                "PURCHASE",
                "ACQUISITION",
                "BOUGHT",
            )
        ):
            return "BUY"

        if any(
            token in text
            for token in (
                "SELL",
                "SALE",
                "SOLD",
                "DISPOSAL",
            )
        ):
            return "SELL"

        return "UNKNOWN"

    @staticmethod
    def _rows(
        value: Any,
    ) -> List[Dict[str, Any]]:

        if isinstance(value, Mapping):
            for key in (
                "data",
                "results",
                "items",
                "rows",
                "deals",
            ):
                nested = value.get(key)
                if isinstance(
                    nested,
                    (list, tuple),
                ):
                    return [
                        BlockDealEngine._to_dict(x)
                        for x in nested
                    ]

            return [dict(value)]

        if isinstance(
            value,
            (list, tuple, set),
        ):
            return [
                BlockDealEngine._to_dict(x)
                for x in value
            ]

        return []

    @staticmethod
    def _to_dict(
        value: Any,
    ) -> Dict[str, Any]:

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

    @staticmethod
    def _symbol(
        payload: Mapping[str, Any],
    ) -> str:

        return str(
            payload.get("symbol")
            or payload.get("ticker")
            or payload.get("tradingsymbol")
            or ""
        ).strip().upper()

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
                    .replace("₹", "")
                    .replace("%", "")
                    .strip()
                )

            result = float(value)

            if math.isfinite(result):
                return result

        except (
            TypeError,
            ValueError,
        ):
            pass

        return None

    @staticmethod
    def _parse_date(
        value: Any,
    ) -> Optional[date]:

        if value is None or value == "":
            return None

        if isinstance(value, datetime):
            return value.date()

        if isinstance(value, date):
            return value

        text = str(value).strip()

        for fmt in (
            "%Y-%m-%d",
            "%d-%m-%Y",
            "%d/%m/%Y",
            "%Y/%m/%d",
            "%d %b %Y",
            "%d %B %Y",
            "%b %d, %Y",
            "%B %d, %Y",
        ):
            try:
                return datetime.strptime(
                    text,
                    fmt,
                ).date()
            except ValueError:
                continue

        try:
            return datetime.fromisoformat(
                text.replace(
                    "Z",
                    "+00:00",
                )
            ).date()
        except Exception:
            return None

    @staticmethod
    def _iso(
        value: Any,
    ) -> Optional[str]:

        if value is None:
            return None

        try:
            return value.isoformat()
        except Exception:
            return str(value)

    @staticmethod
    def _fingerprint(
        deal: Mapping[str, Any],
    ) -> str:

        return "|".join(
            str(
                deal.get(key)
                or ""
            ).lower()
            for key in (
                "symbol",
                "client",
                "action",
                "quantity",
                "price",
                "value",
                "date",
            )
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
            min(high, value),
        )

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
        if score >= 45:
            return "D"
        return "F"

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

    def health(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "engine": self.NAME,
            "priority": self.priority,
            "mandatory": self.mandatory,
            "coverage": [
                "block deals",
                "bulk deals",
                "buy/sell direction",
                "deal value",
                "recency",
                "net institutional activity",
            ],
        }


def get_block_deal_engine(
    provider=None,
) -> BlockDealEngine:
    return BlockDealEngine(
        provider=provider
    )


__all__ = [
    "BlockDealEngine",
    "get_block_deal_engine",
]
