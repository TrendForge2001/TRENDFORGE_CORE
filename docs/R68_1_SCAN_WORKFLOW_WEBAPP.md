# R68.1 Scan Workflow Webapp

R68.1 turns the R68.0 page shell into an operational scan workflow while keeping all scanner, continuation and persistence authority in the canonical FastAPI backend.

## Scope

### Scanner result UX

The NIFTY 500 Scanner now presents:

- outcome, completion, error, missing and eligible counters;
- scan-budget utilization;
- accounted-progress bar;
- signal filtering;
- eligible-only filtering;
- CSV export of ranked candidates;
- provider-routing counts when present.

### Continuation resume

When a partial scan returns a continuation token, the active Streamlit session retains the raw token and inspects its state through:

`GET /observability/scan-continuations/{token}`

A resumable pending token can be executed from the Scanner page through:

`POST /scan/universe/nifty500?run_id=<new>&continuation_token=<token>`

The request body is empty. This deliberately preserves the R66.8 inheritance contract for signal-defining inputs and any omitted operational controls.

Every resume uses a new immutable run ID. Continuation children remain ineligible for R67.2 paper auto-entry.

### Scan History

The new Scan History page uses existing read-only endpoints:

- `GET /observability/scan-runs`
- `GET /observability/scan-runs/{run_id}`
- `GET /observability/scan-lineages/{run_id}`
- `GET /observability/scan-lineages/{run_id}/integrity`
- `GET /observability/scan-continuations/{token}`

It exposes recent audit rows, CSV export, lineage completion, attempt/committed run evidence and R66.11 integrity findings.

Raw continuation tokens are still not copied into immutable audit metadata.

## Frontend access boundary

A deployed webapp can hold `TRENDFORGE_ADMIN_API_KEY` server-side. Therefore R68.1 adds a separate Streamlit access secret:

`TRENDFORGE_WEBAPP_ACCESS_KEY`

When configured, navigation is not rendered until the session supplies the correct access key. Comparison uses `secrets.compare_digest`. The System page can revoke the current session.

Local development remains usable without the access key.

## Render blueprint

R68.1 adds:

`deploy/render-webapp.yaml`

This is intentionally separate from the active backend `render.yaml`.

The frontend Blueprint:

- installs only `webapp/requirements.txt`;
- runs `python -m streamlit run webapp/app.py`;
- binds to Render's `$PORT`;
- uses `/_stcore/health`;
- requires separately configured API URL, backend admin key and webapp access key.

## Backend compatibility

R68.1 does not modify:

- scanner rules, indicators or scoring;
- provider routing;
- scan time budgets;
- continuation lifecycle;
- scan audit persistence;
- paper trading;
- paper auto-entry;
- root backend Render deployment.

## Remaining boundary

Render Free still uses ephemeral SQLite for the backend. Scan history and pending continuation state can therefore disappear on backend redeploy or instance replacement until durable storage is enabled.
