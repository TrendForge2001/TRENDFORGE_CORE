from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_database_manager_exposes_explicit_close_boundary():
    text = _text("database/database.py")
    assert "check_same_thread=False" in text
    assert "def close(self):" in text
    assert "self.conn.close()" in text


def test_schema_initialization_is_explicit_and_separate_from_repository_construction():
    init_text = _text("database/init_db.py")
    migration_text = _text("database/migrations/run_migrations.py")
    repository_text = _text("database/repositories/scanner_repository.py")

    assert "def create_tables()" in init_text
    assert "def run()" in migration_text
    assert "self.db = Database()" in repository_text
    assert "create_tables(" not in repository_text
    assert "run_migrations" not in repository_text


def test_repository_schema_dependencies_are_declared_in_migrations():
    migration_text = _text("database/migrations/run_migrations.py")
    repository_text = _text("database/repositories/scanner_repository.py")

    assert "scanner_results" in migration_text
    assert "INSERT INTO scanner_results" in repository_text


def test_database_path_is_centralized_in_database_manager():
    text = _text("database/database.py")
    assert "target = db_path or os.getenv(\"DATABASE_PATH\") or DEFAULT_DATABASE_PATH" in text
    assert "self.db_path = target" in text


def test_database_manager_honors_database_path_environment(monkeypatch, tmp_path):
    target = tmp_path / "configured.db"
    monkeypatch.setenv("DATABASE_PATH", str(target))

    from database.database import Database

    db = Database()
    try:
        assert db.db_path == str(target)
        assert target.exists()
    finally:
        db.close()


def test_explicit_database_path_overrides_environment(monkeypatch, tmp_path):
    configured = tmp_path / "configured.db"
    explicit = tmp_path / "explicit.db"
    monkeypatch.setenv("DATABASE_PATH", str(configured))

    from database.database import Database

    db = Database(str(explicit))
    try:
        assert db.db_path == str(explicit)
        assert explicit.exists()
        assert not configured.exists()
    finally:
        db.close()
