# R69.1 External Scheduler, Wake-Up and Production Scheduling

R69.1 removes the production scheduling dependency on an always-awake
TrendForge web process.

It does this without broadening execution permissions.

## Problem

The R69.0 asyncio worker is useful while the backend process is running, but an
in-process worker cannot wake a suspended hosting service.

R69.1 adds an independent HTTP wake-up contract that can be called by GitHub
Actions or another external scheduler.

## Security boundary

Dedicated environment secret:

    TRENDFORGE_SCHEDULER_API_KEY

Dedicated header:

    X-TrendForge-Scheduler-Key

Minimum length:

    32 characters

The scheduler key must be distinct from:

    TRENDFORGE_ADMIN_API_KEY

A reused admin key is treated as scheduler misconfiguration and the external
tick fails closed with HTTP 503.

The scheduler credential is intentionally narrower than the admin credential.
It authenticates only:

    POST /operations/external-tick

It cannot authorize:

- scanner runs
- paper mutations
- watchlist mutations
- market-context manual refreshes
- portfolio manual sync
- fundamentals writes
- notification sends
- any broker order

## Read-only diagnostics

    GET /operations/external-scheduler/readiness

Reports:

- scheduler credential configured/not configured
- whether it is distinct from the admin key
- minimum key length
- protected header name
- narrow scope
- target endpoint
- timezone
- broker_orders_allowed=false

The secret value is never returned.

Current operation contract:

    GET /operations/external-scheduler/status?operation=morning
    GET /operations/external-scheduler/status?operation=eod

These reads trigger no operational work.

## Satisfaction contract

The current-day contract can return:

    not_required
    pending
    due
    satisfied
    missed_window

Reasons include:

    automation_disabled
    operation_disabled
    non_market_day
    before_window
    inside_window
    successful_run_recorded
    degraded_run_recorded
    window_elapsed_without_success

A previously completed/degraded run remains satisfied even if a redundant
wake-up arrives after the grace window.

This is important because external schedulers can queue or delay duplicate
calls.

## External tick

    POST /operations/external-tick

Header:

    X-TrendForge-Scheduler-Key: <dedicated key>

Body:

    {
      "expected_operation": "morning"
    }

or:

    {
      "expected_operation": "eod"
    }

The response includes:

- before contract
- scheduler tick evidence
- expected operation tick evidence
- after contract
- auth_scope=operations_external_tick_only
- broker_orders_allowed=false

The external call invokes:

    scheduler.tick(external=true)

External mode bypasses only the in-process-worker-enabled switch.

It does not bypass:

- automation_enabled
- operation enabled/disabled policy
- market-day guard
- bounded operation window
- same-day completion/idempotency
- paper safety semantics

## Recommended production mode

Once the external scheduler is configured, production may set:

    TRENDFORGE_OPERATIONS_WORKER_ENABLED=false

This removes duplicate internal polling while retaining manual admin controls
and external wake-up.

This environment change is optional. R69.1 does not modify the active
render.yaml.

## Wake-up client

R69.1 adds:

    scripts/operations_wakeup.py

It uses only Python standard-library networking.

Configuration:

    TRENDFORGE_SCHEDULER_URL
    TRENDFORGE_SCHEDULER_API_KEY

Example:

    TRENDFORGE_SCHEDULER_URL=https://trendforge-core.onrender.com
    python scripts/operations_wakeup.py --expect morning

The URL must:

- use HTTPS for non-local targets
- may use HTTP only for localhost development
- be absolute
- contain no embedded credentials
- contain no query string
- contain no fragment

The client appends:

    /operations/external-tick

The key is never printed.

## Retry behavior

Default client behavior:

    attempts = 2
    request timeout = 300 seconds
    base retry delay = 15 seconds

The longer timeout is intentional because the external tick can perform the
bounded market-context refresh before returning.

Retryable transport/HTTP conditions include:

    408
    425
    429
    500
    502
    503
    504

Network/timeout failures are also retried.

A missed_window contract is not retried because the bounded execution window
has already elapsed.

Exit codes:

    0  satisfied, or not_required because it is a non-market day
    1  transport/auth/contract/degraded/configuration failure
    2  missed operation window

Once the GitHub scheduler is configured, automation_disabled and
operation_disabled are treated as configuration failures rather than green
no-ops. This makes loss of SQLite-backed scheduling policy visible after an
ephemeral deployment reset.

## GitHub Actions schedules

Morning workflow:

    .github/workflows/market-day-morning.yml

Cron:

    15,25,35,45 3 * * *

UTC -> IST:

    03:15 -> 08:45
    03:25 -> 08:55
    03:35 -> 09:05
    03:45 -> 09:15

EOD workflow:

    .github/workflows/market-day-eod.yml

Cron:

    15,25,35,45 10 * * *

UTC -> IST:

    10:15 -> 15:45
    10:25 -> 15:55
    10:35 -> 16:05
    10:45 -> 16:15

India does not use daylight-saving time, so these UTC/IST mappings are stable.

The four calls per window are deliberate redundancy.

R69.0 same-day idempotency means the first successful operation satisfies the
date and later calls safely observe that completion.

## Calendar behavior

The workflows run every calendar day.

This is intentional.

Ordinary weekends and configured holidays return:

    not_required / non_market_day

without performing the operation and remain successful workflow outcomes.

A configured special weekend trading day can therefore still receive the same
external wake-up.

The backend remains the calendar authority.

## GitHub repository configuration

Repository variable:

    TRENDFORGE_SCHEDULER_URL

Recommended value:

    https://trendforge-core.onrender.com

Repository secret:

    TRENDFORGE_SCHEDULER_API_KEY

The secret must match the backend scheduler key.

Do not store the broad admin key in these workflows.

The workflow files contain no secret values.

## Unconfigured behavior

Scheduled workflows are merged in a safe inactive state.

If either the repository URL variable or scheduler secret is missing, the
workflow emits a GitHub Actions notice and skips the network wake-up.

It does not fail the repository merely because R69.1 has not yet been
configured.

After both values are present, network/auth/missed-window failures are real
workflow failures.

## Cold-start behavior

An external HTTP request can wake a sleeping HTTP service.

The client retry window is intended to tolerate normal cold-start latency and
transient gateway errors.

No claim is made that the hosting provider or GitHub Actions provides a hard
real-time SLA.

## Reliability boundary

GitHub Actions scheduled workflows are best-effort and can be delayed.

R69.1 reduces timing risk with:

- four independent scheduled wake times per operation window
- per-run transient retries
- persisted same-day idempotency
- explicit post-tick satisfaction verification
- non-zero missed-window result

For a stricter scheduling SLA, use a dedicated cloud scheduler to invoke the
same narrow external endpoint.

No code changes are required to switch external scheduler providers.

## Production health

    GET /production/health

now includes:

    scheduler_security

This exposes configuration status only.

It never exposes the scheduler key.

## Webapp

Market-Day Operations now shows:

- external scheduler credential state
- auth scope
- current morning satisfaction contract
- current EOD satisfaction contract

System diagnostics exposes the same read-only endpoints.

The Streamlit webapp does not receive or store the scheduler credential.

## Scope exclusions

R69.1 does not add:

- Render cron services
- APScheduler
- a new production dependency
- database migrations
- scanner automation
- live broker execution
- a scheduler secret to render.yaml
- the broad admin key to GitHub wake-up workflows
