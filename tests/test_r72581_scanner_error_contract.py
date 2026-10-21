"""R72.5.8.1 scanner diagnostics and production error boundary contracts."""
from pathlib import Path


def test_scanner_diagnostics_are_read_only_and_serializable():
    source = Path("services/multi_strategy_nifty_scanner.py").read_text(encoding="utf-8")
    section = source.split("    def diagnostics(self)", 1)[1].split("    def results(self)", 1)[0]
    assert "self._state_lock" in section
    for key in ("snapshot_available", "snapshot_storage", "persistent_state_healthy",
                "snapshot_healthy", "last_run_healthy"):
        assert key in section
    assert "batch_candles" not in section
    assert "trigger(" not in section


def test_production_scanner_read_error_boundary_is_present():
    source = Path("api/scanner_error_boundary.py").read_text(encoding="utf-8")
    assert '"/technical/multi-strategy/results"' in source
    assert '"/technical/multi-strategy/status"' in source
    assert '"/technical/multi-strategy/readiness"' in source
    assert "SCANNER_READ_UNAVAILABLE" in source
    assert "status_code=503" in source
    assert "_LOG.exception(" in source
