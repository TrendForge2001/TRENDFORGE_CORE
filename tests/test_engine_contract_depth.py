from __future__ import annotations

import importlib
import inspect
from pathlib import Path

from engines.base_engine import BaseEngine, EngineResult


ENGINE_DIR = Path(__file__).resolve().parents[1] / "engines"


def _engine_classes():
    classes = []
    for path in ENGINE_DIR.glob("*_engine.py"):
        if path.name in {"base_engine.py", "engine_orchestrator.py"}:
            continue
        module = importlib.import_module(f"engines.{path.stem}")
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == module.__name__ and issubclass(cls, BaseEngine) and cls is not BaseEngine:
                classes.append(cls)
    return classes


def test_all_engine_implementations_follow_base_contract():
    classes = _engine_classes()
    assert classes, "No engine implementations discovered"
    for cls in classes:
        assert callable(getattr(cls, "evaluate", None)), cls.__name__
        signature = inspect.signature(cls.evaluate)
        assert "stock" in signature.parameters, cls.__name__


def test_engine_results_are_serializable_contract_objects():
    result = EngineResult(name="contract", score=0.0, signal="HOLD")
    payload = result.as_dict()
    assert payload["name"] == "contract"
    assert payload["score"] == 0.0
    assert payload["signal"] == "HOLD"


def test_engine_source_has_no_provider_execution_imports():
    forbidden = (
        "providers.kite_provider",
        "providers.yfinance_provider",
        "providers.nse_provider",
        "kiteconnect",
    )
    for path in ENGINE_DIR.glob("*_engine.py"):
        if path.name in {"base_engine.py", "engine_orchestrator.py"}:
            continue
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden), path
