# R71 — Weekend research and backtesting in the actual Streamlit app

## What is implemented

Existing backtests remain under **Research → Backtesting** and continue using
canonical FastAPI. New **Research → Weekend Research & Stock Selection** is a
self-contained, read-only Streamlit page and can run without an active Kite
session or an awake FastAPI backend.

- Yahoo's public, adjusted daily history is optional and best-effort.
- Offline CSV upload works without Yahoo. Required columns:
  \`Date,Symbol,Open,High,Low,Close,Volume\` (case-insensitive).
- Maximum 20 securities and 8 MB CSV. Minimum 80 completed trading bars.
- Conservative IST cutoff: weekdays use today's bar only after 16:00 IST,
  weekends use the previous weekday; holiday/special sessions are not confirmed.
- Cross + RSI >= 60 + within 1% EMA20 + volume > 20-day average
  (thresholds/filter configurable). Ranks new BUY_CROSS and TREND_WATCH
  separately; "watch" is not an actual buy entry.
- One-stock backtest reuses the canonical BacktestEngine:
  post-close signals, next-open entry/exit, long only, whole shares,
  configurable per-side cost/slippage, final marked exit, metrics and ledger.
- No broker, paper-trade, API admin, or production SQLite write paths are used.
- Yahoo auto_adjust is enabled to dampen split distortions, but adjusted
  historical prices are not guaranteed executable fills. No real investment
  performance claims. Errors are explicit, not zero-filled.

## Streamlit local smoke test (no production deploy)

\`\`\`powershell
cd C:\Users\Lenovo\Desktop\TrendForge
git fetch origin
git switch feature/r71-weekend-streamlit-research
git pull --ff-only origin feature/r71-weekend-streamlit-research
.\.venv\Scripts\python.exe -m pip install -r webapp/requirements.txt
.\.venv\Scripts\python.exe -m pytest -q tests/test_r71_weekend_research.py

$env:TRENDFORGE_API_URL = "https://trendforge-core.onrender.com"
.\.venv\Scripts\python.exe -m streamlit run webapp/app.py
\`\`\`

Use the sidebar **Research → Weekend Research & Stock Selection**. The
webapp access gate remains in force. Do not commit API/admin/access keys.

## Existing Render Streamlit frontend (requires Render account access)

The existing blueprint is \`deploy/render-webapp.yaml\`:

- Service \`trendforge-webapp\`, Free web
- Build: \`python -m pip install -r webapp/requirements.txt\`
- Start: \`python -m streamlit run webapp/app.py --server.address 0.0.0.0 --server.port $PORT\`
- Health: \`/_stcore/health\`

For a test deploy, point a separate staging Streamlit web service at this
feature branch; do not redeploy the existing production FastAPI service. Use
Render dashboard to set/verify these existing frontend variables:
\`TRENDFORGE_API_URL\`, \`TRENDFORGE_ADMIN_API_KEY\` and
\`TRENDFORGE_WEBAPP_ACCESS_KEY\`. Reuse previously provisioned secrets
securely; never copy their values into GitHub or chat. The standalone Weekend
Research page itself does not need the admin API key.

After all CI checks and browser acceptance gates pass, merge the stacked
branches (R70.1 → R70.2 → R70.3 → R71) in order, then trigger deployment
of the existing Streamlit frontend from the approved main commit.

## Streamlit Community Cloud alternative

Create an app using this GitHub repo and select
\`webapp/app.py\` as entrypoint. Set appropriate access/API secrets in the
Streamlit Cloud secrets manager; retain access gate. Because the
module is inside \`webapp\`, ensure the repository root is importable from
the app's runtime. Confirm \`/_stcore/health\` or the platform's app health
independently.

## Deployment acceptance

1. CI successful (Python 3.11/3.12 and R71 frontend workflow).
2. Streamlit service URL opens with normal access gate intact.
3. Weekend page appears; offline upload ranks a real multi-stock CSV.
4. Public history can fail without affecting offline upload.
5. Correct Friday candle date appears on Sunday; no incomplete/live bar.
6. Backtest shows equity curve, costs, trades and export.
7. No automatic orders, no broker keys exposed and no Render DB write.
8. Confirm Render Git SHA and browser URL after deployment.

This document does not claim that cloud deployment has occurred. The GitHub
integration can commit and test code, but changing a Render service requires
an authorized Render account connection or the Render dashboard.
