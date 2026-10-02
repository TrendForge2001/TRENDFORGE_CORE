# TrendForge Core Runtime Validation Status

## R49 scanner execution boundary checkpoint

Batch 27 hardens scanner health reporting so engine degradation is visible at the application boundary.

## Health contract

- Application health now includes a database readiness section.
- A missing database is reported as `not_initialized`, rather than being silently treated as ready.
- Database readiness does not require Kite credentials or an external market-data request.

## Database lifecycle

- Database initialization is exposed through core.database.initialize_database().
- The target path can be supplied explicitly or through DATABASE_PATH.
- Migration modules remain the canonical schema builders.
- Initialization is explicit and is executed during application startup through the FastAPI lifespan.\n- Importing `start.app` still does not initialize the database.\n- A startup initialization failure prevents the application from entering its ready lifespan.
- A temporary-path lifecycle test verifies that migrations create database tables.

## Test-contract hardening

- Provider factory tests explicitly import `RuntimeConfig`.
- API health fixtures now provide the expected configuration payload.
- API lifecycle tests inject a deterministic database initializer where database state is not under test.

## Scanner execution boundary

- Scanner service health now propagates degraded/unavailable orchestrator state instead of always reporting healthy.
- The canonical scanner pipeline has one explicit `EngineOrchestrator` import boundary.
- Scan execution errors remain surfaced as structured per-symbol errors by `analyze_many` and as API `422` responses for single scans.

## Runtime evidence still required

1. Install requirements.txt from scratch.
2. Run the complete pytest suite.
3. Import start.app successfully.
4. Start Uvicorn with the Render command.
5. Verify /health on the deployed service.
6. Configure and validate only the external credentials/providers actually enabled.
7. Run core.database.initialize_database() against the intended persistent database path and verify migrations.

## Current conclusion

**Database lifecycle boundary: implemented. Runtime execution evidence: pending.**

The branch remains an integration candidate, not a production deployment declaration.
