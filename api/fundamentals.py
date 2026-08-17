"""Fundamental data contracts, providers and local cache service."""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)
CACHE_EXPIRY_SECONDS = 24 * 60 * 60


@dataclass(slots=True)
class FundamentalData:
    symbol: str
    company_name: str = ""
    sector: str = ""
    industry: str = ""
    market_cap: float = 0.0
    pe: float = 0.0
    pb: float = 0.0
    peg: float = 0.0
    eps: float = 0.0
    roe: float = 0.0
    roce: float = 0.0
    debt_to_equity: float = 0.0
    current_ratio: float = 0.0
    sales_growth: float = 0.0
    profit_growth: float = 0.0
    opm: float = 0.0
    npm: float = 0.0
    dividend_yield: float = 0.0
    promoter_holding: float = 0.0
    fii_holding: float = 0.0
    dii_holding: float = 0.0
    pledged: float = 0.0
    eps_growth: float = 0.0
    earnings_today: bool = False
    dividend_today: bool = False
    bonus_issue: bool = False
    stock_split: bool = False
    last_updated: str = ""


class FundamentalProvider(ABC):
    @abstractmethod
    def get_fundamentals(self, symbol: str) -> FundamentalData:
        raise NotImplementedError


class ScreenerProvider(FundamentalProvider):
    def get_fundamentals(self, symbol: str) -> FundamentalData:
        raise NotImplementedError("Screener provider credentials/API integration are not configured.")


class TijoriProvider(FundamentalProvider):
    def get_fundamentals(self, symbol: str) -> FundamentalData:
        raise NotImplementedError("Tijori provider credentials/API integration are not configured.")


class FundamentalService:
    def __init__(self, provider: FundamentalProvider, cache_dir: str | Path = "cache") -> None:
        self.provider = provider
        self.cache: Dict[str, FundamentalData] = {}
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "fundamentals.json"
        self.load_cache()

    def get(self, symbol: str, use_cache: bool = True) -> FundamentalData:
        symbol = symbol.upper().strip()
        if use_cache and self.is_cache_valid(symbol):
            return self.cache[symbol]
        data = self.provider.get_fundamentals(symbol)
        data.last_updated = datetime.now().isoformat()
        self.cache[symbol] = data
        self.save_cache()
        return data

    def get_many(self, symbols: List[str], use_cache: bool = True) -> Dict[str, FundamentalData]:
        result: Dict[str, FundamentalData] = {}
        for symbol in symbols:
            try:
                result[symbol] = self.get(symbol, use_cache=use_cache)
            except Exception:
                logger.exception("Failed loading fundamentals for %s", symbol)
        return result

    def refresh_symbol(self, symbol: str) -> FundamentalData:
        return self.get(symbol, use_cache=False)

    def refresh(self) -> None:
        for symbol in list(self.cache):
            try:
                self.refresh_symbol(symbol)
            except Exception:
                logger.exception("Failed refreshing %s", symbol)

    def clear_cache(self) -> None:
        self.cache.clear()
        if self.cache_file.exists():
            self.cache_file.unlink()

    def is_cache_valid(self, symbol: str) -> bool:
        data = self.cache.get(symbol.upper().strip())
        if data is None or not data.last_updated:
            return False
        try:
            age = (datetime.now() - datetime.fromisoformat(data.last_updated)).total_seconds()
            return 0 <= age < CACHE_EXPIRY_SECONDS
        except (TypeError, ValueError):
            return False

    def symbols(self) -> list[str]:
        return sorted(self.cache)

    def cache_size(self) -> int:
        return len(self.cache)

    def save_cache(self) -> None:
        payload = {symbol: asdict(data) for symbol, data in self.cache.items()}
        self.cache_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load_cache(self) -> int:
        if not self.cache_file.exists():
            return 0
        try:
            raw = json.loads(self.cache_file.read_text(encoding="utf-8"))
            self.cache = {symbol: FundamentalData(**values) for symbol, values in raw.items()}
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Unable to load fundamental cache: %s", exc)
            self.cache = {}
        return len(self.cache)

    def health(self) -> dict:
        return {"status": "healthy", "provider": self.provider.__class__.__name__,
                "cache_loaded": self.cache_file.exists(), "cache_size": len(self.cache)}
