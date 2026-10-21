"""Consolidated TrendForge workspace navigation with one active view at a time.

Using a segmented tab bar (rather than rendering all tabs simultaneously)
avoids running hidden pages that can call st.stop(), perform API requests, or
create duplicate Streamlit widget keys.
"""
from __future__ import annotations

from pathlib import Path
import runpy

import streamlit as st

PAGE_ROOT = Path(__file__).resolve().parent / "pages"

WORKSPACE_TABS: dict[str, tuple[tuple[str, str], ...]] = {
    "portfolio": (
        ("Broker Holdings", "portfolio.py"),
        ("Paper Portfolio", "paper_portfolio.py"),
    ),
    "technicals": (
        ("Scanner & Backtesting", "technicals.py"),
        ("Scanner Results", "scanner_results.py"),
    ),
}


def render_workspace(workspace: str) -> None:
    tabs = WORKSPACE_TABS[workspace]
    labels = [label for label, _ in tabs]
    selection = st.segmented_control(
        "Workspace tabs",
        options=labels,
        default=labels[0],
        key=f"tf_workspace_tab_{workspace}",
        selection_mode="single",
        label_visibility="collapsed",
    )
    selected = selection if selection in labels else labels[0]
    filename = dict(tabs)[selected]
    runpy.run_path(str(PAGE_ROOT / filename), run_name=f"trendforge_{workspace}_{filename[:-3]}")
