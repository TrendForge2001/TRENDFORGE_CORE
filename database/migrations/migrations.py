"""Backward-compatible database creation entry point."""
from database.migrations.run_migrations import run
def create_tables(db=None):
    return run(db)
if __name__=="__main__": create_tables()
