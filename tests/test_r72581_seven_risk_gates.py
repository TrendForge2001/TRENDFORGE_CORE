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


def test_scanner_candle_completeness_and_symbol_errors(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from services.multi_strategy_nifty_scanner import MultiStrategyNiftyScanner
    from tests.test_multi_strategy_scanner_r72_5_2 import FakeUniverse, _daily_frame

    monkeypatch.setenv("TRENDFORGE_MULTI_STRATEGY_RESULTS_PATH", str(tmp_path / "scan.json"))
    market = SimpleNamespace(batch_candles_with_errors=lambda *a, **k: (
        {"S000": _daily_frame(rows=119), "S001": _daily_frame()},
        {"S002": "No historical candles"},
    ))
    result = MultiStrategyNiftyScanner(
        market_data=market, universe_provider=FakeUniverse(),
    ).scan(universe="NIFTY 500", mode="swing", source="user_notebook", limit=3)
    assert result["status"] == "degraded"
    assert result["completed_symbols"] == 1 and result["error_symbols"] == 2
    assert [row["symbol"] for row in result["results"]] == ["S001"]
    errors = {row["symbol"]: row["error"] for row in result["errors"]}
    assert "120 completed candles" in errors["S000"]
    assert errors["S002"] == "No historical candles"
    assert result["safety"]["paper_orders_created"] is False


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
        assert not app.selectbox
        assert app.dataframe[0].value["Symbol"].tolist() == ["TCS"]
        assert app.dataframe[0].value["Company"].tolist() == ["Test company"]
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
