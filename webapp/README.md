# TrendForge Webapp

R68.0 introduces a standalone Streamlit frontend that consumes the canonical FastAPI backend. It does not replace or embed the backend and does not alter the existing Render production service.

## Pages

- Command Center — core health, NIFTY 500 readiness, scanner runtime, paper safety status.
- NIFTY 500 Scanner — staged 25/50/100/500 scans using the canonical universe endpoint.
- Paper Trading — simulated positions, supervised paper orders, kill switch, monitor tick.
- Fundamentals — report, symbol inspection, templates, upload, manual update.
- System — session-scoped API URL/admin key and diagnostics.

## Local run

From the repository root on Windows PowerShell:

    .\.venv\Scripts\python.exe -m pip install -r webapp\requirements.txt
    $env:TRENDFORGE_API_URL = "http://localhost:8000"
    .\.venv\Scripts\python.exe -m streamlit run webapp\app.py

To point the UI at Render:

    $env:TRENDFORGE_API_URL = "https://trendforge-core.onrender.com"
    $env:TRENDFORGE_ADMIN_API_KEY = "<your-admin-key>"
    .\.venv\Scripts\python.exe -m streamlit run webapp\app.py

The admin key can also be entered on the System page for the current Streamlit browser session. Do not commit a real key to Git.

## Deployment boundary

R68.0 intentionally does not modify root render.yaml. The existing FastAPI service remains the production backend. A dedicated frontend service can be added after UI validation so frontend changes cannot destabilize the scanner runtime.
