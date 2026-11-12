"""Export broker-free execution examples; artificial data is not market evidence."""

import argparse
import base64
import json
import tempfile
from pathlib import Path

from core.database import initialize_database
from database.repositories.backtest_results import BacktestResultsRepository
from scanner.weekly_floor import STRATEGY_ID, VERSION
from services.execution_report import validate_result
from services.portfolio_backtest_service import PortfolioBacktestService
from services.technical_trading_service import TechnicalTradingService
from tests.support.weekly_floor_candles import NOW, ExampleMarket


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--symbols", type=int, default=1, choices=range(1, 34))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="weekly-floor-verification-") as folder:
        database = str(Path(folder) / "test.db")
        initialize_database(database)
        service = TechnicalTradingService(
            market_data=ExampleMarket(),
            repository=BacktestResultsRepository(db_path=database),
        )
        try:
            result = PortfolioBacktestService(service).run(
                symbols=[f"SYNTHETIC_{offset:02d}" for offset in range(args.symbols)],
                mode="positional",
                strategy_id=STRATEGY_ID,
                period="2y",
                now=NOW,
            )
            validate_result(result)
            reasons = {trade["exit_reason"] for trade in result["trades"]}
            assert {"YEARLY_R2", "PROTECTIVE_STOP", "END_OF_TEST"} <= reasons
            report = result["report"]
            (args.output_dir / "synthetic_execution_trades.csv").write_text(
                report["csv"], encoding="utf-8-sig"
            )
            (args.output_dir / "synthetic_execution_trades.xlsx").write_bytes(
                base64.b64decode(report["xlsx_base64"])
            )
            receipt = {
                "status": "passed",
                "strategy_id": STRATEGY_ID,
                "version": VERSION,
                "data": "ARTIFICIAL FIXTURE; not SBIN or any actual market history",
                "profitability_assessed": False,
                "simulated_positions": len(result["trades"]),
                "requested_symbols": args.symbols,
                "max_observed_positions": result["metrics"]["max_observed_positions"],
                "exit_paths_verified": sorted(reasons),
                "accounting_reconciled": True,
                "costs_and_slippage_applied": True,
                "shared_capital": result["metrics"]["initial_capital"],
                "cash_reserve": result["metrics"]["cash_reserve"],
                "csv_sha256": report["sha256"],
                "broker_orders_submitted": 0,
                "paper_ledger_writes": 0,
            }
            (args.output_dir / "verification.json").write_text(
                json.dumps(receipt, indent=2)
            )
            print(json.dumps(receipt))
        finally:
            service.repository.close()


if __name__ == "__main__":
    main()
