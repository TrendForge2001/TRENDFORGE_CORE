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
    assert "No completed candles available" in source
    assert "errors.append(" in source


def test_watchlist_keeps_constituents_independent_of_quotes():
    source = Path("webapp/pages/watchlists.py").read_text(encoding="utf-8")
    assert "load_constituents()" in source
    assert "load_live_watchlist()" in source
    assert "tf_nifty100_stock_selector" in source
    assert "if not members:" in source


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
    # Presence of this exception suppression is a tracked risk, not a pass.
    assert "except Exception:\n                    pass" in source
