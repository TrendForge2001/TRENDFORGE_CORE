"""Persisted NIFTY 500 market breadth dashboard."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import info_note, page_header, render_api_error


page_header(
    "Market Breadth",
    "Monitor NIFTY 500 participation, advance/decline balance, trend breadth, new highs/lows, and sector participation from the latest persisted market-context snapshot.",
    kicker="Market",
)

client = api_client(timeout=920)

with st.form("breadth_refresh"):
    c1, c2, c3 = st.columns(3)
    with c1:
        sample_size = st.selectbox(
            "Sample size",
            [25, 50, 100, 250, 500],
            index=2,
        )
    with c2:
        period = st.selectbox(
            "History",
            ["1y", "2y"],
            index=0,
        )
    with c3:
        refresh_universe = st.toggle(
            "Refresh universe",
            value=False,
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
    breadth = client.get_json("/market/breadth")
except ApiError as exc:
    render_api_error(
        exc,
        title="Market breadth unavailable",
    )
    st.stop()

if breadth.get("status") == "not_available":
    info_note(
        "No breadth snapshot exists yet. Run Refresh market context to create the first persisted snapshot."
    )
    st.stop()

if breadth.get("status") == "degraded":
    info_note(
        "The latest breadth snapshot has degraded coverage. Review failures before treating it as broad-market confirmation.",
        danger=True,
    )

m1, m2, m3, m4, m5, m6 = st.columns(6)
with m1:
    st.metric(
        "Direction",
        str(breadth.get("direction") or "UNKNOWN"),
    )
with m2:
    st.metric(
        "Breadth score",
        f"{float(breadth.get('breadth_score') or 0):.1f}",
    )
with m3:
    st.metric(
        "Coverage",
        f"{float(breadth.get('coverage_pct') or 0):.1f}%",
    )
with m4:
    st.metric(
        "A/D ratio",
        f"{float(breadth.get('advance_decline_ratio') or 0):.2f}",
    )
with m5:
    st.metric(
        "Advances",
        int(breadth.get("advances") or 0),
    )
with m6:
    st.metric(
        "Declines",
        int(breadth.get("declines") or 0),
    )

t1, t2, t3, t4, t5 = st.columns(5)
with t1:
    st.metric(
        "Above EMA20",
        f"{float(breadth.get('above_ema20_pct') or 0):.1f}%",
    )
with t2:
    st.metric(
        "Above EMA50",
        f"{float(breadth.get('above_ema50_pct') or 0):.1f}%",
    )
with t3:
    st.metric(
        "Above EMA200",
        f"{float(breadth.get('above_ema200_pct') or 0):.1f}%",
    )
with t4:
    st.metric(
        "New highs",
        int(breadth.get("new_highs") or 0),
    )
with t5:
    st.metric(
        "New lows",
        int(breadth.get("new_lows") or 0),
    )

st.caption(
    f"Snapshot: {breadth.get('snapshot_updated_at') or 'unknown'} · "
    f"Analyzed {breadth.get('analyzed_symbols') or 0}/"
    f"{breadth.get('requested_symbols') or 0} sampled NIFTY 500 securities · "
    f"Data quality: {breadth.get('data_quality') or 'unknown'}"
)

sectors = breadth.get("sector_strength")
sectors = sectors if isinstance(sectors, list) else []
if sectors:
    st.subheader("Sector participation")
    sector_frame = pd.DataFrame(sectors)
    st.dataframe(
        sector_frame,
        use_container_width=True,
        hide_index=True,
    )
    if (
        "sector" in sector_frame
        and "average_change_pct" in sector_frame
    ):
        st.bar_chart(
            sector_frame.set_index("sector")[
                ["average_change_pct"]
            ]
        )

failures = breadth.get("failures")
if isinstance(failures, dict) and failures:
    with st.expander(
        f"Coverage failures ({len(failures)})"
    ):
        failure_frame = pd.DataFrame(
            [
                {
                    "Symbol": symbol,
                    "Reason": reason,
                }
                for symbol, reason in failures.items()
            ]
        )
        st.dataframe(
            failure_frame,
            use_container_width=True,
            hide_index=True,
        )

with st.expander("Breadth diagnostics"):
    st.json(
        {
            "advance_decline_line": breadth.get(
                "advance_decline_line"
            ),
            "confidence": breadth.get("confidence"),
            "legacy_ema_weighted_score_raw": breadth.get(
                "ema_weighted_score_raw"
            ),
            "provider_observation": breadth.get(
                "provider_observation"
            ),
            "sample_symbols": breadth.get(
                "sample_symbols"
            ),
        }
    )
