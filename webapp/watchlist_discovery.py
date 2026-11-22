"""List discovery follows the owner's compact mobile watchlist reference."""

import streamlit as st

from config.stock_lists import STOCK_LISTS, stock_list_label
from webapp.stock_lists import SELECTED, selected_stock_list


def open_list(name):
    st.session_state[SELECTED] = name
    recent = st.session_state.get("tf_recent_stock_lists", [])
    st.session_state["tf_recent_stock_lists"] = [
        name,
        *[n for n in recent if n != name],
    ][:8]
    st.session_state["tf_watchlist_open"] = True


def render_discovery():
    if st.session_state.get("tf_watchlist_open"):
        if st.button("← All watchlists", key="tf_watchlist_back"):
            st.session_state["tf_watchlist_open"] = False
            st.rerun()
        return True
    current = selected_stock_list()
    recent = list(
        dict.fromkeys([current, *st.session_state.get("tf_recent_stock_lists", [])])
    )
    tabs = st.tabs(
        [f"My watchlists · {len(recent)}", f"Discover · {len(STOCK_LISTS)}"],
        key="watchlist_discovery",
        on_change="rerun",
    )
    for index, tab in enumerate(tabs):
        with tab:
            if not tab.open:
                continue
            search = st.text_input(
                "Search watchlists",
                placeholder="Index, sector or F&O list",
                key=f"tf_watchlist_discover_search_{index}",
            )
            names = recent if index == 0 else list(STOCK_LISTS)
            names = [
                name
                for name in names
                if name in STOCK_LISTS
                and search.casefold() in stock_list_label(name).casefold()
            ]
            if index == 0:
                st.caption("Your selected and recently opened lists in this session.")
            previous_group = None
            for name in names:
                group = (
                    "F&O STOCKS" if name.startswith("NSE F&O") else "INDICES & SECTORS"
                )
                if group != previous_group:
                    st.caption(group)
                    previous_group = group
                with st.container(border=False, key=f"tf_watchlist_row_{index}_{name}"):
                    row, action = st.columns([8, 1], vertical_alignment="center")
                    row.markdown("▱  **" + stock_list_label(name) + "**")
                    action.button(
                        "→",
                        key=f"tf_open_list_{index}_{name}",
                        help="Open this watchlist",
                        on_click=open_list,
                        args=(name,),
                        width="stretch",
                    )
                    st.divider()
            if not names:
                st.info("No watchlists match this search.")
    return False
