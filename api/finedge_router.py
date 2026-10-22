"""Authenticated FinEdge fundamental-data reads owned by the backend."""
from __future__ import annotations

from typing import Any, Callable
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.admin_auth import require_admin_api_key
from providers.finedge_api_provider import FinEdgeAPIProvider, FinEdgeError


class FinEdgeFetchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=40)
    statement_type: str = Field(default="c", pattern="^(c|s)$")
    force_refresh: bool = False

    @field_validator("symbol")
    @classmethod
    def normalized_symbol(cls, value: str) -> str:
        return FinEdgeAPIProvider._symbol(value)


def attach_finedge_routes(app: FastAPI, *, service_getter: Callable[[], Any]) -> None:
    def service():
        try:
            result = service_getter()
        except Exception:
            raise HTTPException(503, "FinEdge configuration unavailable") from None
        if result is None:
            raise HTTPException(503, "FinEdge fundamental service unavailable")
        return result

    @app.get("/fundamentals/finedge/readiness", dependencies=[Depends(require_admin_api_key)])
    def readiness():
        return service().health()

    @app.post("/fundamentals/finedge/fetch", dependencies=[Depends(require_admin_api_key)])
    def fetch(request: FinEdgeFetchRequest):
        try:
            return service().fetch(**request.model_dump())
        except FinEdgeError as exc:
            code = 429 if exc.status_code == 429 else 503 if exc.status_code is None else 502
            raise HTTPException(code, str(exc)) from None
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "FinEdge fundamental data unavailable") from None
