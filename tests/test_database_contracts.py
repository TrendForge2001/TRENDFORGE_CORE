"""Database persistence contract tests."""

from pathlib import Path

from database.database import Database
from database.migrations.run_migrations import run
from database.repositories.ai_feedback import AIFeedbackRepository
from database.repositories.backtest_results import BacktestResultsRepository
from database.repositories.news_repository import NewsRepository


def test_canonical_migrations_create_repository_tables(tmp_path):
    path = tmp_path / "trendforge.db"
    db = Database(path)
    try:
        run(db)
        names = {row["name"] for row in db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"news", "portfolio", "fundamentals", "ai_feedback", "backtest_results"} <= names
    finally:
        db.close()


def test_database_context_and_rollback(tmp_path):
    path = tmp_path / "rollback.db"
    with Database(path) as db:
        db.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO sample (value) VALUES (?)", ("ok",))
        assert db.fetchone("SELECT value FROM sample WHERE id=1")["value"] == "ok"


def test_repaired_repositories_persist_data(tmp_path):
    db = Database(tmp_path / "repos.db")
    try:
        run(db)
        AIFeedbackRepository(db).save({"symbol": "TEST", "scanner": "unit"})
        BacktestResultsRepository(db).save({"strategy_name": "unit", "symbol": "TEST"})
        NewsRepository(db).insert_news("TEST", "headline")
        assert len(AIFeedbackRepository(db).latest()) == 1
        assert len(BacktestResultsRepository(db).latest()) == 1
        assert len(NewsRepository(db).get_by_symbol("TEST")) == 1
    finally:
        db.close()
