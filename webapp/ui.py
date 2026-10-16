"""Reusable visual primitives for the TrendForge Streamlit UI."""
from __future__ import annotations

from typing import Any, Iterable

import streamlit as st

from webapp.api_client import ApiError


THEME_CSS = """
<style>
:root {
  --tf-bg: #0b0f14;
  --tf-panel: #111827;
  --tf-panel-2: #151d2b;
  --tf-border: #263244;
  --tf-text: #e5e7eb;
  --tf-muted: #94a3b8;
  --tf-green: #22c55e;
  --tf-amber: #f59e0b;
  --tf-red: #ef4444;
}
.block-container {padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1500px;}
[data-testid="stSidebar"] {border-right: 1px solid var(--tf-border);}
.tf-brand {padding: 0.15rem 0 0.8rem 0;}
.tf-brand-title {font-size: 1.28rem; font-weight: 800; letter-spacing: 0.08em; color: var(--tf-text);}
.tf-brand-sub {font-size: 0.76rem; color: var(--tf-muted); margin-top: 0.15rem;}
.tf-kicker {font-size: 0.73rem; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: var(--tf-green);}
.tf-title {font-size: 2rem; line-height: 1.08; font-weight: 800; color: var(--tf-text); margin: 0.18rem 0 0.38rem 0;}
.tf-subtitle {font-size: 0.98rem; color: var(--tf-muted); max-width: 900px; margin-bottom: 1rem;}
.tf-card {background: linear-gradient(180deg, rgba(21,29,43,.95), rgba(17,24,39,.95)); border: 1px solid var(--tf-border); border-radius: 14px; padding: 1rem 1.05rem; margin-bottom: .85rem;}
.tf-note {border-left: 3px solid var(--tf-green); padding: .6rem .8rem; color: var(--tf-muted); background: rgba(34,197,94,.06); border-radius: 6px;}
.tf-danger-note {border-left: 3px solid var(--tf-red); padding: .6rem .8rem; color: var(--tf-muted); background: rgba(239,68,68,.06); border-radius: 6px;}
div[data-testid="stMetric"] {background: rgba(17,24,39,.72); border: 1px solid var(--tf-border); padding: .75rem .85rem; border-radius: 12px;}
</style>
"""


def apply_theme() -> None:
    st.markdown(THEME_CSS, unsafe_allow_html=True)


def render_brand() -> None:
    st.markdown(
        """
        <div class="tf-brand">
          <div class="tf-brand-title">TRENDFORGE</div>
          <div class="tf-brand-sub">Market intelligence & execution control</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str, *, kicker: str = "TrendForge Core") -> None:
    st.markdown(
        f"""
        <div class="tf-kicker">{kicker}</div>
        <div class="tf-title">{title}</div>
        <div class="tf-subtitle">{subtitle}</div>
        """,
        unsafe_allow_html=True,
    )


def info_note(text: str, *, danger: bool = False) -> None:
    css_class = "tf-danger-note" if danger else "tf-note"
    st.markdown(f'<div class="{css_class}">{text}</div>', unsafe_allow_html=True)


def render_api_error(exc: ApiError, *, title: str = "API request failed") -> None:
    st.error(f"{title}: {exc}")
    if exc.detail is not None:
        st.caption("Backend detail")
        st.json(exc.detail)


def value_at(payload: Any, *path: str, default: Any = None) -> Any:
    current = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def first_list(payload: dict[str, Any], keys: Iterable[str]) -> list[Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def scan_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = first_list(
        payload,
        (
            "analysis_top_picks",
            "top_picks",
            "analysis_ranked",
            "eligible",
            "results",
        ),
    )
    rows: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        signal = item.get("signal")
        signal_payload = signal if isinstance(signal, dict) else {}
        signal_name = signal_payload.get("signal")
        if not signal_name and isinstance(signal, str):
            signal_name = signal
        rows.append(
            {
                "Symbol": item.get("symbol"),
                "Signal": signal_name or item.get("final_signal"),
                "Score": signal_payload.get("overall_score", item.get("ranking_score")),
                "Confidence": signal_payload.get("confidence", item.get("confidence")),
                "Entry": signal_payload.get("entry", item.get("entry")),
                "Stop": signal_payload.get("stoploss", item.get("stoploss")),
                "Target 2": signal_payload.get("target2", item.get("target2")),
                "Analysis Eligible": item.get(
                    "analysis_eligible",
                    item.get("eligible", item.get("passed")),
                ),
                "Execution Eligible": item.get(
                    "execution_eligible",
                    item.get("eligible", item.get("passed")),
                ),
                "Execution Block": item.get(
                    "execution_rejection_reason",
                    item.get("rejection_reason"),
                ),
            }
        )
    return rows


def report_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("records", "rows", "items", "fundamentals", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []
