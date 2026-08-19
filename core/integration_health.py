"""Integration health checks for the TrendForge core pipeline."""

from __future__ import annotations

from typing import Any

from core.data_contract import MarketDataContract
from engines.engine_orchestrator import EngineOrchestrator
from engines.data_readiness import EngineDataReadinessChecker


class IntegrationHealth:
    """Validate the core engine stack without requiring a market-data provider."""

    def __init__(self, orchestrator: EngineOrchestrator | None = None) -> None:
        self.orchestrator = orchestrator or EngineOrchestrator()
        self.readiness = EngineDataReadinessChecker()

    def check_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        symbol = str(payload.get("symbol", "")).strip()
        df = payload.get("df")
        contract = MarketDataContract.validate(df)
        readiness = self.readiness.check(payload)
        return {
            "status": "healthy" if contract.valid and readiness.ready else "not_ready",
            "symbol": symbol,
            "contract": contract.as_dict(),
            "readiness": readiness.as_dict(),
            "orchestrator": self.orchestrator.health(),
        }

    def check_empty(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "contract": {
                "required_columns": list(MarketDataContract.required),
                "validator": "available",
            },
            "readiness": "available",
            "orchestrator": self.orchestrator.health(),
        }


__all__ = ["IntegrationHealth"]
