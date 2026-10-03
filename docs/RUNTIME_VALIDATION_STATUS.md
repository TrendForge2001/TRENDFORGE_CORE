# TrendForge Core Runtime Validation Status

## R51 NSE startup-boundary checkpoint

Batch 29.1 repairs a regression in the NSE provider startup boundary.

## NSE provider startup boundary

- Constructing NSEProvider no longer performs an NSE network request.
- NSE session initialization is deferred until the first actual request.
- _ensure_session() owns the lazy session initialization boundary.
- The request path no longer contains embedded source escape text.
- Regression tests parse the provider source and verify that __init__ does not call _initialize_session() while _ensure_session() does.

## Health and database contracts

- Application health includes database readiness.
- A missing database is reported as not_initialized.
- Database initialization is explicit and runs during FastAPI lifespan startup.
- Importing the application does not initialize the default database.
- Database readiness does not require Kite credentials or an external market-data request.

## Scanner execution boundary

- Scanner service health propagates degraded/unavailable orchestrator state.
- The canonical scanner pipeline has one explicit EngineOrchestrator import boundary.
- Scan execution errors remain structured by symbol and invalid API scanner return types are rejected before serialization.

## Runtime evidence still required

1. Install requirements.txt from scratch.
2. Run the complete pytest suite.
3. Import start.app successfully.
4. Start Uvicorn with the Render command.
5. Verify /health on the deployed service.
6. Configure and validate only the external credentials/providers actually enabled.
7. Run core.database.initialize_database() against the intended persistent database path and verify migrations.

## Current conclusion

**NSE startup boundary: repaired and regression-covered. Runtime execution evidence: pending.**

The branch remains an integration candidate, not a production deployment declaration.
