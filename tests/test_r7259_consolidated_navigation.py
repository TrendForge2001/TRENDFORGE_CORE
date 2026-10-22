"""R72.6 replaces the older nested workspace navigation without deleting legacy modules."""
from pathlib import Path
from webapp.navigation import NAVIGATION_SPEC, all_pages

def test_five_main_sections_are_one_page_each():
    assert len(NAVIGATION_SPEC) == 5
    assert all(len(group) == 1 for group in NAVIGATION_SPEC.values())
    assert len(all_pages()) == 5

def test_reachable_pages_exist():
    root = Path("webapp")
    assert all((root / page.path).is_file() for page in all_pages())
