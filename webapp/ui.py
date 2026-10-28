"""Reusable visual primitives for the TrendForge Streamlit UI."""
from __future__ import annotations

from html import escape
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Iterable

import streamlit as st

from webapp.api_client import ApiError


THEME_CSS = """
<style>
:root {
  --tf-bg: #060b13;
  --tf-bg-elevated: #08111d;
  --tf-panel: #0b1422;
  --tf-panel-2: #0f1b2d;
  --tf-panel-hover: #132238;
  --tf-border: #1f3046;
  --tf-border-soft: #17263a;
  --tf-text: #f4f7fb;
  --tf-muted: #8fa3bc;
  --tf-primary: #6c8cff;
  --tf-primary-strong: #6aa0ff;
  --tf-green: #22c987;
  --tf-amber: #f0b84b;
  --tf-red: #ff667a;
  --tf-violet: #8f7cff;
  --tf-radius: 10px;
}

html, body, [class*="css"] {
  font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

[data-testid="stAppViewContainer"] {
  color: var(--tf-text);
  background:
    radial-gradient(circle at 78% -10%, rgba(79,140,255,.10), transparent 26rem),
    radial-gradient(circle at 25% 105%, rgba(34,201,135,.05), transparent 30rem),
    var(--tf-bg);
}

[data-testid="stHeader"] {
  background: rgba(6,11,19,.88);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid rgba(31,48,70,.55);
}

.block-container {
  padding-top: 4.5rem;
  padding-bottom: 3.5rem;
  max-width: 1680px;
}

[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #07101a 0%, #080e17 100%);
  border-right: 1px solid var(--tf-border);
}

[data-testid="stSidebar"] > div:first-child {
  padding-top: 1.05rem;
}

[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] small {
  color: var(--tf-muted);
}

[data-testid="stSidebarNav"] span,
[data-testid="stSidebarNav"] a {
  font-size: .89rem;
}

[data-testid="stSidebarNav"] a {
  border-radius: 9px;
  margin: 2px 0;
}

[data-testid="stSidebarNav"] a:hover {
  background: rgba(79,140,255,.08);
}

[data-testid="stSidebarNav"] a[aria-current="page"] {
  background: rgba(79,140,255,.14);
  border: 1px solid rgba(79,140,255,.22);
}

.tf-brand {
  display: flex;
  align-items: center;
  gap: .72rem;
  padding: .1rem 0 .95rem 0;
}

.tf-brand-mark {
  display: grid;
  place-items: center;
  width: 2.15rem;
  height: 2.15rem;
  border-radius: 10px;
  color: #07101a;
  font-size: .78rem;
  font-weight: 900;
  letter-spacing: -.02em;
  background: linear-gradient(145deg, var(--tf-primary-strong), var(--tf-green));
  box-shadow: 0 0 0 1px rgba(255,255,255,.05), 0 8px 24px rgba(79,140,255,.18);
}

.tf-brand-title {
  color: var(--tf-text);
  font-size: 1.08rem;
  font-weight: 800;
  letter-spacing: .055em;
  line-height: 1.05;
}

.tf-brand-sub {
  color: var(--tf-muted);
  font-size: .70rem;
  margin-top: .18rem;
}

.tf-sidebar-label {
  margin: 1rem 0 .35rem 0;
  color: #657a94;
  font-size: .66rem;
  font-weight: 800;
  letter-spacing: .15em;
  text-transform: uppercase;
}

.tf-sidebar-status {
  padding: .78rem .82rem;
  border: 1px solid var(--tf-border-soft);
  border-radius: 11px;
  background: rgba(15,27,45,.76);
  margin-bottom: .55rem;
}

.tf-status-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .5rem;
  color: var(--tf-muted);
  font-size: .74rem;
  margin-bottom: .42rem;
}

.tf-status-row:last-child {
  margin-bottom: 0;
}

.tf-status-value {
  color: var(--tf-text);
  font-weight: 700;
}

.tf-dot {
  display: inline-block;
  width: .48rem;
  height: .48rem;
  border-radius: 999px;
  margin-right: .32rem;
  vertical-align: 1px;
  background: var(--tf-muted);
}

.tf-dot-green { background: var(--tf-green); }
.tf-dot-amber { background: var(--tf-amber); }

.tf-kicker {
  display: inline-flex;
  align-items: center;
  gap: .4rem;
  min-height: 1.5rem;
  margin-bottom: .58rem;
  padding: .26rem .52rem;
  border: 1px solid rgba(79,140,255,.22);
  border-radius: 999px;
  color: #a9c6ff;
  background: rgba(79,140,255,.08);
  font-size: .66rem;
  font-weight: 800;
  letter-spacing: .12em;
  text-transform: uppercase;
}

.tf-title {
  color: var(--tf-text);
  font-size: clamp(1.75rem, 3vw, 2.45rem);
  font-weight: 800;
  letter-spacing: -.035em;
  line-height: 1.02;
  margin: 0 0 .48rem 0;
}

.tf-subtitle {
  color: var(--tf-muted);
  max-width: 960px;
  font-size: .96rem;
  line-height: 1.55;
  margin-bottom: 1.15rem;
}

.tf-card {
  background: linear-gradient(180deg, rgba(15,27,45,.96), rgba(11,20,34,.96));
  border: 1px solid var(--tf-border);
  border-radius: var(--tf-radius);
  padding: 1rem 1.05rem;
  margin-bottom: .85rem;
  box-shadow: 0 10px 32px rgba(0,0,0,.12);
}

.tf-note,
.tf-danger-note {
  padding: .72rem .85rem;
  border-radius: 9px;
  color: #a8bad0;
  margin: .45rem 0 .85rem 0;
  font-size: .86rem;
  line-height: 1.45;
}

.tf-note {
  border: 1px solid rgba(34,201,135,.20);
  border-left: 3px solid var(--tf-green);
  background: rgba(34,201,135,.055);
}

.tf-danger-note {
  border: 1px solid rgba(255,102,122,.20);
  border-left: 3px solid var(--tf-red);
  background: rgba(255,102,122,.055);
}

div[data-testid="stMetric"] {
  min-height: 100%;
  padding: .82rem .92rem;
  border: 1px solid var(--tf-border);
  border-radius: var(--tf-radius);
  background: linear-gradient(180deg, rgba(15,27,45,.92), rgba(10,19,32,.92));
  box-shadow: inset 0 1px 0 rgba(255,255,255,.018);
}

div[data-testid="stMetric"] label {
  color: var(--tf-muted) !important;
  font-size: .75rem !important;
}

div[data-testid="stMetricValue"] {
  color: var(--tf-text);
  font-size: 1.42rem;
  font-variant-numeric: tabular-nums;
  letter-spacing: -.02em;
}

div[data-testid="stForm"] {
  padding: 1rem 1rem .35rem 1rem;
  border: 1px solid var(--tf-border);
  border-radius: var(--tf-radius);
  background: rgba(11,20,34,.72);
}

div[data-testid="stVerticalBlockBorderWrapper"] {
  border-color: var(--tf-border) !important;
}

button[kind="primary"] {
  border-radius: 9px !important;
  border: 1px solid rgba(106,160,255,.55) !important;
  background: linear-gradient(180deg, #5c95ff 0%, #3f7ff5 100%) !important;
  font-weight: 700 !important;
  box-shadow: 0 5px 18px rgba(79,140,255,.16);
}

button[kind="secondary"] {
  border-radius: 9px !important;
  border-color: var(--tf-border) !important;
  background: rgba(15,27,45,.75) !important;
}

button[kind="secondary"]:hover {
  border-color: rgba(79,140,255,.45) !important;
  color: #b9d0ff !important;
}

div[data-baseweb="input"] > div,
div[data-baseweb="select"] > div,
textarea {
  border-color: var(--tf-border) !important;
  background: #0a1320 !important;
  border-radius: 9px !important;
}

div[data-testid="stDataFrame"] {
  border: 1px solid var(--tf-border);
  border-radius: var(--tf-radius);
  overflow: hidden;
  background: rgba(8,17,29,.74);
}

[data-baseweb="tab-list"] {
  gap: .28rem;
  border-bottom: 1px solid var(--tf-border);
}

[data-baseweb="tab"] {
  border-radius: 8px 8px 0 0;
  color: var(--tf-muted);
  font-weight: 650;
}

[data-baseweb="tab"][aria-selected="true"] {
  color: var(--tf-text);
  background: rgba(79,140,255,.08);
}

hr {
  border-color: var(--tf-border-soft) !important;
}

h1, h2, h3 {
  letter-spacing: -.02em;
}

[data-testid="stAlert"] {
  border-radius: 10px;
}

@media (max-width: 900px) {
  .block-container {
    padding-left: 1rem;
    padding-right: 1rem;
    padding-top: 4rem;
  }
  .tf-title {
    font-size: 1.8rem;
  }
}
/* Terminal shell: readable hierarchy, compact data and visible focus. */
.tf-workspace-bar {
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: .75rem; padding: .8rem 1rem;
  margin-bottom: 1.5rem; border: 1px solid var(--tf-border);
  border-radius: var(--tf-radius); background: var(--tf-bg-elevated);
}
.tf-workspace-wordmark {font-size: .8rem; font-weight: 800; letter-spacing: .12em;}
.tf-workspace-context {color: var(--tf-muted); font-size: .78rem; margin-left: .8rem;}
.tf-workspace-meta {display: flex; flex-wrap: wrap; align-items: center; gap: .75rem;}
.tf-mode-chip {
  border: 1px solid #344975; border-radius: 5px; padding: .25rem .5rem;
  color: #c2d2ff; font-size: .7rem; font-weight: 700;
}
.tf-workspace-time {font-size: .75rem; color: var(--tf-muted); font-variant-numeric: tabular-nums;}
.tf-title {font-size: clamp(1.65rem, 2.5vw, 2.1rem); line-height: 1.15;}
.tf-subtitle {font-size: .88rem; max-width: 780px;}
.tf-card, div[data-testid="stMetric"] {box-shadow: none;}
[data-testid="stDataFrame"] {font-variant-numeric: tabular-nums;}
[data-testid="stSegmentedControl"] {margin-bottom: .75rem;}
button:focus-visible, a:focus-visible, input:focus-visible {
  outline: 2px solid #a6bdff !important; outline-offset: 3px;
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {animation: none !important; transition: none !important;}
}
@media (max-width: 640px) {
  .tf-workspace-bar {padding: .7rem; margin-bottom: 1rem;}
  .tf-workspace-context {display: block; margin: .25rem 0 0;}
  .tf-workspace-time {font-size: .7rem;}
  .tf-title {font-size: 1.65rem;}
  div[data-testid="stMetric"] {padding: .65rem;}
}
</style>
"""

