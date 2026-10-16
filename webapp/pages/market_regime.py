"""Persisted NIFTY 500 market regime dashboard."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import info_note, page_header, render_api_error


page_header(
    "Market Regime",
    "Track the broader TrendForge market environment using an equal-weight normalized NIFTY 500 sample composite plus the same canonical regime logic used by the scanner.",
    kicker="Market",
)

client = api_client(timeout=920)

with st.form("regime_refresh"):
    c1, c2, c3 = st.columns(3)
    with c1:
        sample_size = st.selectbox(
            "Sample size",
            [25, 50, 100, 250, 500],
            index=2,
            key="regime_sample_size",
        )
    with c2:
        period = st.selectbox(
            "History",
            ["1y", "2y"],
            index=0,
            key="regime_period",
        )
    with c3:
        refresh_universe = st.toggle(
            "Refresh universe",
            value=False,
            key="regime_refresh_universe",
        )

    refresh = st.form_submit_button(
        "Refresh market context",
        type="primary",
        use_container_width=True,
    )

if refresh:
    if not admin_key_configured():
        st.error(
            "The production admin key is required to refresh market context."
        )
    else:
        try:
            with st.spinner(
                f"Refreshing {sample_size}-symbol NIFTY 500 market context..."
            ):
                client.post_json(
                    "/market/context/refresh",
                    {
                        "limit": int(sample_size),
                        "period": period,
                        "interval": "1d",
                        "refresh_universe": bool(
                            refresh_universe
                        ),
                    },
                    timeout=920,
                )
            st.success("Market context refreshed.")
            st.rerun()
        except ApiError as exc:
            render_api_error(
                exc,
                title="Market context refresh failed",
            )

try:
    regime = client.get_json("/market/regime")
except ApiError as exc:
    render_api_error(
        exc,
        title="Market regime unavailable",
    )
    st.stop()

if regime.get("status") == "not_available":
    info_note(
        "No regime snapshot exists yet. Run Refresh market context to create the first persisted snapshot."
    )
    st.stop()

m1, m2, m3, m4, m5, m6 = st.columns(6)
with m1:
    st.metric(
        "Regime",
        str(regime.get("regime") or "UNKNOWN"),
    )
with m2:
    st.metric(
        "Direction",
        str(regime.get("direction") or "UNKNOWN"),
    )
with m3:
    st.metric(
        "Score",
        f"{float(regime.get('score') or 0):.1f}",
    )
with m4:
    st.metric(
        "Confidence",
        f"{float(regime.get('confidence') or 0):.1f}",
    )
with m5:
    st.metric(
        "Grade",
        str(regime.get("grade") or "—"),
    )
with m6:
    st.metric(
        "Coverage",
        f"{float(regime.get('coverage_pct') or 0):.1f}%",
    )

components = pd.DataFrame(
    [
        {
            "Component": "Trend",
            "Score": regime.get("trend_score"),
            "Max": 30,
        },
        {
            "Component": "Momentum",
            "Score": regime.get("momentum_score"),
            "Max": 20,
        },
        {
            "Component": "Volatility",
            "Score": regime.get("volatility_score"),
            "Max": 20,
        },
        {
            "Component": "Participation",
            "Score": regime.get(
                "participation_score"
            ),
            "Max": 15,
        },
        {
            "Component": "Breadth",
            "Score": regime.get(
                "breadth_component_score"
            ),
            "Max": 15,
        },
    ]
)
components["Score"] = pd.to_numeric(
    components["Score"],
    errors="coerce",
)
components["Utilization %"] = (
    components["Score"] * 100 / components["Max"]
)

st.subheader("Regime components")
st.dataframe(
    components,
    use_container_width=True,
    hide_index=True,
)
if not components["Score"].dropna().empty:
    st.bar_chart(
        components.set_index("Component")[["Score"]]
    )

st.subheader("Composite technical state")
technicals = pd.DataFrame(
    [
        {
            "Metric": "Composite close",
            "Value": regime.get("close"),
        },
        {"Metric": "EMA20", "Value": regime.get("ema20")},
        {"Metric": "EMA50", "Value": regime.get("ema50")},
        {"Metric": "EMA200", "Value": regime.get("ema200")},
        {"Metric": "RSI", "Value": regime.get("rsi")},
        {"Metric": "ADX", "Value": regime.get("adx")},
        {
            "Metric": "ATR %",
            "Value": regime.get("atr_percent"),
        },
        {"Metric": "RVOL", "Value": regime.get("rvol")},
    ]
)
st.dataframe(
    technicals,
    use_container_width=True,
    hide_index=True,
)

reasons = regime.get("reasons")
if isinstance(reasons, list) and reasons:
    st.subheader("Regime evidence")
    for item in reasons:
        st.markdown(f"- {item}")

warnings = regime.get("warnings")
if isinstance(warnings, list) and warnings:
    st.subheader("Risk warnings")
    for item in warnings:
        st.warning(str(item))

st.caption(
    f"Snapshot: {regime.get('snapshot_updated_at') or 'unknown'} · "
    f"Analyzed {regime.get('analyzed_symbols') or 0}/"
    f"{regime.get('requested_symbols') or 0} sampled NIFTY 500 securities · "
    f"Methodology: {regime.get('methodology') or 'unknown'}"
)

info_note(
    "The regime composite is an equal-weight normalized sample of NIFTY 500 constituents. "
    "It is a market filter/diagnostic, not a trade signal by itself."
)
