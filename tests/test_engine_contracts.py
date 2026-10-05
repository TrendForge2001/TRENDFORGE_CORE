from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from engines.base_engine import BaseEngine, EngineResult


ENGINE_MODULES = [
    "engines.breakout_engine",
    "engines.market_regime_engine",
    "engines.price_action_engine",
    "engines.technical_engine",
    "engines.trend_engine",
    "engines.signal_engine",
    "engines.volume_engine",
    "engines.vwap_engine",
    "engines.pivot_engine",
    "engines.volatility_engine",
    "engines.risk_engine",
    "engines.data_readiness",
    "engines.sector_engine",
    "engines.sector_strength_engine",
    "engines.block_deal_engine",
    "engines.corporate_action_engine",
    "engines.big_shark_engine",
]


def _engine_classes(module):
    return [
        value for value in vars(module).values()
        if isinstance(value, type)
        and issubclass(value, BaseEngine)
        and value is not BaseEngine
    ]


@pytest.mark.parametrize("module_name", ENGINE_MODULES)
def test_engine_modules_use_base_contract(module_name):
    module = importlib.import_module(module_name)
    classes = _engine_classes(module)
    if not classes:
        pytest.skip(f"No BaseEngine implementation exported by {module_name}")
    for cls in classes:
        assert callable(getattr(cls, "evaluate", None)), cls.__name__


def test_engine_result_is_serializable_contract():
    result = EngineResult(
        engine="test",
        passed=True,
        score=80,
        confidence=90,
        grade="A",
        reasons=["ok"],
        metrics={"value": 1},
    )
    payload = result.as_dict()
    assert payload["engine"] == "test"
    assert payload["score"] == 80
    assert payload["confidence"] == 90
    assert payload["reasons"] == ["ok"]


def test_engine_layer_has_no_market_data_provider_imports():
    root = Path(__file__).resolve().parents[1] / "engines"
    forbidden = ("providers.kite_provider", "providers.yfinance_provider", "providers.nse_provider")
    violations = []
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                violations.append(f"{path}:{token}")
    assert not violations, "Engine/provider boundary violations: " + ", ".join(violations)
