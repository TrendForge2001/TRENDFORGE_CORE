"""Canonical end-to-end scanner pipeline."""

from __future__ import annotations

from typing import Any

from providers.market_data_adapter import MarketDataAdapter
from universe.data_validation import MarketDataValidator


class ScanPipeline:
    """Run universe selection, market data, validation, scanning, ranking and top picks."""

    def __init__(
        self,
        scanner,
        ranking,
        dashboard,
        universe=None,
        top_picks=None,
        data_validator: MarketDataValidator | None = None,
        data_loader=None,
        market_data_adapter: MarketDataAdapter | None = None,
        data_period: str = "1y",
        data_interval: str = "1d",
    ):
        self.scanner = scanner
        self.ranking = ranking
        self.dashboard = dashboard
        self.universe = universe
        self.top_picks = top_picks
        self.data_validator = data_validator
        self.market_data_adapter = market_data_adapter
        self.data_loader = data_loader
        self.data_period = data_period
        self.data_interval = data_interval

    def _resolve_symbols(self, symbols):
        if symbols is not None:
            return list(symbols)
        if self.universe is None:
            raise ValueError("symbols are required when no universe provider is configured")
        return self.universe.symbols() if self.universe.symbols() else [
            member.symbol for member in self.universe.load()
        ]

    def _load_frame(self, symbol):
        if self.data_loader is not None:
            return self.data_loader(symbol)
        if self.market_data_adapter is not None:
            return self.market_data_adapter.candles(
                symbol, period=self.data_period, interval=self.data_interval
            )
        return None

    def _validate_data(self, symbols):
        if self.data_validator is None:
            return list(symbols), [], {}

        frames = {}
        rejected = []
        for symbol in symbols:
            try:
                frame = self._load_frame(symbol)
                if frame is None:
                    rejected.append({
                        "symbol": symbol,
                        "valid": False,
                        "reasons": ["market_data_adapter_not_configured"],
                    })
                else:
                    frames[symbol] = frame
            except Exception as exc:
                rejected.append({
                    "symbol": symbol,
                    "valid": False,
                    "reasons": [f"data_loader_error:{exc}"],
                })

        valid, validation_rejected = self.data_validator.validate_many(frames)
        rejected.extend(item.as_dict() for item in validation_rejected)
        return valid, rejected, frames

    def run(self, symbols=None, capital=0, top_n=None):
        resolved_symbols = self._resolve_symbols(symbols)
        valid_symbols, rejected, frames = self._validate_data(resolved_symbols)
        signals = self.scanner.scan(valid_symbols, capital)
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
            "validated_size": len(valid_symbols),
            "rejected": rejected,
            "rejected_count": len(rejected),
            "market_data_loaded": len(frames),
        }

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "universe_configured": self.universe is not None,
            "data_validation_configured": self.data_validator is not None,
            "market_data_configured": self.market_data_adapter is not None or self.data_loader is not None,
            "top_picks_configured": self.top_picks is not None,
            "data_period": self.data_period,
            "data_interval": self.data_interval,
        }
