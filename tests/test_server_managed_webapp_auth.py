"""Server credentials authorize API calls without entering widgets or sessions."""

import importlib.util
import secrets
import sys
from pathlib import Path

from tests.test_webapp_secure_login import FakeStreamlit


def runtime(monkeypatch):
    fake = FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    spec = importlib.util.spec_from_file_location(
        "server_managed_runtime_test",
        Path(__file__).resolve().parents[1] / "webapp/runtime.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, fake


def test_configured_server_key_is_used_without_session_credentials(monkeypatch):
    private = secrets.token_urlsafe(40)
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", private)
    monkeypatch.setenv("TRENDFORGE_API_URL", "https://backend.example.test")
    module, fake = runtime(monkeypatch)
    client = module.api_client()
    assert module.admin_key_configured()
    assert client.base_url == "https://backend.example.test"
    assert client._headers()[client.ADMIN_HEADER] == private
    assert "tf_admin_key" not in fake.session_state
    assert private not in str(fake.session_state)
    assert not fake.labels


def test_legacy_browser_overrides_cannot_redirect_server_credentials(monkeypatch):
    private = secrets.token_urlsafe(40)
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", private)
    monkeypatch.setenv("TRENDFORGE_API_URL", "https://backend.example.test")
    module, fake = runtime(monkeypatch)
    fake.session_state.update(
        {
            "tf_admin_key": secrets.token_urlsafe(40),
            "tf_api_url": "https://untrusted.example.test",
            "tf_access_granted": True,
        }
    )
    client = module.api_client()
    assert client.base_url == "https://backend.example.test"
    assert client.admin_key == private
    assert "tf_admin_key" not in fake.session_state
    assert "tf_api_url" not in fake.session_state
    assert fake.session_state["tf_access_granted"] is True


def test_missing_server_key_cannot_fall_back_to_old_session_key(monkeypatch):
    monkeypatch.delenv("TRENDFORGE_ADMIN_API_KEY", raising=False)
    module, fake = runtime(monkeypatch)
    fake.session_state["tf_admin_key"] = secrets.token_urlsafe(40)
    assert not module.admin_key_configured()
    client = module.api_client()
    assert client.ADMIN_HEADER not in client._headers()


def test_rotated_server_key_is_used_by_new_requests(monkeypatch):
    first, second = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", first)
    module, fake = runtime(monkeypatch)
    assert module.api_client().admin_key == first
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", second)
    assert module.api_client().admin_key == second
    assert first not in str(fake.session_state)
    assert second not in str(fake.session_state)
