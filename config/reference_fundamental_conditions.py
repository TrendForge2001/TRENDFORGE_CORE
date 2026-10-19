"""Source-Excel research priorities for TrendForge fundamentals (R71.3).

Reference ONLY: extracted from the user's Equity research-1.xlsx and
Stock selection 10 oct 26.xlsx. The source workbooks are not dependencies
and no historical company values, buy labels, or forecasts are imported.

The Excel prioritizes observations, but does not supply general numeric
cutoffs or scoring weights. This module MUST NOT affect canonical
fundamental quality points, pass/fail, scan eligibility, or orders.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

REFERENCE_VERSION = "R71.3"
REFERENCE_BOOKS = (
    "Equity research-1.xlsx",
    "Stock selection 10 oct 26.xlsx",
)

# Exact priority ORDER from Equity research-1.xlsx / "Relative video"!J12:L29
# Spelling standardized to engine keys; the original text is preserved below.
AGGRESSIVE = (
    ("operating_profit_margin", "Operating profit margin"),
    ("peg", "PEG"),
    ("roe_3y_avg", "ROE 3 yr"),
    ("roce_3y_avg", "ROCE 3 yr"),
    ("sales_growth_3y", "Sales growth 3 yr"),
    ("eps_growth_3y", "EPS 3 yr"),
    ("profit_growth", "Profit growth"),
    ("profit_after_tax", "PAT"),
    ("ev_ebitda", "EVEBDITA"),
    ("inventory_turnover", "Inventory turnover ratio"),
    ("roa_3y_avg", "ROA 3 yr"),
    ("interest_turnover", "Interest turnover ratio"),
    ("promoter_holding", "Promotor holding"),
    ("promoter_holding_change", "Change in promotor holding"),
    ("current_ratio", "current ratio"),
    ("quick_ratio", "quick ratio"),
    ("interest_coverage", "Interest coverage ratio"),
    ("debt_equity", "Debt to equity"),
)

CONSERVATIVE = (
    ("debt_equity", "Debt to equity"),
    ("interest_coverage", "Interest coverage ratio"),
    ("quick_ratio", "Quick ratio"),
    ("current_ratio", "Current ratio"),
    ("promoter_holding", "Promotor holding"),
    ("pledged", "Pledged Promotor holding %"),
    ("promoter_holding_change", "Change in promotor holding"),
    ("roa_3y_avg", "ROA 3 yr avg"),
    ("ev_ebitda", "EVEBDITA"),
    ("inventory_turnover", "Inventory turnover ratio"),
    ("profit_growth", "Profit growth"),
    ("eps", "EPS"),
    ("sales_growth_3y", "Sales growth 3 years"),
    ("roce_3y_avg", "ROCE 3 yr avg"),
    ("roe_3y_avg", "ROE 3 yr Avg"),
    ("peg", "PEG"),
    ("operating_profit", "Operating profit"),
)

PROFILES = {"aggressive": AGGRESSIVE, "conservative": CONSERVATIVE}

# Stock selection 10 oct 26.xlsx / "Final"!A1:R1.
# These are columns, NOT rules, screening cutoffs, or current data.
SELECTION_REFERENCE_COLUMNS = (
    ("Industry", "industry"), ("Company", "company"),
    ("CMP Rs.", "price"), ("Mar Cap Rs.Cr.", "market_cap"),
    ("P/E", "pe"), ("Sales growth %", "sales_growth"),
    ("Sales Var 5Yrs %", "sales_growth_5y"),
    ("OPM %", "operating_profit_margin"),
    ("Profit growth %", "profit_growth"),
    ("Profit Var 5Yrs %", "profit_growth_5y"),
    ("Reserves Rs.Cr.", "reserves"),
    ("ROCE %", "roce"), ("ROCE 5Yr %", "roce_5y_avg"),
    ("ROE %", "roe"), ("ROE 5Yr %", "roe_5y_avg"),
    ("EPS 12M Rs.", "eps_12m"), ("Debt / Eq", "debt_equity"),
    ("Change in Prom Hold %", "promoter_holding_change"),
)

# The Bank and Pharma sheets identify sector-specific observations, not
# universal mandatory gates. Bank!D3:J3 plus Bank!L2 notes;
# Pharma!K3:AL3. All remain reference-only until data definitions validated.
SECTOR_OBSERVATIONS = {
    "bank": (
        "net_interest_margin", "casa_ratio", "roe", "roce",
        "net_profit_after_tax", "net_profit", "slr",
        "net_npa", "cost_of_funds", "advances_growth",
    ),
    "pharma": (
        "net_profit_margin", "reserves", "sales_growth", "market_cap",
        "promoter_holding", "pledged", "promoter_holding_change",
        "eps", "eps_3y_avg", "sales_growth_3y",
        "roe", "roe_3y_avg", "roce", "roce_3y_avg",
        "profit_growth", "profit_growth_3y", "current_ratio",
        "quick_ratio", "roa", "roa_3y_avg", "operating_profit",
        "debt_equity", "profit_after_tax", "ev_ebitda", "peg",
        "interest_coverage", "inventory_turnover",
    ),
}

# Exact 8 mandatory canonical scanner fields remain defined exclusively by
# FundamentalInputContract; source reference does not add execution gates.
# Never treat ROE 3 yr as ROE or EPS 3 yr as canonical EPS growth:
# time horizons/methodologies are not interchangeable.
SOURCE_TRACE = {
    "aggressive": "Equity research-1.xlsx / Relative video!J12:K29",
    "conservative": "Equity research-1.xlsx / Relative video!J12:L28",
    "stock_selection": "Stock selection 10 oct 26.xlsx / Final!A1:R1",
    "bank": "Equity research-1.xlsx / Bank!D3:J3; L2",
    "pharma": "Equity research-1.xlsx / Pharma!K3:AL3",
}


def reference_priority_rows(profile: str) -> list[dict[str, Any]]:
    """Source ordering only. No fabricated absolute weights or thresholds."""
    key = str(profile).strip().lower()
    if key not in PROFILES:
        raise ValueError("Profile must be aggressive or conservative")
    return [
        {
            "priority": position,
            "field": field,
            "source_label": label,
            "source": SOURCE_TRACE[key],
            "numeric_cutoff": None,
            "points": None,
            "scoring_status": "reference_only_unconfigured",
        }
        for position, (field, label) in enumerate(PROFILES[key], start=1)
    ]


def _safe_numeric(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def reference_observation_coverage(
    values: Mapping[str, Any] | None, profile: str
) -> dict[str, Any]:
    """Explain present/missing research observations, NOT investment quality.

    Field names must match their actual measurement periods. Neither present
    metrics nor their availability passes a fundamental quality check.
    """
    payload = values if isinstance(values, Mapping) else {}
    rows = reference_priority_rows(profile)
    available: list[str] = []
    missing: list[str] = []
    for row in rows:
        if _safe_numeric(payload.get(row["field"])) is None:
            missing.append(row["field"])
        else:
            available.append(row["field"])
    total = len(rows)
    return {
        "version": REFERENCE_VERSION,
        "profile": profile.lower(),
        "available_count": len(available),
        "required_observation_count": total,
        "observation_coverage_pct": round(100 * len(available) / total, 2),
        "available_fields": available,
        "missing_fields": missing,
        "thresholds_defined_in_excel": False,
        "quality_score": None,
        "pass": None,
        "status": "reference_data_coverage_only",
        "affects_execution_eligibility": False,
    }


__all__ = [
    "REFERENCE_VERSION", "REFERENCE_BOOKS", "PROFILES",
    "SELECTION_REFERENCE_COLUMNS", "SECTOR_OBSERVATIONS", "SOURCE_TRACE",
    "reference_priority_rows", "reference_observation_coverage",
]
