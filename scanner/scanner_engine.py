from dataclasses import dataclass, field
from indicators.indicator_engine import IndicatorEngine

@dataclass(slots=True)
class ScanResult:
    symbol: str
    score: float
    signal: str
    reasons: list[str] = field(default_factory=list)
    latest: dict = field(default_factory=dict)

class ScannerEngine:
    def __init__(self, fundamental_service=None, indicator_engine=None):
        self.indicators = indicator_engine or IndicatorEngine()
        self.fundamentals = fundamental_service

    def scan(self, symbol, df):
        data = self.indicators.calculate(df)
        row = data.iloc[-1]
        score = 0
        if row.get('EMA_20', 0) > row.get('EMA_50', 0): score += 20
        if row.get('EMA_50', 0) > row.get('EMA_200', 0): score += 20
        if row.get('RSI', 0) >= 55: score += 10
        if row.get('MACD', 0) > row.get('MACD_SIGNAL', 0): score += 15
        if row.get('ADX', 0) > 25: score += 10
        if row.get('RVOL', 0) >= 1.5: score += 10
        if row.get('BREAKOUT', False): score += 15
        signal = 'STRONG BUY' if score >= 80 else 'BUY' if score >= 60 else 'WATCH' if score >= 40 else 'IGNORE'
        return ScanResult(symbol, min(score, 100), signal, [], row.to_dict())

    @staticmethod
    def rank(results):
        return sorted(results, key=lambda x: x.score, reverse=True)

    def top_n(self, results, n=20):
        return self.rank(results)[:n]
