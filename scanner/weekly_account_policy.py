"""Versioned research variants; never changes paper/live admission policy."""

from dataclasses import asdict, dataclass

VERSION = "weekly-shared-account-research-v2"


@dataclass(frozen=True)
class WeeklyAccountPolicy:
    variant: str
    risk_fraction: float | None = None
    allocation_fraction: float | None = None
    open_risk_fraction: float | None = None
    stop_distance_ceiling: float | None = None
    minimum_net_reward_risk: float | None = None

    def to_dict(self):
        return {"version": VERSION, **asdict(self), "max_positions": 3}


COMPARISONS = (
    WeeklyAccountPolicy("shared_account_baseline"),
    WeeklyAccountPolicy("risk_sizing", 0.01, 0.3333, 0.03),
    WeeklyAccountPolicy("stop_distance_10pct", 0.01, 0.3333, 0.03, 0.10),
    WeeklyAccountPolicy("target_room_1_5R", 0.01, 0.3333, 0.03, 0.10, 1.5),
)


def net_bracket(entry_fill, stop, target, fee_rate, slip_rate):
    """Long entry already slipped; normal exit slippage and both fees included."""
    paid = entry_fill * (1 + fee_rate)
    stop_proceeds = stop * (1 - slip_rate) * (1 - fee_rate)
    target_proceeds = target * (1 - slip_rate) * (1 - fee_rate)
    risk = paid - stop_proceeds
    reward = target_proceeds - paid
    return {
        "planned_risk_per_share": risk,
        "net_reward_per_share": reward,
        "net_reward_risk": reward / risk if risk > 0 else None,
        "stop_distance_fraction": (entry_fill - stop) / entry_fill,
    }
