# TrendForge Webapp

R68.8 extends the standalone Streamlit frontend over the canonical FastAPI backend. The backend remains the sole scanner/execution authority; the webapp is an HTTP client and presentation/control surface.

## Pages

- **Command Center** — core health, NIFTY 500 readiness, scanner runtime and paper safety status.
- **Scan History** — immutable audit rows, lineage rollups, end-to-end completion and integrity diagnostics.
- **Notification Center** — Discord-only manual/test routing plus automatic scanner, paper-trading, risk and system producer health, cooldown/dedupe audit history and CSV export.
- **NIFTY 500 Scanner** — staged 25/50/100/500 scans, ranked-result filtering/export and guarded continuation resume.
- **Watchlists** — named stock lists with priorities, notes, target/stop-loss context, score/signal metadata and admin-gated mutations.
- **Paper Trading** — simulated positions, supervised paper orders, kill switch and monitor tick.
- **Market Breadth** — persisted NIFTY 500 sample breadth, A/D participation, EMA breadth, highs/lows, sector participation and coverage diagnostics.
- **Market Regime** — persisted equal-weight NIFTY 500 sample composite with canonical TrendForge regime scoring and component evidence.
- **News Intelligence** — persisted symbol-scoped news evidence, provider/source provenance, heuristic sentiment/impact, breaking-news flags, CSV export and admin-gated live refresh.
- **Corporate Actions** — persisted NSE action evidence, normalized event types, upcoming/high-impact flags, weighted impact scoring, CSV export and admin-gated live refresh.
- **Big Shark Activity** — persisted institutional/shareholding/deal evidence evaluated by the canonical Big Shark Engine, with ownership/change/deal provenance and admin-gated refresh.
- **Sector Strength** — persisted NIFTY 500 sector ranking using aggregated momentum, relative performance, volume participation, breadth, leadership and consistency through the canonical Sector Engine.
- **Backtesting** — versioned EMA20/EMA50 + RSI historical simulation with next-bar execution, cost/slippage controls, persisted run history, benchmark comparison, equity curve and trade ledger.
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


## Backtesting contracts

R68.4 adds read-only backtest status/history/detail contracts:

    GET /backtests/readiness
    GET /backtests?limit=<1..500>&symbol=<optional>
    GET /backtests/{run_id}

Historical execution is explicit and admin protected:

    POST /backtests

The first canonical strategy is `EMA20_50_RSI`, version `R68.4-v1`.

Entry requires an EMA20 cross above EMA50, RSI at or above the configured threshold, and close within the configured percentage of EMA20. Exit occurs on EMA20 crossing below EMA50 or RSI falling below the threshold.

Signals are calculated only after a daily bar closes and are filled at the next daily bar open. This is intentionally different from same-close execution and prevents the baseline backtest from using the closing signal price as if it were already known before that close.

The engine is long-only, holds at most one position, uses integer shares and all available cash, and forces any remaining open position to close at the final test bar. Transaction costs and slippage are configured separately in basis points per side.

Every R68.4 run stores its full parameters, metrics, trade ledger and equity curve in the evolved `backtest_results` table. Legacy summary-only rows remain readable after the in-place migration.

Backtesting is historical simulation only. It cannot create paper orders and cannot place broker orders.


## News and corporate-action intelligence

R68.5 adds canonical persisted intelligence evidence:

    GET /intelligence/readiness
    GET /intelligence/events
    GET /intelligence/{symbol}/summary
    GET /intelligence/{symbol}/news
    GET /intelligence/{symbol}/corporate-actions

Live provider refresh is explicit and admin protected:

    POST /intelligence/refresh

The refresh request accepts up to 50 symbols and one or both domains: news and corporate_actions. Corporate-action provider windows support 1-365 days.

R68.5 stores normalized evidence in the dedicated intelligence_events table instead of reshaping the older news/corporate_actions tables. Each source item receives a deterministic SHA-256 event key; repeated refreshes update the same evidence instead of creating duplicates.

News scoring is keyword_heuristic_v1. Positive/negative headline keywords produce a bounded -10..+10 impact score, while selected event words mark a headline as BREAKING_NEWS. This is not an LLM or AI sentiment classifier.

Corporate-action scoring is event_weight_heuristic_v1. Existing explicit event weights are retained (for example buyback +9, bonus +8, split +7, dividend +5, penalty -6, default -8, insolvency/delisting -10) and the result is bounded to -10..+10.

The combined symbol intelligence score is an evidence-weighted diagnostic only: news weight 0.4 and corporate-actions weight 0.6 when both domains contain evidence. When only one domain has evidence, that domain is not diluted by a missing zero-score domain.

Dashboard GET requests read persisted evidence only. They never launch live news/NSE calls automatically.

The intelligence_events table uses the same backend SQLite durability boundary as other persisted webapp evidence. On ephemeral Render storage, evidence can disappear after backend redeploy or instance replacement.


## Institutional and sector-strength contracts

