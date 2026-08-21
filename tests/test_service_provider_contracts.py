from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_news_service_has_an_explicit_provider_boundary():
    text = _read("services/news_service.py")
    assert "class NewsService" in text
    assert "yfinance_provider" in text or "YFinance" in text
    assert "nse_provider" in text or "NSE" in text


def test_corporate_action_service_has_an_explicit_provider_boundary():
    text = _read("services/corporate_action_service.py")
    assert "CorporateActionService" in text
    assert "nse_provider" in text or "NSE" in text


def test_service_specific_data_contracts_are_not_forced_into_market_data_adapter():
    adapter = _read("providers/market_data_adapter.py")
    assert "class MarketDataAdapter" in adapter
    # News and corporate actions are intentionally separate domain contracts
    # until their provider interfaces are designed and migrated.
    assert "candles" in adapter
