from __future__ import annotations

from services.multi_strategy_validation_service import (
    MultiStrategyValidationService,
)


def _good_row():
    return {
        "completed_symbols": 100,
        "universe_scope_pct": 100.0,
        "total_trades": 120,
        "coverage_pct": 100.0,
        "net_pnl": 50000.0,
        "profitable_symbol_pct": 60.0,
        "profit_factor": 1.5,
        "gross_profit": 100000.0,
        "gross_loss": 50000.0,
        "median_symbol_return_pct": 2.0,
        "average_max_drawdown_pct": 8.0,
        "worst_max_drawdown_pct": 20.0,
    }


def test_r7253_staged_scope_is_insufficient_not_promotion_eligible():
    row = _good_row()
    row["universe_scope_pct"] = 25.0

    gate = MultiStrategyValidationService._gate(row)

    assert gate["status"] == "INSUFFICIENT_DATA"
    assert gate["passed"] is False
    assert gate["checks"]["minimum_universe_scope"] is False


def test_r7253_gate_passes_robust_full_universe_metrics():
    gate = MultiStrategyValidationService._gate(_good_row())

    assert gate["status"] == "PASS"
    assert gate["passed"] is True
    assert all(gate["checks"].values())


def test_r7253_gate_fails_weak_profit_factor_after_minimum_data():
    row = _good_row()
    row["profit_factor"] = 0.8

    gate = MultiStrategyValidationService._gate(row)

    assert gate["status"] == "FAIL"
    assert gate["checks"]["profit_factor"] is False


def test_r7253_strategy_promotion_requires_every_selected_universe_to_pass():
    rows = [
        {
            "universe": "NIFTY 100",
            "strategy_id": "tpl_supertrend_rsi",
            "strategy_name": "Template Supertrend RSI",
            "mode": "swing",
            "source": "template",
            "registry_paper_eligible": True,
            "validation_gate": {"status": "PASS"},
        },
        {
            "universe": "NIFTY 200",
            "strategy_id": "tpl_supertrend_rsi",
            "strategy_name": "Template Supertrend RSI",
            "mode": "swing",
            "source": "template",
            "registry_paper_eligible": True,
            "validation_gate": {"status": "PASS"},
        },
    ]

    result = MultiStrategyValidationService._strategy_validation(
        universe_metrics=rows,
        universes=["NIFTY 100", "NIFTY 200"],
    )

    assert result[0]["promotion_status"] == "ELIGIBLE_FOR_REVIEW"
    assert result[0]["paper_execution_enabled"] is False

    rows[1]["validation_gate"] = {"status": "FAIL"}
    result = MultiStrategyValidationService._strategy_validation(
        universe_metrics=rows,
        universes=["NIFTY 100", "NIFTY 200"],
    )
    assert result[0]["promotion_status"] == "NOT_ELIGIBLE"
