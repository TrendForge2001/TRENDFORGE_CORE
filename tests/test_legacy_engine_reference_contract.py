from __future__ import annotations

from pathlib import Path
import ast


ROOT = Path(__file__).resolve().parents[1]
ENGINES = ROOT / "engines"

LEGACY_CANDIDATES = {
    "big_shark_engine.py",
    "block_deal_engine.py",
    "scanner_engine.py",
}

CANONICAL_ORCHESTRATOR = "engine_orchestrator.py"


def _imports_from(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    refs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            refs.add(node.module)
        elif isinstance(node, ast.Import):
            refs.update(alias.name for alias in node.names)
    return refs


def test_legacy_engine_candidates_are_not_imported_by_orchestrator():
    refs = _imports_from(ENGINES / CANONICAL_ORCHESTRATOR)
    assert not any(name in ref for ref in refs for name in ("big_shark_engine", "block_deal_engine", "scanner_engine"))


def test_legacy_engine_files_are_present_before_any_removal_decision():
    present = {path.name for path in ENGINES.iterdir() if path.is_file()}
    assert LEGACY_CANDIDATES.intersection(present)


def test_legacy_candidates_are_explicitly_noncanonical():
    text = (ENGINES / CANONICAL_ORCHESTRATOR).read_text(encoding="utf-8")
    for filename in LEGACY_CANDIDATES:
        module = filename.removesuffix(".py")
        assert f"{module}" not in text
