"""Persisted NIFTY 500 sector-strength dashboard."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import info_note, page_header, render_api_error


page_header(
    "Sector Strength",
    "Rank NIFTY 500 sectors using aggregated momentum, relative performance, volume participation, breadth, leadership and consistency through the canonical Sector Engine.",
    kicker="Market",
)

client = api_client(timeout=920)

info_note(
    "R68.6 does not have a source-backed sector-level FII/DII flow feed. The Sector Engine flow component therefore remains neutral/missing rather than being fabricated."
)

with st.form("sector_strength_refresh"):
    a, b, c = st.columns(3)
    with a:
        sample_size = st.selectbox(
            "NIFTY 500 sample",
            [25, 50, 100, 250, 500],
            index=2,
        )
    with b:
        period = st.selectbox(
            "History",
            ["1y", "2y"],
            index=0,
        )
    with c:
        refresh_universe = st.toggle(
            "Refresh universe",
            value=False,
        )

    refresh = st.form_submit_button(
        "Refresh sector strength",
        type="primary",
        use_container_width=True,
    )

if refresh:
    if not admin_key_configured():
        st.error(
            "Configure the production admin key before refreshing sector strength."
        )
    else:
        try:
            with st.spinner(
                f"Refreshing sector strength from {sample_size} NIFTY 500 securities..."
            ):
                client.post_json(
                    "/sector-strength/refresh",
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
            st.success("Sector-strength snapshot refreshed.")
            st.rerun()
        except ApiError as exc:
            render_api_error(
                exc,
                title="Sector-strength refresh failed",
            )

try:
    snapshot = client.get_json("/sector-strength")
except ApiError as exc:
    render_api_error(
        exc,
        title="Sector-strength snapshot unavailable",
    )
    st.stop()

if snapshot.get("status") == "not_available":
    info_note(
        "No persisted sector-strength snapshot exists yet. Run Refresh sector strength first."
    )
    st.stop()

sectors = snapshot.get("sectors")
sectors = sectors if isinstance(sectors, list) else []

top = sectors[0] if sectors else {}
bottom = sectors[-1] if sectors else {}

m1, m2, m3, m4, m5, m6 = st.columns(6)
with m1:
    st.metric(
        "Coverage",
        f"{float(snapshot.get('coverage_pct') or 0):.1f}%",
    )
with m2:
    st.metric(
        "Sectors",
        int(snapshot.get("sector_count") or 0),
    )
with m3:
    st.metric(
        "Top sector",
        str(top.get("sector") or "—"),
    )
with m4:
    st.metric(
        "Top score",
        f"{float(top.get('score') or 0):.1f}",
    )
with m5:
    st.metric(
        "Weakest sector",
        str(bottom.get("sector") or "—"),
    )
with m6:
    st.metric(
        "Market composite",
        f"{float(snapshot.get('market_return_composite_pct') or 0):.2f}%",
    )

st.caption(
    f"Snapshot: {snapshot.get('snapshot_updated_at') or 'unknown'} · "
    f"Analyzed {snapshot.get('analyzed_symbols') or 0}/"
    f"{snapshot.get('requested_symbols') or 0} sampled securities · "
    f"Methodology: {snapshot.get('methodology') or 'unknown'}"
)

if sectors:
    frame = pd.DataFrame(sectors)
    preferred = [
        "rank",
        "sector",
        "score",
        "confidence",
        "grade",
        "trend",
        "bias",
        "sector_strength",
        "constituents",
        "change_1d",
        "change_1w",
        "change_1m",
        "change_3m",
        "volume_ratio",
        "breadth",
        "leadership_score",
    ]
    columns = [
        column
        for column in preferred
        if column in frame.columns
    ]
    st.subheader("Sector ranking")
    st.dataframe(
        frame[columns],
        use_container_width=True,
        hide_index=True,
    )

    chart = frame[["sector", "score"]].copy()
    chart = chart.set_index("sector")
    st.bar_chart(chart)

    st.download_button(
        "Download sector ranking CSV",
        data=frame.to_csv(index=False).encode("utf-8"),
        file_name="trendforge_sector_strength.csv",
        mime="text/csv",
    )

    selected = st.selectbox(
        "Inspect sector",
        [str(row.get("sector")) for row in sectors],
    )
    detail = next(
        (
            row
            for row in sectors
            if str(row.get("sector")) == selected
        ),
        {},
    )

    d1, d2 = st.columns(2)
    with d1:
        st.subheader("Score components")
        components = detail.get("components")
        components = (
            components
            if isinstance(components, dict)
            else {}
        )
        if components:
            component_frame = pd.DataFrame(
                [
                    {"Component": key, "Score": value}
                    for key, value in components.items()
                ]
            )
            st.dataframe(
                component_frame,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No component evidence available.")
    with d2:
        st.subheader("Participation")
        st.json(
            {
                "constituents": detail.get("constituents"),
                "advancing": detail.get("advancing"),
                "declining": detail.get("declining"),
                "breadth": detail.get("breadth"),
                "volume_ratio": detail.get("volume_ratio"),
                "leadership_score": detail.get(
                    "leadership_score"
                ),
                "institutional_sector_flow_available": (
                    detail.get(
                        "institutional_sector_flow_available"
                    )
                ),
            }
        )

    reasons = detail.get("reasons")
    if isinstance(reasons, list) and reasons:
        st.subheader("Sector evidence")
        for item in reasons:
            st.markdown(f"- {item}")

    warnings = detail.get("warnings")
    if isinstance(warnings, list) and warnings:
        st.subheader("Warnings")
        for item in warnings:
            st.warning(str(item))
else:
    st.info("No sector rows are available in this snapshot.")

failures = snapshot.get("failures")
if isinstance(failures, dict) and failures:
    with st.expander(
        f"Symbol coverage failures ({len(failures)})"
    ):
        st.dataframe(
            pd.DataFrame(
                [
                    {"Symbol": key, "Reason": value}
                    for key, value in failures.items()
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

with st.expander("Provider diagnostics"):
    st.json(snapshot.get("provider_observation") or {})
