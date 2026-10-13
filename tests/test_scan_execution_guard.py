from __future__ import annotations

from services.scan_execution_guard import ScanExecutionGuard


def test_scan_execution_guard_is_single_flight():
    guard = ScanExecutionGuard()

    assert guard.try_start("run-a") is True
    assert guard.try_start("run-b") is False

    state = guard.status()
    assert state["status"] == "busy"
    assert state["single_flight"] is True
    assert state["active"]["run_id"] == "run-a"

    guard.finish("run-a", "completed")

    state = guard.status()
    assert state["status"] == "idle"
    assert state["active"] is None
    assert state["last_completed"]["run_id"] == "run-a"
    assert state["last_completed"]["outcome"] == "completed"

    assert guard.try_start("run-b") is True
    guard.finish("run-b", "completed")


def test_scan_execution_guard_annotation_is_scoped_to_holder():
    guard = ScanExecutionGuard()
    assert guard.try_start("run-a") is True

    guard.annotate("other", limit=500)
    assert "limit" not in guard.status()["active"]

    guard.annotate(
        "run-a",
        limit=250,
        full_universe=False,
        batch_size=25,
    )
    state = guard.status()["active"]
    assert state["limit"] == 250
    assert state["full_universe"] is False
    assert state["batch_size"] == 25

    guard.finish("run-a", "failed")
    assert guard.status()["last_completed"]["outcome"] == "failed"


def test_wrong_run_id_cannot_release_active_scan():
    guard = ScanExecutionGuard()
    assert guard.try_start("run-a") is True

    guard.finish("run-b", "completed")

    assert guard.status()["status"] == "busy"
    assert guard.try_start("run-c") is False

    guard.finish("run-a", "completed")
    assert guard.status()["status"] == "idle"
