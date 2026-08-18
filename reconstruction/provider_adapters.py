"""Adapters from confirmed TrendForge services/providers to enrichment slots."""

from __future__ import annotations
from typing import Any


class ServiceAdapter:
    """Small callable adapter that preserves the provider/service boundary."""

    def __init__(self, service: Any, method: str, *, name: str | None = None):
        self.service = service
        self.method = method
        self.name = name or service.__class__.__name__

    def __call__(self, symbol: str, payload: dict[str, Any] | None = None) -> Any:
        fn = getattr(self.service, self.method)
        try:
            return fn(symbol)
        except TypeError:
            return fn(symbol, payload or {})


class FundamentalServiceAdapter(ServiceAdapter):
    def __init__(self, service: Any):
        super().__init__(service, "load", name="FundamentalService")


class CorporateActionServiceAdapter(ServiceAdapter):
    def __init__(self, service: Any):
        super().__init__(service, "get_actions", name="CorporateActionService")


class SectorServiceAdapter(ServiceAdapter):
    def __init__(self, service: Any):
        super().__init__(service, "get", name="SectorService")


def build_confirmed_adapters(*, fundamental_service=None, corporate_action_service=None,
                             sector_service=None) -> dict[str, Any]:
    """Return only adapters backed by explicitly supplied services.

    No provider is instantiated implicitly and no missing dataset is fabricated.
    """
    adapters: dict[str, Any] = {}
    if fundamental_service is not None:
        adapters["fundamentals"] = FundamentalServiceAdapter(fundamental_service)
    if corporate_action_service is not None:
        adapters["corporate_actions"] = CorporateActionServiceAdapter(corporate_action_service)
    if sector_service is not None:
        adapters["sector"] = SectorServiceAdapter(sector_service)
    return adapters


__all__ = [
    "ServiceAdapter", "FundamentalServiceAdapter", "CorporateActionServiceAdapter",
    "SectorServiceAdapter", "build_confirmed_adapters",
]
