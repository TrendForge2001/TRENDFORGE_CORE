"""Credential-source precedence, safe secret-file parsing and no flag injection."""

import secrets

import pytest

from core.kite_environment import (
    FIELDS,
    apply_kite_environment,
    resolve_kite_environment,
)
from core.runtime_config import load_runtime_config


@pytest.fixture
def credentials():
    return {name: secrets.token_hex(16) for name in FIELDS}


def write_credentials(tmp_path, values, *, prefix=""):
    path = tmp_path / "kite.env"
    path.write_text(
        prefix + "\n".join(f"{key}={value}" for key, value in values.items()),
        encoding="utf-8",
    )
    return path


def test_saved_process_credentials_win_and_are_trimmed(tmp_path, credentials):
    alternate = {name: secrets.token_hex(16) for name in FIELDS}
    path = write_credentials(tmp_path, alternate)
    result = resolve_kite_environment(
        {
            **{name: f" {value} " for name, value in credentials.items()},
            "TRENDFORGE_KITE_ENV_PATH": str(path),
        }
    )
    assert result.values == credentials
    assert result.source == "environment"
    assert all(value not in repr(result) for value in credentials.values())


def test_bom_secret_file_supplies_a_complete_pair_without_interpolation(
    tmp_path, credentials
):
    credentials["KITE_ACCESS_TOKEN"] += "${UNRELATED_VALUE}"
    path = write_credentials(tmp_path, credentials, prefix="\ufeff")
    result = resolve_kite_environment({"TRENDFORGE_KITE_ENV_PATH": str(path)})
    assert result.values == credentials
    assert result.source == "secret_file"
    assert result.error_code is None


def test_partial_pair_requires_a_matching_key(tmp_path, credentials):
    path = write_credentials(tmp_path, credentials)
    env = {
        "TRENDFORGE_KITE_ENV_PATH": str(path),
        "KITE_API_KEY": credentials["KITE_API_KEY"],
    }
    assert resolve_kite_environment(env).values == credentials
    env["KITE_API_KEY"] = secrets.token_hex(16)
    result = resolve_kite_environment(env)
    assert result.values["KITE_ACCESS_TOKEN"] == ""
    assert result.error_code == "credential_sources_conflict"


def test_runtime_factory_and_settings_loader_use_the_same_values(
    tmp_path, monkeypatch, credentials
):
    path = write_credentials(tmp_path, credentials)
    for name in FIELDS:
        # Record every field so apply_kite_environment's writes are restored.
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("TRENDFORGE_KITE_ENV_PATH", str(path))
    resolved = apply_kite_environment()
    runtime = load_runtime_config()
    assert runtime.kite_api_key == resolved.values["KITE_API_KEY"]
    assert runtime.kite_access_token == resolved.values["KITE_ACCESS_TOKEN"]
    assert runtime.kite_api_secret == resolved.values["KITE_API_SECRET"]


def test_secret_file_cannot_turn_on_trading_or_replace_other_settings(
    tmp_path, monkeypatch, credentials
):
    path = write_credentials(
        tmp_path,
        {
            **credentials,
            "TRENDFORGE_LIVE_TRADING_ENABLED": "true",
            "TRENDFORGE_PAPER_TRADING_ENABLED": "true",
            "TRENDFORGE_ADMIN_API_KEY": secrets.token_hex(16),
        },
    )
    for name in FIELDS:
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("TRENDFORGE_KITE_ENV_PATH", str(path))
    monkeypatch.setenv("TRENDFORGE_LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("TRENDFORGE_PAPER_TRADING_ENABLED", "false")
    admin = secrets.token_hex(16)
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", admin)
    apply_kite_environment()
    import os

    assert os.environ["TRENDFORGE_LIVE_TRADING_ENABLED"] == "false"
    assert os.environ["TRENDFORGE_PAPER_TRADING_ENABLED"] == "false"
    assert os.environ["TRENDFORGE_ADMIN_API_KEY"] == admin


@pytest.mark.parametrize("content", [b"\xff\xff", b"x" * 65_537])
def test_bad_or_oversized_secret_file_reports_only_a_fixed_code(tmp_path, content):
    path = tmp_path / "kite.env"
    path.write_bytes(content)
    result = resolve_kite_environment({"TRENDFORGE_KITE_ENV_PATH": str(path)})
    assert result.error_code == "credential_file_unreadable"
    assert not any(result.values.values())
    assert str(path) not in repr(result)
