"""Legacy migration runner retained for compatibility."""

from database.database import Database
from database.migrations import (
    instruments, fundamentals, corporate_actions, scanner_results,
    watchlists, alerts, trade_history, portfolio, news, option_chain,
    settings, backtest_results, ai_feedback,
)

MIGRATIONS = (
    instruments, fundamentals, corporate_actions, scanner_results,
    watchlists, alerts, trade_history, portfolio, news, option_chain,
    settings, backtest_results, ai_feedback,
)


def run():
    db = Database()
    try:
        for migration in MIGRATIONS:
            migration.migrate(db)
    finally:
        db.close()
    return {"status": "initialized", "migrations": len(MIGRATIONS)}


if __name__ == "__main__":
    run()
