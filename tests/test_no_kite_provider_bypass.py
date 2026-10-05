from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = "providers.kite_provider"
SCANNER_AND_API = ("api", "scanner", "pipeline", "core")


def test_application_layers_do_not_import_kite_provider_directly():
    violations: list[str] = []
    for package in SCANNER_AND_API:
        directory = ROOT / package
        if not directory.exists():
            continue
        for path in directory.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    if any(alias.name == FORBIDDEN for alias in node.names):
                        violations.append(str(path.relative_to(ROOT)))
                elif isinstance(node, ast.ImportFrom):
                    if node.module == FORBIDDEN:
                        violations.append(str(path.relative_to(ROOT)))
    assert violations == []
