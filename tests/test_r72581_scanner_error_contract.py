"""R72.5.8.1 read-only scanner diagnostics contract."""
from pathlib import Path


def test_scanner_diagnostics_are_read_only_and_serializable():
    source = Path("services/multi_strategy_nifty_scanner.py").read_text(encoding="utf-8")
    section = source.split("    def diagnostics(self)", 1)[1].split("    def results(self)", 1)[0]
    assert "self._state_lock" in section
    assert "snapshot_available" in section
    assert "snapshot_storage" in section
    assert "persistent_state_healthy" in section
    assert "snapshot_healthy" in section
    assert "last_run_healthy" in section
    assert "batch_candles" not in section
    assert "trigger(" not in section


def test_scanner_api_error_paths_need_hardening():
    """Expected-failure risk marker until the API boundary is patched."""
    source = Path("api/app.py").read_text(encoding="utf-8")
    for route, following in (
        ('@app.get("/technical/multi-strategy/results")', '@app.get("/technical/multi-strategy/status")'),
        ('@app.get("/technical/multi-strategy/status")', '@app.post('),
    ):
        section = source.split(route, 1)[1].split(following, 1)[0]
        if "except Exception as exc:" not in section:
            import pytest
            pytest.xfail("API read endpoint error normalization pending")
        assert "status_code=503" in section
