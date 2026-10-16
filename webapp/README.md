# TrendForge Webapp

R68.1 extends the standalone Streamlit frontend over the canonical FastAPI backend. The backend remains the sole scanner/execution authority; the webapp is an HTTP client and presentation/control surface.

## Pages

- **Command Center** — core health, NIFTY 500 readiness, scanner runtime and paper safety status.
- **Scan History** — immutable audit rows, lineage rollups, end-to-end completion and integrity diagnostics.
- **NIFTY 500 Scanner** — staged 25/50/100/500 scans, ranked-result filtering/export and guarded continuation resume.
- **Paper Trading** — simulated positions, supervised paper orders, kill switch and monitor tick.
- **Fundamentals** — report, symbol inspection, templates, upload and manual update.
- **System** — session-scoped API URL/admin key, diagnostics and access-session lock.

## Local run

From the repository root on Windows PowerShell:

    .\.venv\Scripts\python.exe -m pip install -r webapp\requirements.txt
    $env:TRENDFORGE_API_URL = "http://localhost:8000"
    .\.venv\Scripts\python.exe -m streamlit run webapp\app.py

To point the UI at the production backend:

    $env:TRENDFORGE_API_URL = "https://trendforge-core.onrender.com"
    $env:TRENDFORGE_ADMIN_API_KEY = "<backend-admin-key>"
    $env:TRENDFORGE_WEBAPP_ACCESS_KEY = "<separate-webapp-access-key>"
    .\.venv\Scripts\python.exe -m streamlit run webapp\app.py

The backend admin key and webapp access key must be different secrets. Do not commit either value.

## Continuation behavior

A partial scan can return an opaque one-time continuation token. R68.1 keeps that token only in the active Streamlit browser session. Resume uses:

    POST /scan/universe/nifty500
         ?run_id=<new-run-id>
         &continuation_token=<token>

The resume request sends an empty JSON body so the backend inherits the original period, interval, capital, top_n and omitted operational controls under the R66.8 contract.

Raw continuation tokens are intentionally not recoverable from immutable scan audits.

## Separate Render deployment

The backend production manifest remains the root `render.yaml`.

The frontend reference Blueprint is:

    deploy/render-webapp.yaml

It creates a separate `trendforge-webapp` service using `webapp/requirements.txt` and Streamlit's `/_stcore/health` endpoint.

Configure these Render secrets/variables when creating the frontend service:

- `TRENDFORGE_API_URL`
- `TRENDFORGE_ADMIN_API_KEY`
- `TRENDFORGE_WEBAPP_ACCESS_KEY`

The access key protects the Streamlit control plane before navigation is rendered. This is required because the server-side webapp may hold the backend admin credential.
