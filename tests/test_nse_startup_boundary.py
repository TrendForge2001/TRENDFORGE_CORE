from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_nse_provider_construction_has_no_network_call():
    tree = ast.parse(_source("providers/nse_provider.py"))
    init = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    calls = [
        node for node in ast.walk(init)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"get", "post", "request"}
    ]
    assert calls == []


def test_nse_session_is_initialized_only_before_an_actual_request():
    source = _source("providers/nse_provider.py")
    assert "self._ensure_session()" in source
    assert "self.session.get(self.BASE_URL, timeout=10)" in source
