"""A persistent stock-list choice and optional member browser on every page."""

from urllib.parse import quote

import pandas as pd
import streamlit as st

from config.stock_lists import STOCK_LISTS, resolve_stock_list, stock_list_label
from webapp.api_client import ApiError

SELECTED = "tf_selected_stock_list"
ROOT_MANAGED = "tf_shared_stock_lists_root"


def selected_stock_list(default="NIFTY 50"):
    value = st.session_state.get(SELECTED, default)
    try:
        return resolve_stock_list(value)[0]
    except ValueError:
        return default


def remember_stock_list(widget_key):
    st.session_state[SELECTED] = st.session_state[widget_key]


def stock_list_picker(*, key, default="NIFTY 50"):
    value = selected_stock_list(default)
    st.session_state[key] = value
    return st.selectbox(
        "Stock list",
        list(STOCK_LISTS),
        format_func=stock_list_label,
        key=key,
        on_change=remember_stock_list,
        args=(key,),
    )


@st.cache_data(ttl=600, show_spinner=False)
def load_members(backend_url, name):
    from webapp.api_client import TrendForgeApi
    from webapp.runtime import admin_key

    return TrendForgeApi(
        backend_url, admin_key=admin_key(), default_timeout=35
    ).get_json(f"/workspace/watchlist/{quote(name, safe='')}/constituents", timeout=35)


def use_stock(symbol):
    st.session_state["tf_selected_stock_symbol"] = symbol
    st.session_state["tf_paper_order_symbol"] = symbol
    st.session_state["tf_live_preview_symbol"] = symbol


def render_shared_stock_lists(backend_url):
    st.session_state[ROOT_MANAGED] = True
    from webapp.institutional_selector import render_selector

    with st.container(key="tf_global_toolbar"):
        list_column, options_column = st.columns([6, 1], vertical_alignment="bottom")
        with list_column:
            name = stock_list_picker(key="tf_global_stock_list")
        with options_column, st.popover("List filters", width="stretch"):
            render_selector()
            browse = st.toggle("Browse list members", key="tf_browse_stock_list")
    if browse:
        snapshots = st.session_state.setdefault("tf_catalog_member_snapshots", {})
        cache_key = (backend_url, name)
        if st.button("Load / refresh members", key="tf_load_catalog_members"):
            try:
                load_members.clear(backend_url, name)
                snapshots[cache_key] = load_members(backend_url, name)
            except ApiError as exc:
                st.info(str(exc))
        payload = snapshots.get(cache_key)
        if payload is None:
            st.caption("Load the selected list to browse its members.")
            return
        rows = payload.get("rows") or []
        from webapp.institutional_selector import filter_symbols
        from webapp.runtime import api_client

        try:
            allowed = set(filter_symbols(api_client(), [r["symbol"] for r in rows]))
            rows = [r for r in rows if r["symbol"] in allowed]
        except ApiError as exc:
            st.info(str(exc))
            return
        if not rows:
            st.info("The selected list has no available members.")
            return
        search = st.text_input("Search selected list", key="tf_catalog_search")
        frame = pd.DataFrame(rows)
        frame["sector"] = frame.get(
            "sector", pd.Series(index=frame.index, dtype=str)
        ).fillna("Unclassified")
        if search.strip():
            frame = frame.loc[
                frame["symbol"].str.contains(search.strip(), case=False, regex=False)
                | frame["stock_name"].str.contains(
                    search.strip(), case=False, regex=False
                )
            ]
        if resolve_stock_list(name)[1].grouped:
            frame = frame.sort_values(["sector", "stock_name"])
        st.dataframe(
            frame[["sector", "symbol", "stock_name"]].rename(
                columns={
                    "sector": "Sector / market",
                    "symbol": "Symbol",
                    "stock_name": "Name",
                }
            ),
            hide_index=True,
            width="stretch",
        )
        if payload.get("source_warning"):
            st.caption(payload["source_warning"])
        if payload.get("source"):
            st.caption("Membership source: " + payload["source"])
        if payload.get("kind") == "index":
            st.caption(
                "Index references for browsing. Choose a stock constituent "
                "list for equity scans and backtests."
            )
        elif not frame.empty:
            symbols = frame["symbol"].tolist()
            widget = "tf_catalog_stock"
            if st.session_state.get(widget) not in symbols:
                st.session_state.pop(widget, None)
            symbol = st.selectbox("Stock from selected list", symbols, key=widget)
            st.button(
                "Use this stock",
                key="tf_use_catalog_stock",
                on_click=use_stock,
                args=(symbol,),
            )
