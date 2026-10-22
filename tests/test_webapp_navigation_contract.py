"""R72.6 five-tab technical-only frontend navigation."""
from webapp.navigation import DEFAULT_PAGE, NAVIGATION_SPEC, all_pages

EXPECTED = (
    "Watchlist", "Technical Scanner", "Backtesting",
    "Live Paper Trading", "Live Kite Session",
)
EXPECTED_PATHS = (
    "pages/watchlists.py", "pages/technical_scanner.py",
    "pages/kite_backtesting.py", "pages/paper_session.py", "pages/live_kite.py",
)

def test_navigation_groups_match_focused_workspace():
    assert tuple(NAVIGATION_SPEC) == EXPECTED

def test_navigation_registers_five_functional_pages():
    paths = tuple(page.path for page in all_pages())
    assert paths == EXPECTED_PATHS
    assert len(paths) == len(set(paths))
    assert DEFAULT_PAGE == paths[0]
    assert all(page.purpose.strip() for page in all_pages())

def test_fundamentals_and_enrichment_unreachable_from_navigation():
    pages = tuple(all_pages())
    assert all("fundamental" not in (p.title + p.path + p.purpose).lower() for p in pages)
    assert all("corporate_action" not in p.path for p in pages)
