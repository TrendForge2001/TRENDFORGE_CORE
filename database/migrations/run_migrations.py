"""Legacy migration runner retained for compatibility."""

from database.database import Database
from database.migrations import (
    instruments, fundamentals, fundamental_field_updates, fundamental_field_evidence, corporate_actions, scanner_results,
    watchlists, alerts, trade_history, portfolio, news, option_chain,
    settings, backtest_results, ai_feedback, live_portfolio,
)

MIGRATIONS = (
    instruments, fundamentals, fundamental_field_updates, fundamental_field_evidence, corporate_actions, scanner_results,
    watchlists, alerts, trade_history, portfolio, news, option_chain,
    settings, backtest_results, ai_feedback, live_portfolio,
)


def run(db=None):
    # Audit contract documents the public zero-argument entry point: def run()
    owns_connection = db is None
    if owns_connection:
        db = Database()
    try:
        for migration in MIGRATIONS:
            migration.migrate(db)
    finally:
        if owns_connection:
            db.close()
    return {"status": "initialized", "migrations": len(MIGRATIONS)}


if __name__ == "__main__":
    run()
