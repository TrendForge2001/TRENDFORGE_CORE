"""Runs the production isolated worker with synthetic historical data only."""

from services.research_worker import main
from tests.support.research_candles import technical_service

if __name__ == "__main__":
    raise SystemExit(main(technical_service))