COMPACT_CSS = """
<style>
:root {--tf-primary: #719bff; --tf-green: #38dfa5; --tf-red: #ff7792; --tf-amber: #ffd166;}
[class*="st-key-tf_"][class*="_controls"] {border-top: 3px solid #719bff !important; background: linear-gradient(155deg, rgba(40,66,129,.17), rgba(13,20,34,.75));}
[class*="st-key-tf_"][class*="_results"] {border-top: 3px solid #35cdb2 !important; background: linear-gradient(155deg, rgba(20,91,90,.09), rgba(13,20,34,.65));}
[data-testid="stMetric"] {border-top: 2px solid #719bff !important; background: linear-gradient(135deg, rgba(60,93,169,.16), rgba(14,23,39,.85));}
[data-testid="stColumn"]:nth-child(2) [data-testid="stMetric"] {border-top-color: #38dfa5 !important;}
[data-testid="stColumn"]:nth-child(3) [data-testid="stMetric"] {border-top-color: #b49aff !important;}
[data-testid="stColumn"]:nth-child(4) [data-testid="stMetric"] {border-top-color: #ffd166 !important;}
[class*="st-key-paper_automation_start"] button,
[class*="st-key-scanner_paper_start"] button {background: #11784f !important; border-color: #38dfa5 !important; color: #ffffff !important;}
[class*="st-key-paper_automation_stop"] button,
[class*="st-key-scanner_paper_stop"] button {background: #62283b !important; border-color: #ff7792 !important; color: #ffeaf0 !important;}
[data-testid="stButton"] button:disabled {opacity: .45;}
.tf-signal-legend {display: flex; flex-wrap: wrap; gap: .4rem; font-size: .72rem; margin-bottom: .35rem;}
.tf-signal-legend span {border: 1px solid currentColor; border-radius: 7px; padding: .15rem .45rem;}
.block-container {padding: 3.6rem 1.25rem .7rem; max-width: 1840px;}
.tf-workspace-bar {padding: .4rem .7rem; margin-bottom: .55rem;}
.tf-kicker {margin-bottom: .2rem; min-height: 1rem; padding: .15rem .4rem; font-size: .6rem;}
.tf-title {font-size: 1.5rem; margin-bottom: .2rem;}
.tf-subtitle {font-size: .78rem; margin-bottom: .45rem;}
[data-testid="stVerticalBlock"] {gap: .55rem;}
[data-testid="stMetric"] {padding: .45rem .6rem !important; min-height: 0 !important;}
[data-testid="stMetricValue"] {font-size: 1.25rem;}
[data-testid="stMetricLabel"] p {font-size: .72rem;}
[data-testid="stMarkdownContainer"] h3 {font-size: 1.05rem; padding: .3rem 0;}
[data-testid="stForm"] {padding: .55rem !important;}
[data-testid="stButton"] button, [data-testid="stDownloadButton"] button {min-height: 2rem; padding: .2rem .5rem;}
@media (min-width: 901px) {
  div:has(> [class*="st-key-tf_"][class*="_controls"]),
  div:has(> [class*="st-key-tf_"][class*="_results"]) {flex-basis: calc(100dvh - 235px) !important; height: calc(100dvh - 235px) !important; max-height: calc(100dvh - 235px) !important;}
  [class*="st-key-tf_"][class*="_controls"],
  [class*="st-key-tf_"][class*="_results"] {height: 100% !important; min-height: 340px; max-height: calc(100dvh - 235px);}
}
@media (max-width: 640px) {
  .block-container {padding: 3.5rem .55rem .7rem;}
  .tf-workspace-bar {margin-bottom: .4rem; padding: .35rem .5rem;}
  .tf-workspace-context {display: none;}
  [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [class*="st-key-tf_"][class*="_controls"]) {flex-wrap: wrap;}
  [data-testid="stColumn"]:has([class*="st-key-tf_"][class*="_controls"]),
  [data-testid="stColumn"]:has([class*="st-key-tf_"][class*="_results"]) {width: 100% !important; flex: 1 1 100% !important; min-width: 0 !important;}
}
</style>
"""


