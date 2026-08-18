"""Canonical end-to-end scanner pipeline."""

from __future__ import annotations

from typing import Any


class ScanPipeline:
    """Run universe selection, scanning, ranking and dashboard generation.

    Existing callers can continue passing an explicit ``symbols`` list. When a
    universe provider is configured and symbols are omitted, the pipeline loads
    the active NIFTY 500 constituents automatically.
    """

    def __init__(self, scanner, ranking, dashboard, universe=None, top_picks=None):
        self.scanner = scanner
        self.ranking = ranking
        self.dashboard = dashboard
        self.universe = universe
        self.top_picks = top_picks

    def _resolve_symbols(self, symbols):
        if symbols is not None:
            return list(symbols)
        if self.universe is None:
            raise ValueError("symbols are required when no universe provider is configured")
        return self.universe.symbols() if self.universe.symbols() else [
            member.symbol for member in self.universe.load()
        ]

    def run(self, symbols=None, capital=0, top_n=None):
        resolved_symbols = self._resolve_symbols(symbols)
        signals = self.scanner.scan(resolved_symbols, capital)
        ranked = self.ranking.rank(signals)

        if self.top_picks is not None:
            limit = top_n if top_n is not None else 20
            picks = self.top_picks.get(ranked, limit=limit)
        else:
            picks = ranked[:top_n] if top_n is not None else ranked

        summary = self.dashboard.build(ranked)
        return {
            "ranked": ranked,
            "top_picks": picks,
            "summary": summary,
            "universe_size": len(resolved_symbols),
        }

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "universe_configured": self.universe is not None,
            "top_picks_configured": self.top_picks is not None,
        }
