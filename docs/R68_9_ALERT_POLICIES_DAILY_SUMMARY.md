# R68.9 Alert Policies, Routing Preferences and Daily Discord Summary

R68.9 adds policy-controlled delivery and an optional end-of-day Discord digest on top of the canonical R68.7/R68.8 Notification Center.

## Design rules

The notification layer remains observational.

R68.9 does not change:

- scanner scoring
- execution eligibility
- paper order decisions
- live broker-order permissions
- risk-engine decisions

A notification-policy or Discord failure cannot convert a successful primary operation into a failed scanner or paper-trading operation.

## Policy persistence

Policy is stored as namespaced JSON in the existing SQLite settings table:

    notifications.policy.r68_9

No new migration/table is introduced.

Built-in defaults apply when no stored policy exists.

The existing Render SQLite durability limitation still applies. Durable preferences require durable backend storage.

## Policy API

Read:

    GET /notifications/policy

Admin mutations:

    PUT /notifications/policy
    DELETE /notifications/policy

DELETE resets to built-in defaults by removing the stored override.

## Default policy

Global delivery:

    enabled

Categories:

    scanner      enabled, minimum INFO
    paper        enabled, minimum INFO
    risk         enabled, minimum WARNING
    system       enabled, minimum WARNING
    intelligence enabled, minimum WARNING
    market       enabled, minimum WARNING
    portfolio    enabled, minimum WARNING

Quiet hours:

    disabled
    22:00-07:00 Asia/Kolkata
    CRITICAL pass-through enabled

Daily summary:

    disabled
    time 18:30 IST
    skip empty true
    notable limit 10

## Routing semantics

Policy is evaluated only when deliver=true.

Record-only events are always retained.

A policy-rejected delivery is persisted as:

    status = filtered

with:

    policy_filtered = true
    policy_reason
    policy_version

Filtered events never call Discord.

Filtered, blocked and failed events do not poison the cooldown dedupe window.

Policy is evaluated before cooldown suppression so a newly disabled category is visibly filtered rather than hidden as a cooldown duplicate.

Explicit /notifications/test delivery bypasses policy. This is intentional so an operator can test the Discord transport even when normal delivery is disabled.

## Quiet hours

Quiet-hours calculations use:

    Asia/Kolkata

The interval supports both same-day and cross-midnight windows.

Example:

    22:00 -> 07:00

means 22:00 through midnight and midnight through 06:59.

When allow_critical=true, CRITICAL messages may pass through quiet hours. Other severities are persisted as filtered.

## Daily summary API

Readiness:

    GET /notifications/daily-summary/readiness

Preview:

    GET /notifications/daily-summary/preview
        ?summary_date=YYYY-MM-DD

Manual/admin send:

    POST /notifications/daily-summary/send

Body:

    {
      "summary_date": "2026-10-16",
      "force": false
    }

summary_date may be null for today in Asia/Kolkata.

## Daily summary evidence

The digest is built only from canonical notification_events evidence inside the selected Asia/Kolkata calendar date.

It reports:

- total event count
- sent/recorded/filtered/suppressed/blocked/failed distribution
- category distribution
- severity distribution
- event-type distribution
- scanner-pick count
- paper-open count
- paper-close count
- risk-event count
- delivery-issue count
- bounded notable-event evidence

daily_discord_summary events themselves are excluded from their own source evidence.

## Delivery semantics

The daily summary must be explicitly enabled in policy.

The global delivery_enabled switch remains authoritative.

After those gates pass, the digest intentionally bypasses per-category minimum severity and quiet hours. This allows a user-selected digest time to work even if the system category minimum is ERROR or the selected time falls in quiet hours.

Successful daily summary identity:

    daily-summary:YYYY-MM-DD

A successfully sent digest is not automatically sent again that day.

blocked, failed and interrupted recorded-but-unsent digest attempts remain retryable.

force=true uses a unique dedupe key for an explicit operator resend.

## Dependency-free scheduler

R68.9 does not use the legacy APScheduler utilities because APScheduler is not part of the locked production dependency graph.

The canonical daily-summary worker uses asyncio.

Runtime defaults:

    worker enabled
    poll interval 60 seconds

Environment controls:

    TRENDFORGE_NOTIFICATION_SUMMARY_WORKER_ENABLED
    TRENDFORGE_NOTIFICATION_SUMMARY_POLL_SECONDS

The worker itself can run while the daily-summary policy is disabled. In that state it performs no Discord delivery. This allows a stored policy change to enable the digest without a service restart.

The scheduler polls the current persisted policy on every tick.

## Scheduler recovery

The worker records:

- running status
- iterations
- last poll
- last attempted local date
- last result
- last error

Unexpected tick errors are caught inside the worker loop so one SQLite/policy/summary failure does not terminate the background task.

## Security

Admin protected:

    PUT /notifications/policy
    DELETE /notifications/policy
    POST /notifications/daily-summary/send

Read-only:

    GET /notifications/policy
    GET /notifications/daily-summary/readiness
    GET /notifications/daily-summary/preview

No webhook secret is returned.

## Webapp

Notification Center adds:

- global Discord delivery switch
- per-category enable/disable
- per-category minimum severity
- IST quiet-hours controls
- CRITICAL quiet-hours override
- daily-summary enable/disable
- summary time
- skip-empty preference
- notable-event limit
- daily preview
- manual daily-summary send
- policy reset
- filtered-event metric/filter

Command Center shows daily-summary state.

System diagnostics exposes policy, daily-summary runtime and preview.

## Scope

R68.9 is Discord-only.

It does not add:

- WhatsApp
- email
- live broker execution
- APScheduler
- scanner/risk score changes
- new database tables
- Render manifest changes
