"""Run canonical TrendForge SQLite migrations."""
from database.database import Database
from database.migrations import ai_feedback, alerts, backtest_results, corporate_actions, fundamentals, instruments, live_portfolio, news, option_chain, portfolio, scanner_results, settings, trade_history, watchlists
MIGRATIONS=(instruments,fundamentals,corporate_actions,scanner_results,watchlists,alerts,trade_history,portfolio,live_portfolio,news,option_chain,settings,backtest_results,ai_feedback)
def run(db=None):
    owns_db=db is None
    db=db or Database()
    try:
        for migration in MIGRATIONS: migration.migrate(db)
        return db
    finally:
        if owns_db: db.close()
if __name__=="__main__":
    run(); print("TrendForge database initialized successfully.")