R68.6 adds read-only persisted contracts:

    GET /institutional/readiness
    GET /institutional?limit=<1..500>
    GET /institutional/{symbol}
    GET /sector-strength

Explicit refreshes are admin protected:

    POST /institutional/refresh
    POST /sector-strength/refresh

Institutional refresh accepts at most 25 symbols because the source-backed provider can combine Yahoo institutional-holder tables, NSE/BSE shareholding filings, Screener fallback evidence, and NSE bulk/block deals. The canonical Big Shark Engine evaluates only evidence actually returned by those sources. Missing evidence lowers confidence and is never converted into a bullish institutional signal.

Sector Strength samples the canonical NIFTY 500 constituent universe, retrieves daily candles through the existing market-data adapter, aggregates member returns/volume/breadth by official constituent sector, and evaluates each sector snapshot with the canonical Sector Engine. Supported horizons are 1d, 1w, 1m and 3m, with a 20-session relative-volume measure and positive-1m constituent leadership percentage.

R68.6 does not currently have a source-backed sector-level FII/DII flow feed. Those Sector Engine inputs remain unavailable/neutral and are explicitly labeled as such instead of being inferred from unrelated data.

Both institutional and sector results are diagnostic confirmation layers and are explicitly not standalone trade signals.

Snapshots are stored in the new institutional_sector_snapshots SQLite table. The existing Render ephemeral-storage limitation therefore still applies until durable backend storage is configured.


## Notification Center contracts

R68.7 adds canonical Discord-only notification contracts:

    GET /notifications/readiness
    GET /notifications/summary
    GET /notifications/events
    GET /notifications/events/{event_id}

Event creation and live Discord delivery are explicit admin-protected mutations:

    POST /notifications/events
    POST /notifications/test

The canonical Discord transport resolves its webhook from the runtime DISCORD_WEBHOOK secret first. The legacy config/alerts.json webhook remains blank and is not treated as a secret store.

Every routed event is persisted in the notification_events table with event type, category, severity, source, optional symbol, delivery status, dedupe key, payload metadata, timestamps and delivery error evidence. The webhook itself is never persisted or returned by readiness/history APIs.

Supported canonical categories are scanner, paper, risk, system, intelligence, market and portfolio. Supported severities are INFO, SUCCESS, WARNING, ERROR and CRITICAL.

A routed event can be record-only by setting deliver=false. When delivery is requested and Discord is not configured, the event is persisted as blocked rather than being reported as sent. Successful events are sent; network/provider failures are persisted as failed.

The default cooldown is 15 minutes and can be changed with TRENDFORGE_ALERT_COOLDOWN_MINUTES. If no dedupe key is supplied, TrendForge derives one from category, event type, symbol, title and message. A duplicate of a recent sent/recorded event is persisted as suppressed and does not produce another Discord call. Failed and blocked events are intentionally retryable and do not poison the dedupe window.

R68.7 is Discord-only. Email and WhatsApp are not part of the canonical routing path.

The older alerts_log table and legacy alert helpers remain untouched for compatibility. New dashboard/API event routing uses notification_events as the canonical evidence store.

Notification persistence is SQLite-backed and remains subject to the existing Render ephemeral-storage limitation until durable backend storage is configured.


## Automatic notification producers

R68.8 wires the existing canonical producer domains into the R68.7 Notification Center while preserving the Notification Center as an observational side channel.

Producer health is read-only:

    GET /notifications/producers

The NIFTY 500 production scan records a scanner-run summary after audit commit and before compact response projection. A fully completed scan can deliver execution-eligible pick alerts to Discord. Partial scans record their summary but do not send pick alerts. The default cap is three execution-pick alerts per completed scan and can be configured with TRENDFORGE_NOTIFICATION_MAX_SCAN_PICKS from 0 through 20.

PaperTradingService emits events for successful paper opens, monitored closes and actual runtime kill-switch state changes. It also emits risk events when a manual paper entry is blocked because paper trading is disabled or the kill switch is active.

PaperAutoEntryService records one evaluation summary per requested run. Discord risk delivery is intentionally narrow: only maximum daily paper-loss and maximum open-position guardrails generate automatic risk alerts. Routine low-score, confidence, reward/risk, duplicate-symbol or market-window rejections remain in the auto-entry evaluation evidence and do not create Discord noise.

PaperQuoteMonitor emits a deduplicated system ERROR event when live quote monitoring fails. Application startup emits system ERROR events when persisted paper-position restore or quote-monitor startup fails. Successful restore is record-only and is created only when positions were actually restored.

All producer calls are best-effort. Notification persistence errors, a missing Discord webhook, network failures or a bug in the notification adapter cannot convert a successful scan/paper operation into a failed primary operation. Producer health keeps attempted/routed/failure counters and the latest producer error for diagnostics.

R68.8 does not change scanner scoring or execution eligibility. It does not place broker orders, and paper notifications remain explicitly paper-only.
