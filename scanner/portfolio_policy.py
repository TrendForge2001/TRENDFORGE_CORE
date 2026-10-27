"""Owner's shared-account policy and transparent score-based allocation."""

from __future__ import annotations

import math

ACCOUNT_CAPITAL = 100_000.0
DEPLOYMENT_LIMIT = 80_000.0
CASH_RESERVE = 20_000.0
MAX_POSITIONS = 3


def number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def risk_details(entry, stoploss, target) -> dict:
    entry, stoploss, target = map(number, (entry, stoploss, target))
    if (
        entry is None
        or stoploss is None
        or target is None
        or not 0 < stoploss < entry < target
    ):
        return {"reward_risk": None, "risk_reward": "Unavailable"}
    risk, reward = entry - stoploss, target - entry
    return {
        "risk_per_share": risk,
        "reward_per_share": reward,
        "reward_risk": reward / risk,
        "risk_reward": f"1:{reward / risk:.2f}",
    }


def allocate_candidates(rows: list[dict], *, budget: float, slots: int) -> list[dict]:
    """Only BUY candidates with valid brackets; no return/profit prediction."""
    if number(budget) is None or budget < 0 or not 0 <= slots <= MAX_POSITIONS:
        raise ValueError("Invalid portfolio allocation budget")
    eligible = {}
    for row in rows:
        score = number(row.get("score"))
        risk = risk_details(row.get("entry"), row.get("stoploss"), row.get("target2"))
        if (
            row.get("signal") != "BUY"
            or score is None
            or not 0 < score <= 100
            or risk["reward_risk"] is None
            or not row.get("symbol")
        ):
            continue
        item = {
            **row,
            **risk,
            "score": score,
            "entry": number(row.get("entry")),
            "stoploss": number(row.get("stoploss")),
            "target2": number(row.get("target2")),
        }
        old = eligible.get(row["symbol"])
        if old is None or score > old["score"]:
            eligible[row["symbol"]] = item
    ranked = sorted(
        eligible.values(),
        key=lambda row: (-row["score"], -row["reward_risk"], row["symbol"]),
    )[:slots]
    total = math.fsum(row["score"] for row in ranked)
    return [
        {
            **row,
            "weight_pct": row["score"] / total * 100,
            "allocation_budget": budget * row["score"] / total,
        }
        for row in ranked
    ]


def evidence_rows(rows: list[dict]) -> list[dict]:
    """Flatten actual source indicator values for tables and safe exports."""
    result = []
    for row in rows:
        risk = risk_details(row.get("entry"), row.get("stoploss"), row.get("target2"))
        indicators = row.get("indicators")
        result.append(
            {
                **{
                    key: row.get(key)
                    for key in (
                        "symbol",
                        "signal",
                        "score",
                        "entry",
                        "stoploss",
                        "target2",
                        "bar_at",
                        "execution_eligible",
                        "execution_blocked_reason",
                    )
                },
                **risk,
                **{
                    f"indicator_{key}": number(value)
                    for key, value in (
                        indicators.items() if isinstance(indicators, dict) else []
                    )
                },
            }
        )
    return result
