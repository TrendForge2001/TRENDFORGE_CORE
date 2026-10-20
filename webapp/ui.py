"""Reusable visual primitives for the TrendForge Streamlit UI."""
from __future__ import annotations

from html import escape
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
  --tf-primary: #4f8cff;
  --tf-primary-strong: #6aa0ff;
  --tf-green: #22c987;
  --tf-amber: #f0b84b;
  --tf-red: #ff667a;
  --tf-violet: #8f7cff;
  --tf-radius: 12px;
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
  padding-top: 1.35rem;
  padding-bottom: 3.5rem;
  max-width: 1540px;
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
    padding-top: .9rem;
  }
  .tf-title {
    font-size: 1.8rem;
  }
}
</style>
"""


def apply_theme() -> None:
    st.markdown(THEME_CSS, unsafe_allow_html=True)


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
    admin_text = "Authorized" if admin_ready else "Read-only"
    st.markdown(
        f"""
        <div class="tf-sidebar-status">
          <div class="tf-status-row">
            <span>Core API</span>
            <span class="tf-status-value"><span class="tf-dot tf-dot-green"></span>Configured</span>
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
            "On the System & Access page, configure the production TrendForge "
            "admin key for this browser session. Do not enter Kite credentials here."
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
