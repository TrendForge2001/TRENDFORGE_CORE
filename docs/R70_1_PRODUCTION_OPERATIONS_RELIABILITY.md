# R70.1 Production Operations Audit, Missed-Run Alerts and Scheduler Reliability

The user-requested Production Operations Audit scope is implemented as R70.1
because the current repository already uses R69.2 for the canonical backtest
engine and has progressed through R70 local-storage work.

R70.1 extends R69.0/R69.1 scheduling with independent evidence and
post-window verification.

## Safety boundary

R70.1 does not:

- change scanner scoring
- launch scanner runs
- change paper-trading execution semantics
- enable broker orders
- bypass R69.0 market-day/window/idempotency rules
- add APScheduler
- add a database migration
- add a Render cron service
- modify the active root render.yaml

Every reliability/external response preserves:

    broker_orders_allowed = false

## Audit persistence

R70.1 reuses the existing SQLite settings table.

Key:

    operations.audit.r70_1

Maximum retained events:

    300

No schema migration is required.

The existing storage durability boundary still applies. On ephemeral backend
storage, audit evidence can be lost after redeploy or instance replacement.

## Evidence types

External wake-up evidence:

    event_type = external_tick

Post-window verification:

    event_type = post_window_audit

The distinction matters because R69.1 deliberately sends multiple redundant
wake-ups. Reliability percentages must not count those duplicate calls as
multiple successful operations.

## External tick evidence

The existing:

    POST /operations/external-tick

now attempts to record an external_tick audit event containing:

- operation
- before status
- scheduler tick status
- after status
- final audit classification
- completion delay when available
- IST timestamp
- broker_orders_allowed=false

This write is best-effort.

If the reliability ledger fails, the primary external tick response still
reflects the operation result and does not fail solely because observability
persistence failed.

## Post-window audit

Narrow scheduler-authenticated endpoint:

    POST /operations/external-audit

Header:

    X-TrendForge-Scheduler-Key

Body:

    {
      "expected_operation": "morning"
    }

or:

    {
      "expected_operation": "eod"
    }

The same R69.1 scheduler-only key is used.

The broad admin key cannot substitute for it.

Manual admin audit:

    POST /operations/audit/run

Body:

    {
      "operation": "morning",
      "deliver_alerts": false
    }

operation may be null to audit both morning and EOD.

Manual audits default to no alert delivery. External post-window audits are
strict and alert-capable.

## Audit states

    healthy
    missed
    degraded
    configuration_error
    not_required
    disabled
    pending
    due
    unknown

Mapping from the R69.1 external contract:

    satisfied -> healthy
    degraded -> degraded
    missed_window -> missed
    non_market_day -> not_required

Strict external audit additionally maps:

    automation_disabled -> configuration_error
    operation_disabled -> configuration_error

This makes lost/disabled production policy visible.

## Missed-run alerts

Missed:

    severity = CRITICAL
    category = system
    event_type = operations_reliability_alert

Degraded:

    severity = ERROR

Unexpected production automation drift:

    severity = ERROR

Alerts route through the canonical R68.7/R68.9 Notification Center and remain
subject to its Discord configuration and alert policy.

Notification delivery is a side channel and cannot modify the underlying
operation result.

## Daily alert dedupe

Alert identity is scoped to:

    date + operation + audit state

Example:

    operations-reliability:2026-10-16:morning:missed

R70.1 checks the persisted audit ledger before emitting.

If a prior same-state alert was:

    sent
    filtered
    suppressed

the later audit records already_alerted and does not emit again.

If the prior delivery was:

    failed
    blocked

a later audit may retry delivery.

## Read-only API

Reliability:

    GET /operations/reliability?days=30

Allowed window:

    1..90 days

Audit ledger:

    GET /operations/audit?limit=100
    GET /operations/audit?limit=100&operation=morning
    GET /operations/audit?limit=100&operation=eod

Maximum audit limit:

    300

## Reliability calculation

Historical measured operations use post_window_audit rows only.

Successful measured operation:

    healthy

Failure measured operation:

    missed
    degraded
    configuration_error

Historical reliability percentage:

    healthy / (healthy + failures) * 100

Duplicate external_tick rows are reported as scheduler activity but are not
included in this denominator.

Per-operation metrics include:

- post-window audit count
- external wake tick count
- healthy count
- missed count
- degraded count
- configuration-error count
- not-required count
- average completion delay
- reliability percentage
- latest audit evidence

## Completion delay

When a successful run exposes completed_at_ist:

    completion_delay_minutes =
        completed_at_ist - window_start_ist

This is reported per operation and across the reliability window.

## Current health

Current health can be:

    GREEN
    AMBER
    RED
    NO_DATA

RED if any of the following apply:

- latest post-window evidence is missed/degraded/configuration-error
- the live current contract is missed or degraded
- market-day automation/operation is unexpectedly disabled
- required post-window verification is absent after the audit grace point

Default audit verification grace:

    10 minutes after window_end_ist

This prevents yesterday's green audit from masking a missing audit today.

## External post-window workflows

Morning verification:

    .github/workflows/market-day-morning-audit.yml

Default schedule:

    03:55 UTC = 09:25 IST

EOD verification:

    .github/workflows/market-day-eod-audit.yml

Default schedule:

    10:55 UTC = 16:25 IST

India has no DST, so the UTC mapping is stable.

The checks run every calendar day. The backend market-day contract makes normal
weekends/holidays not_required without alerts.

Both workflows:

- use TRENDFORGE_SCHEDULER_URL
- use the narrow TRENDFORGE_SCHEDULER_API_KEY secret
- never use TRENDFORGE_ADMIN_API_KEY
- soft-skip before external scheduling is configured
- fail when post-window reliability verification reports a production failure

## Schedule customization warning

The verification schedules are aligned to the built-in R69.0 defaults:

    morning window ends 09:15 IST
    EOD window ends 16:15 IST

If operation time or grace_minutes is changed materially, GitHub post-window
workflow timing should be reviewed.

The backend live-contract dashboard will still expose missing verification even
if the external workflow schedule becomes stale.

## Audit client

Stdlib client:

    scripts/operations_audit.py

Usage:

    python scripts/operations_audit.py --expect morning
    python scripts/operations_audit.py --expect eod

It:

- requires HTTPS outside localhost
- rejects embedded URL credentials
- uses only the scheduler key
- validates scheduler-only auth scope
- validates broker_orders_allowed=false
- retries transient transport/server failures
- fails on missed/degraded/configuration-error states
- does not print the secret

## Webapp

New Monitor page:

    Scheduler Reliability

It provides:

- reliability window selector
- overall health
- measured reliability percentage
- measured/failed counts
- average completion delay
- external scheduler credential state
- per-operation reliability table
- manual admin audit
- audit-state filter
- audit ledger table
- CSV export
- explicit reliability semantics

Command Center adds a 30-day scheduler-reliability metric.

System diagnostics adds:

    /operations/reliability?days=30
    /operations/audit?limit=20

## Scope

R70.1 is operational observability and alerting only.

It does not enable live trading or change trading decisions.
