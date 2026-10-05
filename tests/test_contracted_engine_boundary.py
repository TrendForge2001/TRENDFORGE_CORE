from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_every_contracted_engine_validates_before_wrapped_engine_execution():
    files = sorted((ROOT / "engines").glob("contracted_*_engine.py"))
    assert files, "No contracted engine adapters found"

    offenders: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        if "input_contract" not in text or ".validate(stock)" not in text:
            offenders.append(f"{path.name}: missing input contract validation")
            continue
        validate_pos = text.find(".validate(stock)")
        engine_eval_pos = text.find("self.engine.evaluate(stock)")
        if engine_eval_pos == -1 or validate_pos > engine_eval_pos:
            offenders.append(f"{path.name}: wrapped engine can execute before validation")

    assert not offenders, "Contracted-engine boundary violations: " + "; ".join(offenders)


def test_contracted_engines_return_structured_contract_failure_results():
    files = sorted((ROOT / "engines").glob("contracted_*_engine.py"))
    offenders: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        if "if not report.ready" not in text or "EngineResult(" not in text:
            offenders.append(path.name)
    assert not offenders, "Contracted engines lack structured failure handling: " + ", ".join(offenders)