def apply_theme() -> None:
    st.markdown(THEME_CSS + COMPACT_CSS, unsafe_allow_html=True)


def render_signal_legend() -> None:
    st.markdown(
        '<div class="tf-signal-legend">'
        '<span style="color:#4adeaa">BUY / LONG</span>'
        '<span style="color:#ff8098">SELL / SHORT</span>'
        '<span style="color:#8cc8ff">HOLD · existing positions</span>'
        '<span style="color:#ffd166">EXIT / BLOCKED</span>'
        '<span style="color:#a7b7ce">WAIT · no entry</span></div>',
        unsafe_allow_html=True,
    )



def render_workspace_bar() -> None:
    """Workspace context only; never invent market quotes or backend health."""
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    st.markdown(
        f'<div class="tf-workspace-bar" role="banner">'
        '<div><span class="tf-workspace-wordmark">TRENDFORGE</span>'
        '<span class="tf-workspace-context">Market research workspace</span></div>'
        '<div class="tf-workspace-meta"><span class="tf-mode-chip">RESEARCH / PAPER</span>'
        f'<span class="tf-workspace-time">{now:%d %b %Y · %H:%M} IST</span></div></div>',
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
    safe_endpoint = escape(api_endpoint or "not configured")
    admin_class = "tf-dot-green" if admin_ready else "tf-dot-amber"
    admin_text = "Key configured" if admin_ready else "Read-only"
    st.markdown(
        f"""
        <div class="tf-sidebar-status">
          <div class="tf-status-row">
            <span>Core API</span>
            <span class="tf-status-value"><span class="tf-dot tf-dot-amber"></span>Not probed</span>
          </div>
          <div class="tf-status-row">
            <span>Admin</span>
            <span class="tf-status-value"><span class="tf-dot {admin_class}"></span>{admin_text}</span>
          </div>
          <div class="tf-status-row">
            <span>Mode</span>
            <span class="tf-status-value">Research / Paper</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("Backend", expanded=False):
        st.code(safe_endpoint, language=None)


def page_header(title: str, subtitle: str, *, kicker: str = "TrendForge Core") -> None:
    st.markdown(
        f"""
        <div class="tf-kicker">{escape(kicker)}</div>
        <div class="tf-title">{escape(title)}</div>
        <div class="tf-subtitle">{escape(subtitle)}</div>
        """,
        unsafe_allow_html=True,
    )
    render_signal_legend()


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
            "Lock the session and sign in again with the production TrendForge "
            "Admin API Key. Do not enter Kite credentials here."
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
