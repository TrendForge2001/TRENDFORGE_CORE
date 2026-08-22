from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_application_factory_is_the_canonical_domain_service_composition_owner():
    text = _text("core/application_factory.py")
    assert "def news_service" in text
    assert "def corporate_action_service" in text
    assert "self.news_provider()" in text
    assert "self.corporate_action_provider()" in text


def test_domain_services_accept_injected_providers():
    news = _text("services/news_service.py")
    corporate = _text("services/corporate_action_service.py")
    assert "provider: NewsProvider | None = None" in news
    assert "provider: CorporateActionProvider | None = None" in corporate


def test_domain_service_singletons_are_not_used_by_application_factory():
    text = _text("core/application_factory.py")
    assert "news_service = NewsService()" not in text
    assert "corporate_action_service = CorporateActionService()" not in text
