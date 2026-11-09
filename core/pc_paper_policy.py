"""Validated PC paper defaults, separate from credentials and broker opt-ins."""

import json
import math
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "pc_paper_policy.json"
FIELDS = {
    "capital": (1000, 1_000_000_000, "TRENDFORGE_PAPER_CAPITAL"),
    "cash_reserve_percent": (0, 100, "TRENDFORGE_PAPER_CASH_RESERVE_PERCENT"),
    "max_open_positions": (1, 25, "TRENDFORGE_PAPER_MAX_OPEN_POSITIONS"),
    "max_daily_entries": (1, 100, "TRENDFORGE_PAPER_MAX_DAILY_ENTRIES"),
    "risk_per_trade_percent": (0.1, 5, "TRENDFORGE_PAPER_RISK_PER_TRADE_PERCENT"),
    "staged_risk_per_trade_percent": (0.1, 0.5, "TRENDFORGE_PAPER_STAGED_RISK_PERCENT"),
    "max_daily_loss_percent": (0.1, 20, "TRENDFORGE_PAPER_MAX_DAILY_LOSS_PERCENT"),
    "max_capital_per_trade_percent": (
        1,
        100,
        "TRENDFORGE_PAPER_MAX_CAPITAL_PER_TRADE_PERCENT",
    ),
    "minimum_rr": (1, 10, "TRENDFORGE_PAPER_MINIMUM_RR"),
    "max_entries_per_scan": (1, 10, "TRENDFORGE_PAPER_AUTO_ENTRY_MAX_PER_SCAN"),
}
INTEGER_FIELDS = {"max_open_positions", "max_daily_entries", "max_entries_per_scan"}


def policy_environment(path=POLICY_PATH):
    policy = json.loads(Path(path).read_text(encoding="utf-8"))
    if set(policy) != {
        *FIELDS,
        "version",
        "daily_loss_basis",
        "retain_realized_loss_guard",
    }:
        raise ValueError("Invalid PC paper policy fields")
    if (
        policy["version"] != "pc-paper-v1"
        or policy["daily_loss_basis"] != "realized_plus_unrealized"
        or policy["retain_realized_loss_guard"] is not True
    ):
        raise ValueError("Unsupported PC paper policy")
    environment = {
        "TRENDFORGE_PAPER_POLICY_VERSION": policy["version"],
        "TRENDFORGE_PAPER_DAILY_LOSS_BASIS": policy["daily_loss_basis"],
    }
    for field, (minimum, maximum, variable) in FIELDS.items():
        value = policy[field]
        if (
            type(value) not in {int, float}
            or not math.isfinite(value)
            or not minimum <= value <= maximum
            or (field in INTEGER_FIELDS and type(value) is not int)
        ):
            raise ValueError("Invalid PC paper policy value")
        environment[variable] = str(value)
    return environment
