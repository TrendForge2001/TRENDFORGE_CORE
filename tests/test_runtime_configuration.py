from __future__ import annotations

from core.runtime_config import (
    RuntimeConfig,
    load_runtime_config,
    validate_runtime_config,
)


def test_runtime_config_reads_environment_without_side_effects():
    config = load_runtime_config(
        {
            "KITE_API_KEY": "key",
            "KITE_API_SECRET": "secret",
            "KITE_ACCESS_TOKEN": "token",
            "DISCORD_WEBHOOK": "webhook",
            "DATABASE_URL": "sqlite:///trendforge.db",
        }
    )

    assert config.kite_configured is True
    assert config.kite_authenticated is True
    assert config.discord_webhook == "webhook"
    assert config.database_url == "sqlite:///trendforge.db"
    assert validate_runtime_config(config) == ()


def test_runtime_config_allows_public_market_data_without_kite_credentials():
    config = RuntimeConfig()

    assert config.kite_configured is False
    assert config.kite_authenticated is False
    assert validate_runtime_config(config) == ()


def test_runtime_config_reports_missing_kite_credentials_only_when_required():
    config = RuntimeConfig(kite_api_key="key")

    errors = validate_runtime_config(config, require_kite=True)

    assert errors == ("Missing required Kite configuration: KITE_API_SECRET",)


def test_runtime_config_rejects_partial_kite_authentication():
    config = RuntimeConfig(kite_access_token="token")

    errors = validate_runtime_config(config)

    assert errors == (
        "KITE_ACCESS_TOKEN is set but KITE_API_KEY and KITE_API_SECRET are incomplete",
    )


def test_provider_configuration_is_explicit_and_deterministic():
    config = RuntimeConfig(kite_api_key="key", kite_api_secret="secret")

    assert config.missing_kite_credentials() == ()
    assert config.kite_configured is True
    assert config.kite_authenticated is False


def test_runtime_configuration_health_reports_partial_authentication():
    health = runtime_configuration_health(RuntimeConfig(kite_access_token="token"))

    assert health["status"] == "invalid"
    assert health["kite_authenticated"] is False
    assert health["errors"]
