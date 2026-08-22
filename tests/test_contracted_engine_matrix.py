from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MATRIX = {
    "big_shark": ("contracted_big_shark_engine.py", "big_shark_contract.py", "BigSharkInputContract"),
    "corporate_action": ("contracted_corporate_action_engine.py", "corporate_action_contract.py", "CorporateActionInputContract"),
    "fundamental": ("contracted_fundamental_engine.py", "fundamental_contract.py", "FundamentalInputContract"),
    "market_regime": ("contracted_market_regime_engine.py", "market_regime_contract.py", "MarketRegimeInputContract"),
    "price_action": ("contracted_price_action_engine.py", "price_action_contract.py", "PriceActionInputContract"),
    "risk": ("contracted_risk_engine.py", "risk_contract.py", "RiskInputContract"),
    "sector": ("contracted_sector_engine.py", "sector_contract.py", "SectorInputContract"),
    "technical": ("contracted_technical_engine.py", "technical_contract.py", "TechnicalInputContract"),
}


def _text(path: str) -> str:
    return (ROOT / "engines" / path).read_text(encoding="utf-8")


def test_every_contracted_engine_has_a_matching_input_contract():
    missing: list[str] = []
    for name, (adapter, contract, contract_class) in MATRIX.items():
        adapter_text = _text(adapter)
        contract_text = _text(contract)
        if contract_class not in adapter_text or contract_class not in contract_text:
            missing.append(name)
    assert not missing, f"Contract matrix gaps: {missing}"


def test_every_contracted_engine_validates_before_delegation():
    violations: list[str] = []
    for name, (adapter, _, _) in MATRIX.items():
        text = _text(adapter)
        validate_pos = text.find("input_contract.validate")
        delegate_pos = text.find("self.engine.evaluate(stock)")
        if validate_pos < 0 or delegate_pos < 0 or validate_pos > delegate_pos:
            violations.append(name)
    assert not violations, f"Validation/delegation ordering violations: {violations}"


def test_signal_contract_uses_generation_boundary_not_engine_evaluate_boundary():
    text = _text("contracted_signal_engine.py")
    assert "SignalInputContract" in text
    assert "self.input_contract.validate(results)" in text
    assert "self.engine.generate_from_results(symbol, results)" in text


def test_known_composition_exceptions_are_explicit():
    # These adapters have canonical implementations supplied by EngineOrchestrator
    # even though their standalone defaults remain legacy-compatible.
    sector = _text("contracted_sector_engine.py")
    shark = _text("contracted_big_shark_engine.py")
    assert "SectorEngine" in sector
    assert "BigSharkEngine" in shark
