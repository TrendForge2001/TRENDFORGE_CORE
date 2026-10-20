# R72.2 — Unified Render Service

R72.2 consolidates the existing TrendForge FastAPI Core and Streamlit webapp
into one Render web service and one deployment URL.

## Runtime

The existing Render start command remains unchanged:

```
uvicorn start:app --host 0.0.0.0 --port $PORT
```

When `TRENDFORGE_UNIFIED_UI_ENABLED=true`:

- `/` redirects to `/app/`.
- `/app/*` is the Streamlit application.
- `/health`, scanner, technical, paper, backtest, operations and all other
  existing API paths remain owned by the canonical FastAPI Core.
- Streamlit calls Core through `127.0.0.1:$PORT`; the UI therefore inherits
  the same Render environment and no Kite/admin secret is duplicated into a
  second service.

When the flag is absent or false, `start:app` remains the original Core
FastAPI application.

## Deployment safety

The old `trendforge-webapp-staging` service remains available during
validation as a rollback surface. No paid resource is created and broker
orders remain governed by the existing TrendForge safety controls.

## Dependency policy

Streamlit 1.66.0 and its missing runtime dependencies are exact-pinned in
`requirements-production.lock`. CI installs the production lock, runs
`pip check`, verifies exact versions, and imports the unified ASGI graph
before merge.
