"""Navigation contract tests for the TrendForge Streamlit shell."""
from webapp.navigation import DEFAULT_PAGE, NAVIGATION_SPEC, all_pages


def test_navigation_groups_are_operator_workflows():
    assert tuple(NAVIGATION_SPEC) == (
        "Home",
        "Trade",
        "Markets",
        "Research",
        "Portfolio",
        "Operations",
    )


def test_navigation_registers_all_pages_once():
    pages = all_pages()
    paths = [page.path for page in pages]

    assert len(pages) == 22
    assert len(paths) == len(set(paths))
    assert DEFAULT_PAGE in paths
    assert all(path.startswith("pages/") and path.endswith(".py") for path in paths)


def test_navigation_has_required_trading_surfaces():
    titles = {page.title for page in all_pages()}

    assert {
        "Command Center",
        "NIFTY 500 Scanner",
        "Technical Lab",
        "Paper Trading",
        "Weekend Research",
        "Backtesting",
        "Portfolio",
        "P&L Statement",
        "Performance",
        "System & Access",
    }.issubset(titles)


def test_every_page_has_operator_purpose():
    assert all(page.purpose.strip() for page in all_pages())
