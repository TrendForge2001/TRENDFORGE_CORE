from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_settings_load_environment_without_embedded_credentials():
    text = _text("config/settings.py")
    required = (
        "load_dotenv()",
        'os.getenv("KITE_API_KEY")',
        'os.getenv("KITE_API_SECRET")',
        'os.getenv("KITE_ACCESS_TOKEN")',
        'os.getenv("DISCORD_WEBHOOK")',
        'os.getenv("DATABASE_URL")',
    )
    for marker in required:
        assert marker in text


def test_gitignore_excludes_runtime_secrets_and_database_files():
    text = _text(".gitignore")
    for marker in (".env", "*.db", "*.sqlite"):
        assert marker in text


def test_configuration_does_not_contain_known_secret_assignments():
    text = _text("config/settings.py")
    forbidden = ("KITE_API_KEY = \"", "KITE_API_SECRET = \"", "DISCORD_WEBHOOK = \"")
    assert not [marker for marker in forbidden if marker in text]


def test_settings_module_declares_all_current_external_runtime_configuration():
    text = _text("config/settings.py")
    names = (
        "KITE_API_KEY",
        "KITE_API_SECRET",
        "KITE_ACCESS_TOKEN",
        "DISCORD_WEBHOOK",
        "DATABASE_URL",
    )
    for name in names:
        assert name in text
