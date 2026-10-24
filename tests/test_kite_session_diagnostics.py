"""Credentials must load on Windows and failures must be truthful and private."""

import json
import secrets
import threading
from types import SimpleNamespace

import pytest
import requests

from core.pc_kite_credentials import FIELDS, load_pc_kite_credentials
from providers.kite_diagnostics import MESSAGES, safe_session_failure, session_failure
from providers.kite_errors import (
    DataException,
    GeneralException,
    NetworkException,
    PermissionException,
    TokenException,
)
from providers.kite_provider import KiteProvider
from providers.kite_rest_client import KiteRESTClient
from scripts.check_kite_session import diagnose


@pytest.fixture(autouse=True)
def no_real_requests(monkeypatch):
    monkeypatch.setattr(
        requests.sessions.Session,
        "request",
        lambda *a, **k: pytest.fail("External request forbidden"),
    )
    for name in FIELDS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("scripts.check_kite_session.dotenv_values", lambda *a, **k: {})


def private_file(root, values, *, encoding="utf-8"):
    private = root / "private"
    private.mkdir(exist_ok=True)
    path = private / "kite.env"
    path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()), encoding=encoding
    )
    return path


def test_windows_bom_whitespace_and_literal_dollar_tokens_are_preserved(tmp_path):
    token = secrets.token_hex(16) + "${LITERAL}"
    key = secrets.token_hex(8)
    private_file(
        tmp_path,
        {"KITE_API_KEY": f"  {key}  ", "KITE_ACCESS_TOKEN": token},
        encoding="utf-8-sig",
    )
    assert load_pc_kite_credentials(tmp_path) == {
        "KITE_API_KEY": key,
        "KITE_ACCESS_TOKEN": token,
    }


def test_diagnostic_detects_notepad_txt_extension_without_reading_its_values(tmp_path):
    private = tmp_path / "private"
    private.mkdir()
    (private / "kite.env.txt").write_text("KITE_API_KEY=" + secrets.token_hex(12))
    result = diagnose(tmp_path)
    assert result["credential_file_found"] is False
    assert result["possible_txt_extension"] is True
    assert result["status"] == "configuration_required"
    assert result["diagnostic"]["code"] == "api_key_missing"


@pytest.mark.parametrize(
    "error,code,http",
    [
        (TokenException("private"), "token_rejected", 403),
        (PermissionException("private"), "permission_denied", 403),
        (NetworkException("private"), "transport_unavailable", None),
        (NetworkException("private", reason="tls_failure"), "tls_failure", None),
        (GeneralException("private", 429), "rate_limited", 429),
        (GeneralException("private", 503), "upstream_unavailable", 503),
        (DataException("private", 200), "invalid_response", None),
        (ValueError("private"), "probe_failed", None),
    ],
)
def test_safe_failure_categories_never_copy_exception_text(error, code, http):
    assert session_failure(error) == {
        "code": code,
        "message": MESSAGES[code],
        "http_status": http,
    }
    assert "private" not in json.dumps(session_failure(error))


@pytest.mark.parametrize(
    "error,code",
    [
        (requests.exceptions.SSLError, "tls_failure"),
        (requests.exceptions.ProxyError, "proxy_failure"),
        (requests.exceptions.Timeout, "request_timeout"),
        (requests.exceptions.ConnectionError, "connection_failed"),
    ],
)
def test_transport_reports_safe_cause_instead_of_blaming_the_token(error, code):
    sentinel = secrets.token_hex(20)

    def fail(*args, **kwargs):
        raise error(sentinel)

    client = KiteRESTClient(
        api_key=secrets.token_hex(8),
        access_token=secrets.token_hex(12),
        session=SimpleNamespace(request=fail),
    )
    with pytest.raises(NetworkException) as caught:
        client.profile()
    failure = session_failure(caught.value)
    assert failure["code"] == code
    assert sentinel not in json.dumps(failure) + str(caught.value)


