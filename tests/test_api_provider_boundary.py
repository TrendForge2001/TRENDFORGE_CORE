from __future__ import annotations

import ast
from pathlib import Path


API_DIR = Path(__file__).resolve().parents[1] / "api"
FORBIDDEN_DIRECT_PROVIDER_IMPORTS = {
    "providers.kite_provider",
    "providers.nse_provider",
    "providers.yfinance_provider",
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_api_scanner_service_is_the_application_scanning_boundary():
    scanner_service = API_DIR / "scanner_service.py"
    assert scanner_service.exists()
    assert "scanner.full_pipeline" in _imports(scanner_service)


def test_api_has_no_direct_market_data_provider_imports():
    violations = {}
    for path in API_DIR.glob("*.py"):
        imports = _imports(path)
        direct = sorted(imports & FORBIDDEN_DIRECT_PROVIDER_IMPORTS)
        if direct:
            violations[path.name] = direct
    assert violations == {}


def test_scanner_service_does_not_import_legacy_scanner_execution():
    imports = _imports(API_DIR / "scanner_service.py")
    assert "scanner.scanner_engine" not in imports
    assert "scanner.pipeline" not in imports
    assert "engines.scanner_engine" not in imports
