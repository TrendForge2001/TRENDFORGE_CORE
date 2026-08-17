from engines.base_engine import BaseEngine, EngineResult
from config.signal_weights import SIGNAL_WEIGHTS
from models.signal_weights import Signal


class SignalEngine(BaseEngine):
    NAME = "Signal Engine"
    priority = 100
    mandatory = True

    def generate(self, symbol, market, sector, fundamental, corporate, shark, technical, price_action, risk):
        engines = (market, sector, fundamental, corporate, shark, technical, price_action, risk)
        keys = ("market", "sector", "fundamental", "corporate", "big_shark", "technical", "price_action", "risk")
        score = sum(float(getattr(e, "score", 0)) * SIGNAL_WEIGHTS[k] for e, k in zip(engines, keys))
        confidence = sum(float(getattr(e, "confidence", 0)) for e in engines) / len(engines)
        return Signal(symbol, self._classify(score), round(confidence, 2), round(score, 2),
                      float(getattr(price_action, "entry", 0)), float(getattr(risk, "stoploss", 0)),
                      float(getattr(risk, "target1", 0)), float(getattr(risk, "target2", 0)),
                      float(getattr(risk, "target3", 0)), float(getattr(risk, "rr", 0)),
                      self._reasons(*engines), list(getattr(risk, "warnings", [])))

    def evaluate(self, stock):
        return EngineResult(self.NAME, False, 0.0, 0.0, "D", warnings=["SignalEngine.generate requires component engine results."])

    @staticmethod
    def _classify(score):
        if score >= 95: return "STRONG BUY"
        if score >= 90: return "BUY"
        if score >= 85: return "ACCUMULATE"
        if score >= 75: return "WATCHLIST"
        if score >= 60: return "HOLD"
        if score >= 40: return "REDUCE"
        return "SELL"

    @staticmethod
    def _reasons(*engines):
        return list(dict.fromkeys(r for e in engines for r in getattr(e, "reasons", [])))[:10]