def test_unknown_diagnostic_values_are_not_forwarded():
    sentinel = secrets.token_hex(20)
    diagnostic = safe_session_failure(
        {
            "auth_error_code": sentinel,
            "auth_error": sentinel,
            "auth_http_status": sentinel,
        }
    )
    assert diagnostic["code"] == "probe_failed"
    assert sentinel not in json.dumps(diagnostic)


def test_cli_checks_profile_and_quotes_without_printing_account_or_credentials(
    tmp_path,
):
    key, token, account = (secrets.token_hex(16) for _ in range(3))
    private_file(
        tmp_path,
        {"KITE_API_KEY": key, "KITE_ACCESS_TOKEN": token},
        encoding="utf-8-sig",
    )
    calls = []

    def factory(**kwargs):
        assert kwargs == {"api_key": key, "access_token": token}
        return SimpleNamespace(
            profile=lambda: calls.append("profile") or {"user_id": account},
            quote=lambda _: (
                calls.append("quote") or {"NSE:RELIANCE": {"last_price": 100}}
            ),
        )

    result = diagnose(tmp_path, client_factory=factory)
    assert result["status"] == "ready" and result["profile_authenticated"] is True
    assert result["credentials_loaded"]["KITE_API_SECRET"] is False
    assert calls == ["profile", "quote"]
    assert all(value not in json.dumps(result) for value in (key, token, account))


def test_quote_permission_failure_is_separate_from_valid_profile(tmp_path):
    private_file(
        tmp_path,
        {
            "KITE_API_KEY": secrets.token_hex(16),
            "KITE_ACCESS_TOKEN": secrets.token_hex(16),
        },
    )

    def quote(_):
        raise PermissionException(secrets.token_hex(16))

    result = diagnose(
        tmp_path,
        client_factory=lambda **_: SimpleNamespace(profile=lambda: {}, quote=quote),
    )
    assert result["profile_authenticated"] is True
    assert result["status"] == "quote_unavailable"
    assert result["diagnostic"]["code"] == "permission_denied"


def test_provider_health_keeps_safe_error_code_and_no_upstream_text():
    provider = object.__new__(KiteProvider)
    provider.api_key = secrets.token_hex(8)
    provider.access_token = secrets.token_hex(16)
    provider._auth_lock = threading.Lock()
    provider._auth_checked_at = 0
    sentinel = secrets.token_hex(20)

    def profile():
        raise NetworkException(sentinel, reason="proxy_failure")

    provider.kite = SimpleNamespace(profile=profile)
    health = provider.health()
    assert health["authenticated"] is False
    assert health["auth_error_code"] == "proxy_failure"
    assert sentinel not in json.dumps(health)


def test_kite_page_displays_safe_network_cause_instead_of_expired_token(monkeypatch):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    sentinel = secrets.token_hex(20)
    data = {
        "status": "unavailable",
        "authenticated": False,
        "broker_orders_allowed": False,
        "diagnostic": {"code": "tls_failure", "message": sentinel},
    }
    monkeypatch.setattr(
        "webapp.runtime.api_client",
        lambda **_: SimpleNamespace(get_json=lambda *a, **k: data),
    )
    monkeypatch.setattr("webapp.runtime.admin_key_configured", lambda: True)
    page = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "webapp/pages/live_kite.py"
    ).run(timeout=15)
    assert not page.exception
    assert any("TLS connection" in item.value for item in page.warning)
    assert not any("expired" in item.value for item in page.warning)
    assert sentinel not in " ".join(item.value for item in page.warning)


def test_repository_env_with_windows_bom_loads_the_api_key(tmp_path, monkeypatch):
    import os
    import runpy
    from pathlib import Path

    import dotenv

    monkeypatch.setattr(os, "environ", dict(os.environ))
    key = secrets.token_hex(16)
    path = tmp_path / ".env"
    path.write_text("KITE_API_KEY=" + key, encoding="utf-8-sig")
    original = dotenv.load_dotenv
    monkeypatch.setattr(
        dotenv, "load_dotenv", lambda **kwargs: original(path, **kwargs)
    )
    loaded = runpy.run_path(Path(__file__).resolve().parents[1] / "config/settings.py")
    assert loaded["KITE_API_KEY"] == key
