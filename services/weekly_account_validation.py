"""Validate saved planned risk and terminal accounting independently of sizing."""

import math

from scanner.portfolio_policy import number
from scanner.weekly_account_policy import COMPARISONS, net_bracket


def validate_admissions(result):
    from services.execution_report import ReportValidationError

    def require(condition):
        if not condition:
            raise ReportValidationError("Shared-account admission evidence is invalid")

    policy = result["parameters"].get("account_policy")
    require(policy in [p.to_dict() for p in COMPARISONS])
    admissions = result.get("allocations")
    require(isinstance(admissions, list))
    trade_keys = {(t["symbol"], t["entry_at"]): t for t in result["trades"]}
    require(len(trade_keys) == len(admissions))
    for row in admissions:
        trade = trade_keys.get((row.get("symbol"), row.get("at")))
        require(isinstance(trade, dict))
        require(trade["quantity"] == row.get("quantity"))
        require(trade["entry_price"] == row.get("entry_fill"))
        require(trade["initial_stoploss"] == row.get("stoploss"))
        require(trade["target2"] == row.get("target2"))
        require(
            all(
                number(row.get(k)) is not None
                for k in (
                    "equity_before_entry",
                    "cash_before_entry",
                    "entry_fill",
                    "stoploss",
                    "target2",
                    "planned_open_risk",
                    "existing_open_risk",
                    "notional",
                )
            )
        )
        qty = row.get("quantity")
        require(type(qty) is int and qty > 0)
        e, f = row["equity_before_entry"], row["entry_fill"]
        require(e > 0 and 0 < row["stoploss"] < f < row["target2"])
        bracket = net_bracket(f, row["stoploss"], row["target2"], 0.0012, 0.0005)
        risk = qty * bracket["planned_risk_per_share"]
        require(abs(risk - row["planned_open_risk"]) < 1e-6)
        require(abs(qty * f - row["notional"]) < 1e-6)
        require(qty * f * 1.0012 <= row["cash_before_entry"] + 1e-6)
        if policy["risk_fraction"] is not None:
            require(risk <= 0.01 * e + 1e-6)
            require(qty * f <= 0.3333 * e + 1e-6)
            require(risk + row["existing_open_risk"] <= 0.03 * e + 1e-6)
        if policy["stop_distance_ceiling"] is not None:
            require(bracket["stop_distance_fraction"] <= 0.1 + 1e-12)
        if policy["minimum_net_reward_risk"] is not None:
            require(bracket["net_reward_risk"] >= 1.5 - 1e-12)
    terminal = [t for t in result["trades"] if t.get("terminal_liquidation")]
    drag = math.fsum(
        t["quantity"] * t["exit_price"] * (0.0005 / 0.9995 + 0.0012) for t in terminal
    )
    require(abs(drag - result["metrics"]["terminal_liquidation_drag"]) <= 0.02)
    require(len(admissions) == len(result["trades"]))
