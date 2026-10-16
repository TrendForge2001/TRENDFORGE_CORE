# R68.0 Webapp Foundation

R68.0 starts the TrendForge presentation layer without changing the canonical engine or the current Render backend service.

## Architecture

Browser -> Streamlit webapp -> TrendForgeApi -> canonical FastAPI api/app.py -> scanner/providers/database/paper runtime.

The frontend is deliberately a separate process. It does not import scanner engines, provider implementations, or the SQLite database directly. Every operational action crosses the existing HTTP contract.

## Initial page set

1. Command Center
   - GET /health
   - GET /paper/readiness
   - GET /paper/auto-entry/readiness
   - GET /observability/scan-runtime

2. NIFTY 500 Scanner
   - POST /scan/universe/nifty500
   - bounded 25/50/100/500 controls
   - optional explicit paper-auto-entry request
   - scale-gate and ranked-result presentation

3. Paper Trading
   - GET /paper
   - GET /paper/readiness
   - POST /paper/open
   - POST /paper/kill-switch
   - POST /paper/monitor/tick

4. Fundamentals
   - GET /fundamentals
   - symbol inspection/update
   - CSV/XLSX templates
   - curated file upload

5. System
   - API URL and admin key held in Streamlit session state
   - production/core/runtime diagnostics

## Safety rules

- No live broker-order endpoint is added.
- R67.2 paper auto-entry remains opt-in and paper-only.
- The admin key is never hard-coded.
- The frontend does not read the backend SQLite file directly.
- Root render.yaml remains unchanged in this batch.
- The existing FastAPI health check and deployment contract remain unchanged.

## Design direction

The webapp uses a dark, dense operations-console style rather than a marketing dashboard. Primary workflows are organized as Monitor, Operate, and Data. The visual hierarchy prioritizes system health, scan outcome, safety controls, and ranked evidence.

## Next webapp batch

R68.1 should add page-critical response-shape tests, scan continuation/resume controls, scan-history views, and the first deployment manifest for a separate frontend service. Portfolio, P&L analytics, backtesting, market breadth, and watchlists should be added only after their canonical HTTP contracts are available.
