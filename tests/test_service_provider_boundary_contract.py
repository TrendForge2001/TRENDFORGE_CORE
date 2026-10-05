from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# These services are currently allowed to depend on concrete providers only
# because they are themselves provider-facing integration services. The
# canonical scanner/application boundary must remain adapter-based.
SCANNER_APPLICATION_FILES = (
    ROOT / "api" / "app.py",
    ROOT / "api" / "scanner_service.py",
    ROOT / "core" / "application_factory.py",
    ROOT / "scanner" / "full_pipeline.py",
    ROOT / "pipeline" / "scan_pipeline.py",
    ROOT / "scanner" / "watchlist_manager.py",
)
FORBIDDEN = (
    "from providers.kite_provider import",
    "from providers.nse_provider import",
    "from providers.yfinance_provider import",
    "import providers.kite_provider",
    "import providers.nse_provider",
    "import providers.yfinance_provider",
)


def test_scanner_and_application_layers_use_market_data_abstraction():
    offenders: list[str] = []
    for path in SCANNER_APPLICATION_FILES:
        text = path.read_text(encoding="utf-8")
        for marker in FORBIDDEN:
            if marker in text:
                offenders.append(f"{path.relative_to(ROOT)}: {marker}")
    assert not offenders, "Concrete provider bypass detected: " + "; ".join(offenders)


def test_watchlist_manager_accepts_injected_market_data_adapter():
    text = (ROOT / "scanner" / "watchlist_manager.py").read_text(encoding="utf-8")
    assert "MarketDataAdapter" in text
    assert "market_data: MarketDataAdapter | None" in text
    assert "batch_candles" in text


def test_news_service_bypass_is_explicitly_isolated_for_follow_up_migration():
    text = (ROOT / "services" / "news_service.py").read_text(encoding="utf-8")
    assert "yfinance_provider" in text
    assert "nse_provider" in text
    # This test documents the remaining service-level integration seam rather
    # than pretending it is already canonicalized.
    assert "class NewsService" in text
