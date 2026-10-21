"""Navigation contract tests for the focused TrendForge trading shell."""
from webapp.navigation import DEFAULT_PAGE, NAVIGATION_SPEC, all_pages


def test_navigation_groups_match_focused_workspace():
    assert tuple(NAVIGATION_SPEC) == (
        "Watchlist",
        "Portfolio",
        "Fundamentals",
        "Technicals",
        "Corporate Actions",
    )


def test_navigation_registers_focused_pages_once():
    pages = all_pages()
    paths = [page.path for page in pages]

    assert len(pages) == 5
    assert len(paths) == len(set(paths))
    assert DEFAULT_PAGE == "pages/watchlists.py"
    assert DEFAULT_PAGE in paths
    assert all(
        path.startswith("pages/") and path.endswith(".py")
        for path in paths
    )


def test_navigation_has_required_trading_surfaces():
    titles = {page.title for page in all_pages()}

    assert titles == {
        "NIFTY 100 Watchlist",
        "Portfolio",
        "Fundamentals",
        "Technicals",
        "Corporate Actions",
    }


def test_every_page_has_operator_purpose():
    assert all(page.purpose.strip() for page in all_pages())
