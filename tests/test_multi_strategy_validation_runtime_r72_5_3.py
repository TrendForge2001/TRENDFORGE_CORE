from __future__ import annotations

import threading

from fastapi import FastAPI

from services.multi_strategy_validation_runtime import status


def test_r7253_runtime_status_excludes_private_thread_object():
    app = FastAPI()
    app.state.r7253_validation = {
        "status": "running",
        "run_id": "r7253-test",
        "_thread": threading.Thread(),
        "progress": {"phase": "backtest", "progress_pct": 10.0},
    }

    payload = status(app)

    assert "_thread" not in payload
    assert payload["worker_alive"] is False
    assert payload["status"] == "running"
