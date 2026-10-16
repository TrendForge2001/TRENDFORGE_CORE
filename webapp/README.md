# TrendForge Webapp

R68.3 extends the standalone Streamlit frontend over the canonical FastAPI backend. The backend remains the sole scanner/execution authority; the webapp is an HTTP client and presentation/control surface.

## Pages

- **Command Center** — core health, NIFTY 500 readiness, scanner runtime and paper safety status.
- **Scan History** — immutable audit rows, lineage rollups, end-to-end completion and integrity diagnostics.
- **NIFTY 500 Scanner** — staged 25/50/100/500 scans, ranked-result filtering/export and guarded continuation resume.
- **Watchlists** — named stock lists with priorities, notes, target/stop-loss context, score/signal metadata and admin-gated mutations.
- **Paper Trading** — simulated positions, supervised paper orders, kill switch and monitor tick.
- **Market Breadth** — persisted NIFTY 500 sample breadth, A/D participation, EMA breadth, highs/lows, sector participation and coverage diagnostics.
- **Market Regime** — persisted equal-weight NIFTY 500 sample composite with canonical TrendForge regime scoring and component evidence.
- **Portfolio** — persisted Kite holdings/positions, allocation, mark-to-market P&L and admin-gated live refresh.
- **P&L Statement** — daily/weekly/monthly/yearly/all-history realized paper-trade P&L with capital-utilization evidence.
- **Performance** — win rate, profit factor, expectancy, drawdown and cumulative realized paper P&L.
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


## Portfolio and performance contracts

R68.2 uses three canonical read contracts:

    GET /portfolio
    GET /pnl?period=<daily|weekly|monthly|yearly|all>
    GET /performance?period=<daily|weekly|monthly|yearly|all>

Live broker synchronization is explicit and admin protected:

    POST /portfolio/sync

The Portfolio page and P&L/Performance pages intentionally use different scopes:

- Portfolio = persisted/live Kite broker books.
- P&L and Performance = CLOSED TrendForge paper trades.

They are never combined into one P&L number.

Newly closed paper trades record `closed_at` in Asia/Kolkata. Historical rows without `closed_at` remain readable and are tagged `legacy_entry_fallback`; their entry timestamp is used only for period attribution.

The canonical database initializer now includes the `live_portfolio` table on clean boots.


## Watchlists and market context

R68.3 adds these canonical read contracts:

    GET /watchlists
    GET /watchlists/{name}
    GET /market/breadth
    GET /market/regime

Watchlist changes are admin protected:

    POST   /watchlists/{name}/symbols
    PUT    /watchlists/{name}/symbols/{symbol}
    DELETE /watchlists/{name}/symbols/{symbol}
    DELETE /watchlists/{name}

Market-data refresh is explicit and admin protected:

    POST /market/context/refresh

The market refresh calculates breadth and regime once, then persists the latest snapshots in SQLite. Dashboard reads never trigger the market-data fan-out automatically.

Breadth uses an evenly spaced sample across the canonical NIFTY 500 security list when the selected sample size is below the full universe. The public breadth score is the bounded canonical Breadth Engine score; the older EMA-weighted raw calculation remains available only as diagnostics.

Regime uses an equal-weight normalized composite built from the same sampled securities, enriches that composite through the canonical Indicator Engine, and evaluates it with the canonical Market Regime Engine.

The new `market_context_snapshots` and existing watchlist tables remain subject to the backend SQLite durability boundary. On ephemeral Render storage, watchlists and snapshots can disappear after a backend redeploy or instance replacement.
