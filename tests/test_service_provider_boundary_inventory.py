from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE_DIR = ROOT / "services"
ALLOWED_DIRECT_PROVIDER_CONSUMERS = {
    "news_service.py": {"yfinance_provider", "nse_provider"},
    "corporate_action_service.py": {"nse_provider"},
}


def test_service_provider_inventory_is_explicit():
    discovered: dict[str, set[str]] = {}
    for path in SERVICE_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        names = set()
        for provider in ("yfinance_provider", "nse_provider", "kite_provider"):
            if provider in text:
                names.add(provider)
        if names:
            discovered[path.name] = names

    assert discovered == ALLOWED_DIRECT_PROVIDER_CONSUMERS


def test_provider_seams_are_isolated_to_known_legacy_services():
    assert set(ALLOWED_DIRECT_PROVIDER_CONSUMERS) == {
        "news_service.py",
        "corporate_action_service.py",
    }
