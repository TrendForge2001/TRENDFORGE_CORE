from __future__ import annotations

import ast
from pathlib import Path


def test_all_webapp_python_files_parse():
    root = Path(__file__).resolve().parents[1]
    files = sorted((root / "webapp").rglob("*.py"))

    assert files
    for path in files:
        ast.parse(
            path.read_text(encoding="utf-8"),
            filename=str(path),
        )


def test_initial_webapp_pages_exist():
    root = Path(__file__).resolve().parents[1]
    pages = root / "webapp" / "pages"

    expected = {
        "dashboard.py",
        "scan_history.py",
        "notification_center.py",
        "scanner.py",
        "paper_trading.py",
        "portfolio.py",
        "pnl.py",
        "performance.py",
        "watchlists.py",
        "market_breadth.py",
        "market_regime.py",
        "backtesting.py",
        "news_intelligence.py",
        "corporate_actions.py",
        "big_shark.py",
        "sector_strength.py",
        "fundamentals.py",
        "system.py",
    }

    assert expected.issubset(
        {path.name for path in pages.glob("*.py")}
    )
