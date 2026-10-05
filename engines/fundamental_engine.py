from engines.base_engine import BaseEngine, EngineResult
from engines.fundamental_contract import FundamentalInputContract
from config.fundamental_config import FUNDAMENTAL_CONFIG


class FundamentalEngine(BaseEngine):
    NAME = "Fundamental Engine"
    MAX_SCORE = 53

    def __init__(self, input_contract=None):
        self.cfg = FUNDAMENTAL_CONFIG
        self.input_contract = input_contract or FundamentalInputContract()

    def evaluate(self, stock):
        report = self.input_contract.validate(stock)
        if not report.ready:
            return EngineResult(engine=self.NAME, passed=False, score=0.0, max_score=self.MAX_SCORE,
                                confidence=0.0, grade="N/A", reasons=[],
                                warnings=["Fundamental input contract failed"],
                                metrics={"input_contract": report.as_dict()})

        stock = stock if isinstance(stock, dict) else {}
        score = 0.0
        reasons = []
        warnings = list(report.warnings)
        metrics = {"input_contract": report.as_dict()}

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

        roce = stock["roce"]
        add("roce", roce, [(30, 8), (25, 7), (20, 6), (15, 4)], "Low ROCE")
        if float(roce) >= 15: reasons.append("ROCE meets quality threshold")
        roe = stock["roe"]
        add("roe", roe, [(20, 6), (15, 5), (10, 3)], "Low ROE")
        if float(roe) >= 15: reasons.append("ROE meets quality threshold")
        add("sales_growth", stock["sales_growth"], [(25, 7), (20, 6), (15, 5), (10, 3)])
        add("profit_growth", stock["profit_growth"], [(25, 7), (20, 6), (15, 5), (10, 3)])
        add("eps_growth", stock["eps_growth"], [(25, 6), (20, 5), (15, 4), (10, 2)])

        debt = float(stock["debt_equity"])
        metrics["debt_equity"] = debt
        if debt <= 0.25: score += 8
        elif debt <= 0.5: score += 7
        elif debt <= 1: score += 5
        elif debt <= 2: score += 2
        else: warnings.append("High Debt")

        promoter = float(stock["promoter_holding"])
        metrics["promoter_holding"] = promoter
        if promoter >= 70: score += 6
        elif promoter >= 60: score += 5
        elif promoter >= 50: score += 4
        else: warnings.append("Low Promoter Holding")

        pledged = float(stock["pledged"])
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
