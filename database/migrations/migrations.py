"""Backward-compatible database creation entry point."""

from database.migrations.run_migrations import run


def create_tables(db=None):
    """Create all legacy database tables."""
    if db is not None:
        raise TypeError("The legacy create_tables entry point does not accept an injected database.")
    return run()


if __name__ == "__main__":
    create_tables()
