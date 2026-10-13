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


def test_scan_execution_guard_reports_remaining_budget(monkeypatch):
    import services.scan_execution_guard as guard_module

    clock = [100.0]
    monkeypatch.setattr(
        guard_module.time,
        "monotonic",
        lambda: clock[0],
    )

    guard = ScanExecutionGuard()
    assert guard.try_start("budgeted-run") is True
    guard.annotate(
        "budgeted-run",
        scan_time_budget_seconds=450.0,
        deadline_at="2026-10-13T18:00:00+00:00",
        deadline_monotonic=550.0,
    )

    clock[0] = 125.0
    state = guard.status()

    assert state["status"] == "busy"
    assert state["active"]["run_id"] == "budgeted-run"
    assert state["active"]["elapsed_sec"] == 25.0
    assert state["active"]["remaining_budget_sec"] == 425.0
    assert "deadline_monotonic" not in state["active"]

    guard.finish("budgeted-run", "partial")
    assert guard.status()["last_completed"]["outcome"] == "partial"
