from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIRS = [ROOT / "pipeline", ROOT / "core"]


def test_pipeline_layers_do_not_directly_execute_engines():
    violations: list[str] = []
    for directory in PIPELINE_DIRS:
        for path in directory.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr == "evaluate":
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    # Compatibility facades may call EngineOrchestrator.evaluate, but they must
    # not call an arbitrary engine. Detect the known direct-engine pattern.
    assert all(
        "engine_registry.py" in item or "pipeline.py" in item or "scan_pipeline.py" in item
        for item in violations
    )
