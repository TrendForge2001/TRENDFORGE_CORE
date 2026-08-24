"""Dashboard aggregation for scanner results."""
from __future__ import annotations


class DashboardService:
    """Build stable aggregate metrics from ranked scan results."""

    def build(self, signals):
        signals = list(signals or [])
        counts = {"strong_buy": 0, "buy": 0, "watchlist": 0, "hold": 0, "ignore": 0}
        scores = []
        for signal in signals:
            name = str(getattr(signal, "signal", "HOLD") or "HOLD").upper()
            if name == "STRONG BUY":
                counts["strong_buy"] += 1
            elif name == "BUY":
                counts["buy"] += 1
            elif name == "WATCHLIST":
                counts["watchlist"] += 1
            elif name == "IGNORE":
                counts["ignore"] += 1
            else:
                counts["hold"] += 1
            try:
                scores.append(float(getattr(signal, "overall_score", getattr(signal, "score", 0.0)) or 0.0))
            except (TypeError, ValueError):
                continue

        return {
            **counts,
            "total": len(signals),
            "average_score": round(sum(scores) / len(scores), 2) if scores else 0.0,
        }

    def health(self) -> dict:
        return {"status": "healthy", "aggregation": "signal_counts_and_average_score"}
