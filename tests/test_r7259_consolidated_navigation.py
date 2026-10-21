"""R72.5.9 combined workspace navigation contracts."""
from pathlib import Path

from webapp.navigation import NAVIGATION_SPEC, all_pages
from webapp.workspace_tabs import WORKSPACE_TABS


def test_combined_workspace_navigation_has_single_entry_per_group():
    assert [p.path for p in NAVIGATION_SPEC["Portfolio"]] == [
        "pages/portfolio_workspace.py"
    ]
    assert [p.path for p in NAVIGATION_SPEC["Technicals"]] == [
        "pages/technical_workspace.py"
    ]
    paths = [page.path for page in all_pages()]
    assert len(paths) == len(set(paths))


def test_combined_tabs_reuse_existing_functional_pages():
    root = Path("webapp/pages")
    assert [label for label, _ in WORKSPACE_TABS["portfolio"]] == [
        "Broker Holdings", "Paper Portfolio"
    ]
    assert [label for label, _ in WORKSPACE_TABS["technicals"]] == [
        "Scanner & Backtesting", "Scanner Results"
    ]
    for tabs in WORKSPACE_TABS.values():
        for _, filename in tabs:
            assert (root / filename).is_file()


def test_hidden_tabs_are_not_executed_simultaneously():
    source = Path("webapp/workspace_tabs.py").read_text(encoding="utf-8")
    assert "st.segmented_control(" in source
    assert "runpy.run_path(" in source
    assert "filename = dict(tabs)[selected]" in source
