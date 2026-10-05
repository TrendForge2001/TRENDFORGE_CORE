from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _parse(path: str) -> ast.Module:
    return ast.parse(_source(path), filename=path)


def test_production_entrypoint_is_import_safe_and_thin():
    source = _source("start.py")
    tree = _parse("start.py")
    assert 'from api.app import app' in source
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.Call)]


def test_api_module_defers_provider_and_pipeline_construction_to_factory():
    source = _source("api/app.py")
    assert "from core.application_factory import ApplicationFactory" in source
    for forbidden in ("ProviderFactory(", "FullScannerPipeline(", "EngineOrchestrator("):
        assert forbidden not in source


def test_application_factory_imports_do_not_boot_market_providers_directly():
    source = _source("core/application_factory.py")
    assert "self.providers = provider_factory or ProviderFactory(**provider_kwargs)" in source
    assert "self.providers.market_data()" not in source.split("def market_data", 1)[0]


def test_settings_import_loads_configuration_without_credential_literals():
    source = _source("config/settings.py")
    assert "load_dotenv()" in source
    assert 'os.getenv("KITE_API_KEY")' in source
    assert 'os.getenv("KITE_API_SECRET")' in source
    assert 'os.getenv("DISCORD_WEBHOOK")' in source
