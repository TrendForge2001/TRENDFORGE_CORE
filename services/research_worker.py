"""One isolated, read-only research job. Never construct paper/live services."""

import argparse
import logging
import os
import signal
import sys


def technical_service(database):
    from database.repositories.backtest_results import BacktestResultsRepository
    from providers.provider_factory import ProviderFactory
    from services.technical_trading_service import TechnicalTradingService

    return TechnicalTradingService(
        market_data=ProviderFactory(max_workers=2).kite_market_data(),
        repository=BacktestResultsRepository(db_path=database),
    )


def main(factory=technical_service):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--parent-pid", required=True, type=int)
    args = parser.parse_args()
    # No credentials or provider exception strings are emitted from the child.
    logging.disable(logging.CRITICAL)
    if sys.platform == "linux":
        import ctypes

        os.nice(10)
        ctypes.CDLL(None).prctl(1, signal.SIGTERM)
        # PID 1 can legitimately be the web server inside a container.
        # Compare the explicit owner, rather than treating every PID 1 as orphaned.
        if os.getppid() != args.parent_pid:
            return 1

    from database.database import Database
    from database.repositories.research_batches import ResearchBatchRepository
    from services.research_execution import execute_research
    from services.research_failure import fail_research
    from services.research_storage import complete_batch, report_archive

    technical = None
    database = Database(args.database)
    repository = ResearchBatchRepository(database)
    try:
        technical = factory(args.database)
        batch = repository.get(args.batch_id)
        if batch is None or batch["status"] != "running":
            return 1

        def progress(phase, completed, total=None):
            repository.progress(args.batch_id, phase, completed, total)

        report = execute_research(
            technical, args.batch_id, batch["kind"], batch["request"], progress
        )
        saved = complete_batch(
            repository, report_archive(args.database), args.batch_id, report
        )
        return 0 if saved else 1
    except Exception as error:
        fail_research(repository, args.batch_id, error)
        return 1
    finally:
        if technical is not None:
            technical.repository.close()
        database.close()


if __name__ == "__main__":
    if sys.platform == "linux":
        import resource

        # Bound virtual memory before importing numerical libraries in the child.
        cap = int(os.getenv("TRENDFORGE_RESEARCH_ADDRESS_SPACE_MIB", "2048")) * 1024**2
        if cap <= 0:
            raise ValueError("Research address-space limit must be positive")
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        cap = min(
            value for value in (cap, soft, hard) if value != resource.RLIM_INFINITY
        )
        resource.setrlimit(resource.RLIMIT_AS, (cap, cap))

    raise SystemExit(main())
