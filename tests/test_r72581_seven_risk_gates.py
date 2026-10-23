"""R72.5.8.1 seven-risk safety regression gates (offline)."""
from pathlib import Path
from core.storage_config import storage_durability_diagnostics


def test_durability_is_not_inferred_from_configured_path(tmp_path):
    report = storage_durability_diagnostics({
        "TRENDFORGE_DATA_DIR": str(tmp_path),
        "DATABASE_PATH": str(tmp_path / "trendforge.db"),
    })
    assert report["database_path_configured"] is True
    assert report["durability_verified"] is False


def test_scanner_candle_completeness_and_symbol_errors():
    source = Path("services/multi_strategy_nifty_scanner.py").read_text(encoding="utf-8")
    assert "batch_candles_with_errors" in source
    assert "At least 120 completed candles are required" in source
    assert "TechnicalTradingService._completed_bars" in source
    assert "errors.append(" in source


def test_watchlist_keeps_constituents_independent_of_quotes(monkeypatch):
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    from webapp.api_client import ApiError

    class PublicClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_json(self, path, **_kwargs):
            if path.endswith("/constituents"):
                return {"rows": [{"symbol": "TCS", "stock_name": "Test company"}]}
            raise ApiError("Kite quotes unavailable")

    monkeypatch.setattr("webapp.api_client.TrendForgeApi", PublicClient)
    monkeypatch.setattr("webapp.runtime.api_url", lambda: "https://quote-failure.test")
    st.cache_data.clear()
    try:
        app = AppTest.from_file(
            Path(__file__).resolve().parents[1] / "webapp/pages/watchlists.py"
        ).run(timeout=15)
        assert not app.exception
        assert app.selectbox[0].options == ["TCS — Test company"]
        assert app.dataframe[0].value["LTP (₹)"].isna().all()
        assert any("Kite quote retrieval is unavailable" in item.value for item in app.warning)
    finally:
        st.cache_data.clear()


def test_scanner_results_separate_errors_and_empty_state():
    source = Path("webapp/pages/scanner_results.py").read_text(encoding="utf-8")
    assert "/technical/multi-strategy/results" in source
    assert "last_error" in source
    assert "errors_tab" in source


def test_scanner_run_requires_admin_auth():
    source = Path("api/app.py").read_text(encoding="utf-8")
    section = source.split('"/technical/multi-strategy/run"', 1)[1][:400]
    assert "Depends(require_admin_api_key)" in section


def test_cleanup_failure_is_explicitly_flagged_for_followup():
    source = Path("api/app.py").read_text(encoding="utf-8")
    assert "continuation_service" in source
    # Cleanup failures must be logged with the scan run ID, not suppressed.
    assert "scan_continuation_restore_failed run_id=%s" in source
    assert "_AUDIT_LOG.error(" in source
    assert "except Exception:\n                    pass" not in source
