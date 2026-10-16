"""Named watchlist management dashboard."""
from __future__ import annotations

from urllib.parse import quote

import pandas as pd
import streamlit as st

from webapp.api_client import ApiError
from webapp.runtime import admin_key_configured, api_client
from webapp.ui import info_note, page_header, render_api_error


page_header(
    "Watchlists",
    "Maintain named stock lists with priority, notes, target/stop-loss context, scanner score, and latest signal metadata.",
    kicker="Operate",
)

if not admin_key_configured():
    info_note(
        "Production watchlist changes require the TrendForge admin key. "
        "Read-only watchlist views remain available.",
        danger=True,
    )

client = api_client(timeout=60)

try:
    summary = client.get_json("/watchlists")
except ApiError as exc:
    render_api_error(exc, title="Watchlists unavailable")
    st.stop()

watchlists = summary.get("watchlists")
watchlists = watchlists if isinstance(watchlists, list) else []
names = [
    str(item.get("name"))
    for item in watchlists
    if item.get("name")
]

m1, m2, m3 = st.columns(3)
with m1:
    st.metric(
        "Watchlists",
        int(summary.get("watchlist_count") or 0),
    )
with m2:
    st.metric(
        "Unique symbols",
        int(summary.get("symbol_count") or 0),
    )
with m3:
    st.metric(
        "Entries",
        int(summary.get("entry_count") or 0),
    )

if watchlists:
    st.dataframe(
        pd.DataFrame(watchlists),
        use_container_width=True,
        hide_index=True,
    )

selected_name = st.selectbox(
    "Selected watchlist",
    options=names or ["Swing"],
    index=0,
)

encoded_name = quote(selected_name, safe="")
try:
    detail = client.get_json(
        f"/watchlists/{encoded_name}"
    )
except ApiError as exc:
    render_api_error(
        exc,
        title="Selected watchlist unavailable",
    )
    detail = {
        "name": selected_name,
        "entries": [],
        "count": 0,
    }

entries = detail.get("entries")
entries = entries if isinstance(entries, list) else []

st.subheader(selected_name)
if entries:
    frame = pd.DataFrame(entries)
    st.dataframe(
        frame,
        use_container_width=True,
        hide_index=True,
    )
    st.download_button(
        "Download watchlist CSV",
        data=frame.to_csv(index=False).encode("utf-8"),
        file_name=(
            "trendforge_"
            + selected_name.replace(" ", "_").lower()
            + "_watchlist.csv"
        ),
        mime="text/csv",
    )
else:
    st.info("This watchlist has no persisted entries.")

st.divider()
st.subheader("Add or upsert symbol")

with st.form("watchlist_add_form"):
    a, b, c = st.columns(3)
    with a:
        target_watchlist = st.text_input(
            "Watchlist name",
            value=selected_name,
        )
    with b:
        symbol = st.text_input("Symbol")
    with c:
        priority = st.selectbox(
            "Priority",
            [1, 2, 3, 4, 5],
            index=2,
        )

    d, e = st.columns(2)
    with d:
        target = st.number_input(
            "Target",
            min_value=0.0,
            value=0.0,
            step=1.0,
        )
    with e:
        stoploss = st.number_input(
            "Stop-loss",
            min_value=0.0,
            value=0.0,
            step=1.0,
        )

    notes = st.text_area(
        "Notes",
        max_chars=500,
    )
    add_submitted = st.form_submit_button(
        "Save symbol",
        type="primary",
        use_container_width=True,
    )

if add_submitted:
    if not admin_key_configured():
        st.error(
            "Configure the production admin key before changing watchlists."
        )
    else:
        path_name = quote(target_watchlist.strip(), safe="")
        try:
            payload = {
                "symbol": symbol.strip().upper(),
                "priority": int(priority),
                "notes": notes,
                "target": (
                    float(target)
                    if float(target) > 0
                    else None
                ),
                "stoploss": (
                    float(stoploss)
                    if float(stoploss) > 0
                    else None
                ),
            }
            client.post_json(
                f"/watchlists/{path_name}/symbols",
                payload,
            )
            st.success(
                f"{symbol.strip().upper()} saved to {target_watchlist.strip()}."
            )
            st.rerun()
        except ApiError as exc:
            render_api_error(
                exc,
                title="Watchlist save failed",
            )

if entries:
    st.divider()
    st.subheader("Edit selected symbol")

    symbols = [
        str(entry.get("symbol"))
        for entry in entries
        if entry.get("symbol")
    ]
    edit_symbol = st.selectbox(
        "Symbol to edit",
        symbols,
        key="watchlist_edit_symbol",
    )
    current = next(
        (
            entry
            for entry in entries
            if str(entry.get("symbol")) == edit_symbol
        ),
        {},
    )

    with st.form("watchlist_edit_form"):
        e1, e2, e3 = st.columns(3)
        with e1:
            edit_priority = st.selectbox(
                "Priority",
                [1, 2, 3, 4, 5],
                index=max(
                    0,
                    min(
                        4,
                        int(current.get("priority") or 1) - 1,
                    ),
                ),
                key="edit_priority",
            )
        with e2:
            edit_target = st.number_input(
                "Target",
                min_value=0.0,
                value=float(current.get("target") or 0.0),
                step=1.0,
                key="edit_target",
            )
        with e3:
            edit_stoploss = st.number_input(
                "Stop-loss",
                min_value=0.0,
                value=float(current.get("stoploss") or 0.0),
                step=1.0,
                key="edit_stoploss",
            )

        edit_notes = st.text_area(
            "Notes",
            value=str(current.get("notes") or ""),
            max_chars=500,
            key="edit_notes",
        )
        update_submitted = st.form_submit_button(
            "Update symbol",
            use_container_width=True,
        )

    if update_submitted:
        if not admin_key_configured():
            st.error(
                "Configure the production admin key before changing watchlists."
            )
        else:
            try:
                client.put_json(
                    (
                        f"/watchlists/{encoded_name}/symbols/"
                        f"{quote(edit_symbol, safe='')}"
                    ),
                    {
                        "priority": int(edit_priority),
                        "notes": edit_notes,
                        "target": float(edit_target),
                        "stoploss": float(edit_stoploss),
                    },
                )
                st.success(f"{edit_symbol} updated.")
                st.rerun()
            except ApiError as exc:
                render_api_error(
                    exc,
                    title="Watchlist update failed",
                )

    r1, r2 = st.columns(2)
    with r1:
        remove = st.button(
            f"Remove {edit_symbol}",
            use_container_width=True,
        )
    with r2:
        confirm_delete = st.toggle(
            "Confirm delete entire watchlist",
            value=False,
        )
        delete_list = st.button(
            f"Delete {selected_name}",
            disabled=not confirm_delete,
            use_container_width=True,
        )

    if remove:
        if not admin_key_configured():
            st.error(
                "Configure the production admin key before changing watchlists."
            )
        else:
            try:
                client.delete_json(
                    (
                        f"/watchlists/{encoded_name}/symbols/"
                        f"{quote(edit_symbol, safe='')}"
                    )
                )
                st.success(f"{edit_symbol} removed.")
                st.rerun()
            except ApiError as exc:
                render_api_error(
                    exc,
                    title="Symbol removal failed",
                )

    if delete_list:
        if not admin_key_configured():
            st.error(
                "Configure the production admin key before changing watchlists."
            )
        else:
            try:
                client.delete_json(
                    f"/watchlists/{encoded_name}"
                )
                st.success(
                    f"Watchlist {selected_name} deleted."
                )
                st.rerun()
            except ApiError as exc:
                render_api_error(
                    exc,
                    title="Watchlist deletion failed",
                )
