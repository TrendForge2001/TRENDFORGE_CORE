"""Opt-in, authenticated sync receiver; refuses Render ephemeral storage."""
from __future__ import annotations

import os
from pathlib import Path
import secrets
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from services.hybrid_sync_service import (
    DurableInbox, EVENT_TYPES, cloud_receiver_readiness,
)

router = APIRouter(prefix="/sync", tags=["PC Hybrid Sync"])


class SyncEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(default=1)
    event_id: str = Field(min_length=36, max_length=36)
    event_type: str = Field(min_length=1, max_length=50)
    created_at: str = Field(min_length=10, max_length=64)
    payload: dict = Field(default_factory=dict)


@router.get("/readiness")
def sync_readiness() -> dict:
    result = cloud_receiver_readiness()
    return {"status": result["status"], "durability_required": True}


@router.post("/events")
def receive_event(
    event: SyncEvent,
    x_trendforge_sync_key: str | None = Header(
        default=None, alias="X-TrendForge-Sync-Key"),
) -> dict:
    readiness = cloud_receiver_readiness()
    if readiness["status"] != "ready":
        raise HTTPException(status_code=503, detail="Durable sync receiver unavailable")
    stored_key = os.environ.get("TRENDFORGE_SYNC_SHARED_KEY", "")
    if not x_trendforge_sync_key or not secrets.compare_digest(
        stored_key, x_trendforge_sync_key
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        if str(UUID(event.event_id)) != event.event_id:
            raise ValueError("Invalid event ID")
        if event.event_type not in EVENT_TYPES:
            raise ValueError("Unsupported event type")
        storage = Path(os.environ["TRENDFORGE_SYNC_STORAGE_ROOT"]).resolve()
        inbox = DurableInbox(storage / "sync-inbox.db")
        return inbox.store(event.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except Exception:
        # Never leak database/secret internals to clients.
        raise HTTPException(status_code=503, detail="Sync persistence unavailable") from None
