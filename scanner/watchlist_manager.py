"""TrendForge watchlist management with canonical market-data access."""

from __future__ import annotations

import csv
import json
import logging
import threading
from typing import Any, Dict, List

from database.repositories.watchlist_repository import WatchlistRepository
from providers.market_data_adapter import MarketDataAdapter

logger = logging.getLogger(__name__)


class WatchlistManager:
    DEFAULT_WATCHLIST = "Default"

    def __init__(self, market_data: MarketDataAdapter | None = None):
        self.repo = WatchlistRepository()
        self.market_data = market_data
        self.lock = threading.Lock()
        self.watchlists: Dict[str, List[str]] = {}
        self.load()

    def load(self):
        try:
            data = self.repo.get_all_watchlists()
            self.watchlists = {}
            for row in data:
                name = row["watchlist"]
                symbol = row["symbol"].upper()
                self.watchlists.setdefault(name, [])
                if symbol not in self.watchlists[name]:
                    self.watchlists[name].append(symbol)
            logger.info("Loaded %d watchlists", len(self.watchlists))
        except Exception:
            logger.exception("Unable to load watchlists.")

    def refresh(self):
        self.load()

    def create_watchlist(self, name: str):
        if name not in self.watchlists:
            self.watchlists[name] = []
            logger.info("Created watchlist %s", name)

    def delete_watchlist(self, name: str):
        if name == self.DEFAULT_WATCHLIST:
            raise ValueError("Default watchlist cannot be deleted.")
        if name in self.watchlists:
            self.repo.delete_watchlist(name)
            del self.watchlists[name]

    def add_stock(self, symbol: str, watchlist: str = DEFAULT_WATCHLIST):
        symbol = symbol.upper()
        self.watchlists.setdefault(watchlist, [])
        if symbol in self.watchlists[watchlist]:
            return
        self.watchlists[watchlist].append(symbol)
        self.repo.add_stock(watchlist, symbol)

    def remove_stock(self, symbol: str, watchlist: str = DEFAULT_WATCHLIST):
        symbol = symbol.upper()
        if watchlist not in self.watchlists or symbol not in self.watchlists[watchlist]:
            return
        self.watchlists[watchlist].remove(symbol)
        self.repo.remove_stock(watchlist, symbol)

    def get_watchlist(self, name=DEFAULT_WATCHLIST) -> List[str]:
        return sorted(self.watchlists.get(name, []))

    def all_watchlists(self):
        return self.watchlists

    def all_symbols(self):
        symbols = set()
        for stocks in self.watchlists.values():
            symbols.update(stocks)
        return sorted(symbols)

    def quotes(self, watchlist=DEFAULT_WATCHLIST) -> dict[str, Any]:
        if self.market_data is None:
            raise RuntimeError("MarketDataAdapter is required for quote access")
        symbols = self.get_watchlist(watchlist)
        if not symbols:
            return {}
        try:
            frames = self.market_data.batch_candles(symbols, period="5d", interval="1d")
            return {
                symbol: frame.iloc[-1].to_dict()
                for symbol, frame in frames.items()
                if not frame.empty
            }
        except Exception:
            logger.exception("Unable to fetch watchlist market data.")
            return {}

    def scanner_symbols(self):
        return self.all_symbols()

    def export_csv(self, path, watchlist=DEFAULT_WATCHLIST):
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Symbol"])
            for stock in self.get_watchlist(watchlist):
                writer.writerow([stock])

    def import_csv(self, path, watchlist=DEFAULT_WATCHLIST):
        with open(path) as f:
            for row in csv.DictReader(f):
                self.add_stock(row["Symbol"], watchlist)

    def export_json(self, path):
        with open(path, "w") as f:
            json.dump(self.watchlists, f, indent=4)

    def import_json(self, path):
        with open(path) as f:
            data = json.load(f)
        for watchlist, stocks in data.items():
            for stock in stocks:
                self.add_stock(stock, watchlist)

    def exists(self, symbol, watchlist=DEFAULT_WATCHLIST):
        return symbol.upper() in self.watchlists.get(watchlist, [])

    def count(self, watchlist=DEFAULT_WATCHLIST):
        return len(self.watchlists.get(watchlist, []))

    def clear(self, watchlist=DEFAULT_WATCHLIST):
        for stock in list(self.watchlists.get(watchlist, [])):
            self.remove_stock(stock, watchlist)

    def statistics(self):
        return {
            "watchlists": len(self.watchlists),
            "total_symbols": len(self.all_symbols()),
            "details": {name: len(symbols) for name, symbols in self.watchlists.items()},
        }


# Deliberately unconfigured: callers must inject the canonical adapter.
watchlist_manager = WatchlistManager()
