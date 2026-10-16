# R69.0 Scheduled Operations, Market-Day Automation and Control Center

R69.0 adds an opt-in operational scheduler around existing TrendForge services.

It is an orchestration layer, not a new trading engine.

## Safety boundary

R69.0 does not:

- change scanner scoring
- change execution eligibility
- launch scheduled scanner runs
- enable live broker orders
- bypass paper-trading risk controls
- add APScheduler
- add a database migration
- change Render manifests

Every operation reports:

    broker_orders_allowed = false

The EOD execution-related step is paper-only.

## Market-day session

Read-only:

    GET /operations/session

Timezone:

    Asia/Kolkata

Normal boundaries:

    09:15 market open
    15:00 paper entry cutoff
    15:30 market close

Phases:

    closed_non_market_day
    pre_market
    market_open_paper_entry
    market_open_paper_exit_only
    post_market

Calendar authority:

    weekday_plus_configured_overrides

The built-in calendar deliberately does not make a network call and does not claim to be a live NSE holiday source.

Configured policy can supply:

    calendar.holiday_dates
    calendar.special_trading_dates

A configured special-trading date overrides weekend classification. It does not alter the normal session clock. Exceptional exchange sessions with different hours must not be inferred from this override.

## Policy

Read:

    GET /operations/policy

Admin mutations:

    PUT /operations/policy
    DELETE /operations/policy

Policy is stored in the existing settings table under:

    operations.policy.r69_0

Default:

    automation_enabled = false
    market_day_only = true
    market_context_limit = 100

Morning:

    enabled = true
    time_ist = 08:45
    grace_minutes = 30
    refresh_market_context = true
    notify_discord = true

EOD:

    enabled = true
    time_ist = 15:45
    grace_minutes = 30
    paper_safety_tick = true
    refresh_market_context = true
    portfolio_sync = false
    notify_discord = true

DELETE removes the stored override and restores these built-in defaults.

## Bounded windows

The scheduler runs an operation only while:

    scheduled_time <= current_IST_time <= scheduled_time + grace

This is a deliberate anti-catch-up rule.

Example:

    morning 08:45 + 30 minutes

may run from 08:45 through 09:15 inclusive.

If the process first wakes at 10:00, the morning operation is not replayed automatically.

## Morning operation

Manual/admin:

    POST /operations/run/morning

Default step:

    market_context_refresh

The refresh reuses the canonical R68.3 MarketContextService:

    period = 1y
    interval = 1d
    refresh_universe = false
    sample limit = policy.market_context_limit

No scan is launched.

## End-of-day operation

Manual/admin:

    POST /operations/run/eod

Default steps:

    market_context_refresh
    paper_safety_tick
    daily_pnl_snapshot

Optional:

    portfolio_sync

The paper safety tick delegates to the existing PaperQuoteMonitor and PaperTradingService. Existing 15:00 IST paper force-exit semantics remain authoritative.

If no paper positions are open, the monitor remains idle.

Portfolio sync uses existing Kite holdings()/positions() reads and updates the local live_portfolio reporting snapshot. It does not place a broker order.

Run history stores only bounded portfolio evidence:

- row count
- holding count
- position count
- portfolio value
- investment
- total P&L

Full holdings/positions are not duplicated into operations history.

## Operation result semantics

Each run records:

    run_id
    operation
    status
    date_ist
    started_at_ist
    completed_at_ist
    scheduled
    forced
    market_day
    market_phase
    completed_steps
    failed_steps
    steps
    broker_orders_allowed = false

Status:

    completed  all requested steps completed
    degraded   one or more requested steps failed

Individual step failures are captured as evidence instead of aborting later independent steps.

Notification failure is a side-channel failure and cannot change a completed/degraded operational result.

## Same-day idempotency

Run evidence is stored under:

    operations.runs.r69_0

History is bounded to 100 records.

A completed/degraded morning or EOD run for the same IST date is not automatically repeated.

An administrator can intentionally bypass:

- operation-enabled guard
- market-day guard
- same-day completion guard

using:

    {"force": true}

This force flag still cannot enable broker orders.

## Scheduler

Readiness:

    GET /operations/readiness

Manual scheduler evaluation:

    POST /operations/tick

The worker uses asyncio + asyncio.to_thread only.

Environment:

    TRENDFORGE_OPERATIONS_WORKER_ENABLED
    TRENDFORGE_OPERATIONS_POLL_SECONDS

Defaults:

    worker enabled
    60 second poll

Policy automation remains disabled by default, so a running worker performs no operation until the user explicitly enables automation.

## Hosting limitation

An in-process scheduler cannot run when its hosting process is suspended or asleep.

This matters on hosting tiers that spin down inactive services.

R69.0 therefore exposes the admin-protected:

    POST /operations/tick

contract so a future external cron/scheduler can wake the backend and evaluate the same persisted policy and market-day rules.

No Render cron service is added in R69.0.

## Control center

Read-only:

    GET /operations/control-center
    GET /operations/runs?limit=20

The control-center response combines persisted/read-only evidence from:

- current IST market session
- operations policy
- recent operation runs
- latest market breadth snapshot
- latest market regime snapshot
- paper quote-monitor health
- persisted live portfolio snapshot
- daily realized paper P&L
- Discord Notification Center readiness

GET requests do not trigger market-data refreshes, broker syncs or paper exits.

## Discord routing

Operational completion events use category:

    system

Successful operation severity:

    INFO

Degraded operation severity:

    WARNING

The existing R68.9 notification policy remains authoritative.

With built-in system minimum severity WARNING, healthy INFO completion messages are normally persisted as filtered evidence. Degraded WARNING runs are eligible for Discord delivery.

## SQLite concurrency

The R69.0 operations repository serializes access to its settings/history keys with a re-entrant process lock because the scheduler runs in a worker thread while FastAPI may read the same state concurrently.

## Webapp

New page:

    Market-Day Operations

It provides:

- session/market-day status
- automation/worker status
- policy editor
- holiday overrides
- special-trading-day overrides
- market-context sample size
- morning/EOD task controls
- manual morning/EOD execution
- scheduler tick
- force-run control
- policy reset
- market/paper/portfolio/P&L evidence
- recent run history
- CSV run export

The Command Center and System diagnostics also expose the R69.0 runtime.
