"""Consistent signal/status and signed financial colours; values stay visible."""

from __future__ import annotations

import pandas as pd

from scanner.portfolio_policy import number

GREEN = "#4adeaa"
RED = "#ff8098"
AMBER = "#ffd166"
BLUE = "#8cc8ff"
MUTED = "#a7b7ce"


def signal_colour(value) -> str:
    label = str(value).strip().upper()
    if label in {"BUY", "LONG", "STRONG_BUY", "PASS", "EXECUTED", "OPENED"}:
        colour = GREEN
    elif label in {"SELL", "SHORT", "STRONG_SELL", "FAIL", "ERROR", "FAILED"}:
        colour = RED
    elif label in {
        "EXIT",
        "BLOCKED",
        "RISK_BLOCKED",
        "REVIEW_REQUIRED",
        "VALIDATING_STRATEGIES",
    }:
        colour = AMBER
    elif label in {"HOLD", "READY", "WATCHING_MARKET", "ARMED"}:
        colour = BLUE
    else:
        colour = MUTED
    return f"color: {colour}; font-weight: 650"


def signed_colour(value) -> str:
    numeric = number(value)
    colour = MUTED if numeric is None or numeric == 0 else GREEN if numeric > 0 else RED
    return f"color: {colour}; font-weight: 650"


def market_frame(frame: pd.DataFrame):
    """Style real values without converting numbers to strings or changing CSVs."""
    styled = frame.style
    for column in frame.columns:
        name = str(column).lower().replace(" ", "_")
        if name in {
            "signal",
            "side",
            "status",
            "consensus",
            "entry_signal",
            "direction",
            "promotion_status",
            "entry_status",
            "exit_reason",
        }:
            styled = styled.map(signal_colour, subset=[column])
        elif any(part in name for part in ("pnl", "p&l", "return", "change")):
            styled = styled.map(signed_colour, subset=[column])
    return styled
