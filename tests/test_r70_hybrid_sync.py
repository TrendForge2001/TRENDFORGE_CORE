"""R70.3 outbox/inbox durability, auth and no-ACK-on-failure contracts."""
from datetime import datetime, timezone
import json
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api import hybrid_sync_router as api
from services.hybrid_sync_service import (
    LocalOutbox, DurableInbox, assert_safe_payload,
    cloud_receiver_readiness, send_once, utc_now,
)


def event(event_id=None):
    return {
        "version": 1,
        "event_id": event_id or str(uuid4()),
        "event_type": "heartbeat",
        "created_at": utc_now(),
        "payload": {"component": "observer", "trading_enabled": False},
    }


def test_outbox_persists_and_acknowledges(tmp_path):
    path = tmp_path / "sync" / "outbox.db"
    first = LocalOutbox(path)
    event_id = first.enqueue("heartbeat", {"component": "observer"})
    second = LocalOutbox(path)
    assert second.status() == {"total": 1, "pending": 1}
    assert second.pending()[0]["event_id"] == event_id
    second.acknowledge(event_id)
    assert first.status() == {"total": 1, "pending": 0}


def test_secrets_are_not_queued(tmp_path):
    queue = LocalOutbox(tmp_path / "outbox.db")
    with pytest.raises(ValueError, match="restricted"):
        queue.enqueue("heartbeat", {"nested": {"kite_access_token": "secret"}})
    assert queue.status()["pending"] == 0


def test_unknown_types_and_oversized_payload_blocked(tmp_path):
    queue = LocalOutbox(tmp_path / "outbox.db")
    with pytest.raises(ValueError):
        queue.enqueue("orders", {})
    with pytest.raises(ValueError):
        queue.enqueue("heartbeat", {"extra": "x" * 20000})


def test_outbox_pending_has_small_fixed_batch_size(tmp_path):
    queue = LocalOutbox(tmp_path / "outbox.db")
    with pytest.raises(ValueError):
        queue.pending(100)


def test_durable_inbox_idempotent_and_conflicts(tmp_path):
    inbox = DurableInbox(tmp_path / "cloud.db")
    value = event()
    first = inbox.store(value)
    second = inbox.store(value)
    assert first == {"event_id": value["event_id"], "durable": True, "duplicate": False}
    assert second["duplicate"] is True
    changed = dict(value)
    changed["payload"] = {"component": "changed"}
    with pytest.raises(ValueError, match="Conflicting"):
        inbox.store(changed)


def test_receiver_disabled_by_default(tmp_path):
    assert cloud_receiver_readiness({}, mount_check=lambda _: True)["status"] == "disabled"


def test_receiver_requires_mount_and_strong_key(tmp_path):
    environment = {
        "TRENDFORGE_SYNC_RECEIVER_ENABLED": "true",
        "TRENDFORGE_SYNC_SHARED_KEY": "k" * 40,
        "TRENDFORGE_SYNC_STORAGE_ROOT": str(tmp_path),
    }
    assert cloud_receiver_readiness(environment, mount_check=lambda _: False)["status"] == "blocked"
    assert cloud_receiver_readiness(environment, mount_check=lambda _: True)["status"] == "ready"


def test_sender_disabled_by_default_and_no_ack(tmp_path):
    queue = LocalOutbox(tmp_path / "outbox.db")
    queue.enqueue("heartbeat", {"component": "observer"})
    with pytest.raises(RuntimeError):
        send_once(queue, environ={})
    assert queue.status()["pending"] == 1


def test_sender_acks_only_durable_matching_confirmation(tmp_path):
    queue = LocalOutbox(tmp_path / "outbox.db")
    event_id = queue.enqueue("heartbeat", {"component": "observer"})
    env = {
        "TRENDFORGE_SYNC_SENDER_ENABLED": "true",
        "TRENDFORGE_SYNC_URL": "https://trendforge-core.onrender.com/sync/events",
        "TRENDFORGE_SYNC_SHARED_KEY": "s" * 40,
    }
    failed = send_once(queue, transport=lambda url,key,e:(200, {"event_id": e["event_id"], "durable": False}), environ=env)
    assert failed["acknowledged"] == 0
    assert queue.status()["pending"] == 1
    success = send_once(queue, transport=lambda url,key,e:(200, {"event_id": e["event_id"], "durable": True}), environ=env)
    assert success["acknowledged"] == 1
    assert queue.status()["pending"] == 0


def test_sender_refuses_unsafe_endpoint(tmp_path):
    queue = LocalOutbox(tmp_path / "outbox.db")
    with pytest.raises(ValueError):
        send_once(queue, environ={
            "TRENDFORGE_SYNC_SENDER_ENABLED": "true",
            "TRENDFORGE_SYNC_URL": "http://example.com/sync/events",
            "TRENDFORGE_SYNC_SHARED_KEY": "s" * 40,
        })


def test_router_returns_503_with_ephemeral_storage(monkeypatch):
    monkeypatch.setattr(api, "cloud_receiver_readiness", lambda: {"status": "disabled"})
    app = FastAPI()
    app.include_router(api.router)
    response = TestClient(app).post("/sync/events", json=event())
    assert response.status_code == 503


def test_router_auth_required_when_receiver_ready(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "cloud_receiver_readiness", lambda: {"status": "ready"})
    monkeypatch.setenv("TRENDFORGE_SYNC_SHARED_KEY", "X" * 40)
    monkeypatch.setenv("TRENDFORGE_SYNC_STORAGE_ROOT", str(tmp_path))
    app = FastAPI()
    app.include_router(api.router)
    client = TestClient(app)
    value = event()
    assert client.post("/sync/events", json=value).status_code == 401
    assert client.post("/sync/events", json=value, headers={"X-TrendForge-Sync-Key": "wrong"}).status_code == 401
    result = client.post("/sync/events", json=value, headers={"X-TrendForge-Sync-Key": "X" * 40})
    assert result.status_code == 200
    assert result.json()["durable"] is True
    duplicate = client.post("/sync/events", json=value, headers={"X-TrendForge-Sync-Key": "X" * 40})
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
