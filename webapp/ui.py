"""Reusable visual primitives for the TrendForge Streamlit UI."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

import streamlit as st

from core.deployment_role import cloud_read_only
from webapp.api_client import ApiError
from webapp.design_system import WORKSPACE_CSS

THEME_CSS = WORKSPACE_CSS
COMPACT_CSS = ""


def apply_theme() -> None:
    from webapp.design_system import WORKSPACE_CSS

    st.markdown(WORKSPACE_CSS, unsafe_allow_html=True)


def render_signal_legend() -> None:
    st.markdown(
        '<div class="tf-signal-legend">'
        '<span style="color:#4adeaa">BUY / LONG</span>'
        '<span style="color:#ff8098">SELL · disclosed activity</span>'
        '<span style="color:#8cc8ff">HOLD · existing positions</span>'
        '<span style="color:#ffd166">EXIT / BLOCKED</span>'
        '<span style="color:#a7b7ce">WAIT · no entry</span></div>',
        unsafe_allow_html=True,
    )


def render_workspace_bar() -> None:
    """Workspace context only; never invent market quotes or backend health."""
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    mode = "READ-ONLY CLOUD / PC EXECUTION" if cloud_read_only() else "RESEARCH / PAPER"
    st.markdown(
        f'<div class="tf-workspace-bar" role="banner">'
        '<div><span class="tf-workspace-wordmark">TRENDFORGE</span>'
        '<span class="tf-workspace-context">Market research workspace</span></div>'
        f'<div class="tf-workspace-meta"><span class="tf-mode-chip">{mode}</span>'
        f'<span class="tf-workspace-time">{now:%d %b %Y · %H:%M} IST'
        "</span></div></div>",
        unsafe_allow_html=True,
    )


def render_brand() -> None:
    st.markdown(
        """
        <div class="tf-brand">
          <div class="tf-brand-mark">TF</div>
          <div>
            <div class="tf-brand-title">TRENDFORGE</div>
            <div class="tf-brand-sub">Research · signals · execution control</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_status(*, api_endpoint: str, admin_ready: bool) -> None:
    from webapp.core_status import core_status

    safe_endpoint = escape(api_endpoint or "not configured")
    api_text, api_class = core_status(api_endpoint)
    mode_text = "Read-only cloud" if cloud_read_only() else "Research / Paper"
    admin_class = "tf-dot-green" if admin_ready else "tf-dot-amber"
    admin_text = "Key configured" if admin_ready else "Read-only"
    st.markdown(
        f"""
        <div class="tf-sidebar-status">
          <div class="tf-status-row">
            <span>Core API</span>
            <span class="tf-status-value"><span class="tf-dot {api_class}"></span>
            {api_text}</span>
          </div>
          <div class="tf-status-row">
            <span>Admin</span>
            <span class="tf-status-value"><span class="tf-dot {admin_class}"></span>
            {admin_text}</span>
          </div>
          <div class="tf-status-row">
            <span>Mode</span>
            <span class="tf-status-value">{mode_text}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("Backend", expanded=False):
        st.code(safe_endpoint, language=None)


def page_header(
    title: str,
    subtitle: str,
    *,
    kicker: str = "TrendForge Core",
    show_legend: bool = True,
) -> None:
    st.markdown(
        f"""
        <div class="tf-kicker">{escape(kicker)}</div>
        <div class="tf-title">{escape(title)}</div>
        <div class="tf-subtitle">{escape(subtitle)}</div>
        """,
        unsafe_allow_html=True,
    )
    from webapp.runtime import api_url
    from webapp.stock_lists import ROOT_MANAGED, render_shared_stock_lists

    if st.session_state.get(ROOT_MANAGED):
        render_shared_stock_lists(api_url())


def info_note(text: str, *, danger: bool = False) -> None:
    css_class = "tf-danger-note" if danger else "tf-note"
    st.markdown(
        f'<div class="{css_class}">{escape(text)}</div>',
        unsafe_allow_html=True,
    )


def render_api_error(exc: ApiError, *, title: str = "API request failed") -> None:
    st.error(f"{title}: {exc}")
    if exc.status_code == 401:
        st.info(
            "The backend rejected the administrative API key. "
            "The operator must check the saved server API credential in Render "
            "Environment and redeploy. Sign-in uses only the webapp access key; "
            "do not enter Kite credentials here."
        )
    if exc.status_code in {502, 504}:
        st.info(
            "The API gateway/upstream is unavailable. Check "
            "https://trendforge-core.onrender.com/health directly before "
            "attempting a new scanner run. A failed POST must not be "
            "automatically retried."
        )
    if (
        exc.status_code == 503
        and isinstance(exc.detail, str)
        and "database storage is not verified persistent" in exc.detail.lower()
    ):
        st.warning(
            "TrendForge intentionally blocked this administrative write "
            "because production SQLite storage is not verified persistent. "
            "Do not bypass the guard or enable ephemeral writes. "
            "The completion-upload endpoint also rejects read-only previews "
            "under the current production policy. Download the workbook "
            "and prepare verified values offline; uploading must wait for "
            "approved durable storage or a separately reviewed preview-only API."
        )
    if exc.detail is not None:
        st.caption("Backend detail")
        if isinstance(exc.detail, str):
            detail = exc.detail.strip()
            if "<!doctype html" in detail.lower() or "<html" in detail.lower():
                st.caption(
                    "The upstream returned an HTML error page instead of "
                    "FastAPI JSON. Large raw gateway HTML has been hidden."
                )
            else:
                st.code(detail[:1500], language=None)
        else:
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
                "Eligible": item.get(
                    "execution_eligible",
                    item.get("eligible", item.get("passed")),
                ),
                "Execution Block": item.get(
                    "primary_execution_block",
                    item.get(
                        "execution_rejection_reason",
                        item.get("rejection_reason"),
                    ),
                ),
                "Fundamental Readiness": (
                    item.get("fundamental_readiness", {}).get("status")
                    if isinstance(item.get("fundamental_readiness"), dict)
                    else None
                ),
                "Market Regime": (
                    item.get("market_regime_context", {}).get("regime")
                    if isinstance(item.get("market_regime_context"), dict)
                    else None
                ),
                "Risk R:R": (
                    item.get("risk_context", {}).get("rr")
                    if isinstance(item.get("risk_context"), dict)
                    else None
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
