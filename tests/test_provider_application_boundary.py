from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _imports_in(path: Path) -> list[ast.Import | ast.ImportFrom]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]


def _module_names(path: Path) -> set[str]:
    names: set[str] = set()
    for node in _imports_in(path):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif node.module:
            names.add(node.module)
    return names


def test_provider_modules_do_not_import_scanner_or_engine_execution_layers():
    providers = ROOT / "providers"
    forbidden_prefixes = ("scanner", "engines", "pipeline")

    offenders = []
    for path in providers.glob("*.py"):
        for module in _module_names(path):
            if module == forbidden_prefixes[0] or module.startswith(forbidden_prefixes[0] + "."):
                offenders.append((str(path.relative_to(ROOT)), module))
            elif module == forbidden_prefixes[1] or module.startswith(forbidden_prefixes[1] + "."):
                offenders.append((str(path.relative_to(ROOT)), module))
            elif module == forbidden_prefixes[2] or module.startswith(forbidden_prefixes[2] + "."):
                offenders.append((str(path.relative_to(ROOT)), module))

    assert offenders == []


def test_api_modules_do_not_import_legacy_scanner_engine_directly():
    api = ROOT / "api"
    offenders = []
    for path in api.glob("*.py"):
        for module in _module_names(path):
            if module in {"scanner.scanner_engine", "engines.scanner_engine", "scanner.pipeline"}:
                offenders.append((str(path.relative_to(ROOT)), module))

    assert offenders == []
