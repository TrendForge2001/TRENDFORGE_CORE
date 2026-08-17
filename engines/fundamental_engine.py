from engines.base_engine import BaseEngine, EngineResult
from config.fundamental_config import FUNDAMENTAL_CONFIG


class FundamentalEngine(BaseEngine):
    NAME = "Fundamental Engine"
    MAX_SCORE = 53

    def __init__(self):
        self.cfg = FUNDAMENTAL_CONFIG

    def evaluate(self, stock):
        stock = stock if isinstance(stock, dict) else {}
        score = 0.0
        reasons = []
        warnings = []
        metrics = {}

        def add(name, value, tiers, warning=None):
            nonlocal score
            value = float(value or 0)
            metrics[name] = value
            for threshold, points in tiers:
                if value >= threshold:
                    score += points
                    return
            if warning:
                warnings.append(warning)

        roce = stock.get("roce", 0)
        add("roce", roce, [(30, 8), (25, 7), (20, 6), (15, 4)], "Low ROCE")
        if float(roce or 0) >= 15: reasons.append("ROCE meets quality threshold")

        roe = stock.get("roe", 0)
        add("roe", roe, [(20, 6), (15, 5), (10, 3)], "Low ROE")
        if float(roe or 0) >= 15: reasons.append("ROE meets quality threshold")

        sales = stock.get("sales_growth", 0)
        add("sales_growth", sales, [(25, 7), (20, 6), (15, 5), (10, 3)])
        profit = stock.get("profit_growth", 0)
        add("profit_growth", profit, [(25, 7), (20, 6), (15, 5), (10, 3)])
        eps = stock.get("eps_growth", 0)
        add("eps_growth", eps, [(25, 6), (20, 5), (15, 4), (10, 2)])

        debt = float(stock.get("debt_equity", stock.get("debt_to_equity", 999)) or 999)
        metrics["debt_equity"] = debt
        if debt <= 0.25: score += 8
        elif debt <= 0.5: score += 7
        elif debt <= 1: score += 5
        elif debt <= 2: score += 2
        else: warnings.append("High Debt")

        promoter = float(stock.get("promoter_holding", 0) or 0)
        metrics["promoter_holding"] = promoter
        if promoter >= 70: score += 6
        elif promoter >= 60: score += 5
        elif promoter >= 50: score += 4
        else: warnings.append("Low Promoter Holding")

        pledged = float(stock.get("pledged", 100) or 0)
        metrics["pledged"] = pledged
        if pledged == 0: score += 5
        elif pledged <= 5: score += 4
        elif pledged <= 10: score += 2
        else: warnings.append("Promoter Shares Pledged")

        score = min(float(self.MAX_SCORE), score)
        confidence = round(score / self.MAX_SCORE * 100, 2)
        passed = score >= self.cfg["minimum_score"]
        grade = "A+" if confidence >= 90 else "A" if confidence >= 80 else "B" if confidence >= 70 else "C" if confidence >= 60 else "D"
        return EngineResult(engine=self.NAME, passed=passed, score=score, max_score=self.MAX_SCORE,
                            confidence=confidence, grade=grade, reasons=reasons,
                            warnings=warnings, metrics=metrics)
