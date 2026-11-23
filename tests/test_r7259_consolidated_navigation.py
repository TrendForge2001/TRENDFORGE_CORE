"""R72.6 replaces the older nested workspace navigation without deleting legacy modules."""

from pathlib import Path

from webapp.navigation import NAVIGATION_SPEC, all_pages


def test_five_main_sections_are_one_page_each():
    assert len(NAVIGATION_SPEC) == 3
    assert tuple(map(len, NAVIGATION_SPEC.values())) == (5, 1, 1)
    assert len(all_pages()) == 7


def test_reachable_pages_exist():
    root = Path("webapp")
    assert all((root / page.path).is_file() for page in all_pages())
