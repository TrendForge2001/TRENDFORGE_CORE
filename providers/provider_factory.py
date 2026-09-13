"""Deterministic provider selection for TrendForge."""

from __future__ import annotations


class ProviderFactory:
    def __init__(self, kite=None, yahoo=None, nse=None):
        self.kite = kite
        self.yahoo = yahoo
        self.nse = nse

    @staticmethod
    def _usable(provider):
        return provider is not None

    def market_data(self):
        if self._usable(self.kite):
            return self.kite
        if self._usable(self.yahoo):
            return self.yahoo
        raise RuntimeError("No market-data provider is configured")

    def quote(self):
        if self._usable(self.kite):
            return self.kite
        if self._usable(self.nse):
            return self.nse
        if self._usable(self.yahoo):
            return self.yahoo
        raise RuntimeError("No quote provider is configured")

    def health(self):
        return {
            "kite_configured": self._usable(self.kite),
            "yahoo_configured": self._usable(self.yahoo),
            "nse_configured": self._usable(self.nse),
        }
