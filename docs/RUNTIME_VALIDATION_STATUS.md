# TrendForge Core Runtime Validation Status

## R53 market-data health propagation checkpoint

Batch 29.2 repaired scanner-to-application health propagation. Batch 29.3 extends the same contract through the market-data adapter and routed-provider layers.

## Application health contract

- ApplicationFactory no longer hard-codes top-level healthy status.
- ScannerService health is evaluated before the top-level application status is returned.
- MarketDataAdapter now preserves degraded/unavailable provider health instead of always reporting configured.
- RoutedMarketDataProvider aggregates child-provider health so degraded provider state reaches the adapter and application health boundaries.
- A degraded or unavailable scanner now propagates a degraded application health status.
- The scanner health payload remains included unchanged for diagnosis.

## NSE startup boundary

- Constructing NSEProvider no longer performs an NSE network request.
- NSE session initialization is deferred until the first actual request.
- The request path no longer contains embedded source escape text.

## Database and startup contracts

- Application health includes database readiness.
- Database initialization is explicit and runs during FastAPI lifespan startup.
- Importing the application does not initialize the default database.
- Startup initialization failures prevent the application from entering its ready lifespan.

## Runtime evidence still required

1. Install requirements.txt from scratch.
2. Run the complete pytest suite.
3. Import start.app successfully.
4. Start Uvicorn with the Render command.
5. Verify /health on the deployed service.
6. Configure and validate only the external credentials/providers actually enabled.
7. Run core.database.initialize_database() against the intended persistent database path and verify migrations.

## Current conclusion

**Application health propagation across scanner and market-data layers: implemented and regression-covered. Runtime execution evidence: pending.**

The branch remains an integration candidate, not a production deployment declaration.
