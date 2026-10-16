# R68.7 Alerts, Discord Notification Center and Event Routing

R68.7 introduces one canonical Discord-only event-routing boundary for TrendForge.

## Audit finding

Before R68.7 the repository contained three disconnected legacy concepts:

- AlertRepository writing the narrow alerts_log table
- DiscordService reading config/alerts.json
- NotificationManager supporting Discord/email/console

None was composed into the canonical FastAPI application.

The legacy Discord config also kept webhook_url blank while the production runtime already exposed the DISCORD_WEBHOOK environment secret.

R68.7 fixes that composition gap without deleting the legacy helpers.

## Runtime secret boundary

The canonical DiscordService resolves the webhook in this order:

1. explicit injected webhook
2. config.settings.DISCORD_WEBHOOK
3. legacy config/alerts.json webhook_url

The runtime secret is never returned from:

- /notifications/readiness
- /notifications/summary
- /notifications/events
- DiscordService.health()

Health reports only configured/enabled state.

## Canonical event store

R68.7 adds:

    notification_events

Each row stores:

- event_id
- event_type
- category
- severity
- optional symbol
- title
- message
- source
- channel
- status
- dedupe_key
- payload JSON
- error
- created timestamp
- sent timestamp
- updated timestamp

The legacy alerts_log table remains unchanged.

## API contracts

Read-only:

    GET /notifications/readiness
    GET /notifications/summary
    GET /notifications/events
    GET /notifications/events/{event_id}

Admin protected:

    POST /notifications/events
    POST /notifications/test

Example event:

    {
      "event_type": "scanner_pick",
      "category": "scanner",
      "severity": "SUCCESS",
      "title": "TCS Scanner Alert",
      "message": "TCS qualified for review.",
      "symbol": "TCS",
      "source": "scanner",
      "payload": {
        "score": 94
      },
      "deliver": true
    }

## Categories

Canonical categories:

- scanner
- paper
- risk
- system
- intelligence
- market
- portfolio

Canonical severities:

- INFO
- SUCCESS
- WARNING
- ERROR
- CRITICAL

The service also exposes convenience routing methods for scanner, paper, risk and system producers.

R68.7 does not automatically retrofit every existing producer to send messages. It establishes the canonical event ingress and transport contract first so future producer wiring uses one boundary.

## Delivery statuses

recorded

The event is persisted but no network delivery was requested.

sent

Discord accepted the webhook request.

failed

Discord/network delivery was attempted and failed.

blocked

Delivery was requested but Discord is disabled or not configured.

suppressed

An equivalent event already succeeded or was recorded inside the cooldown window.

## Dedupe and cooldown

Default cooldown:

    15 minutes

Override:

    TRENDFORGE_ALERT_COOLDOWN_MINUTES

Range:

    0..1440 minutes

If a producer supplies a dedupe_key, that key is used directly.

Otherwise TrendForge derives SHA-256 from:

    category | event_type | symbol | title | message

Only recent sent or recorded events suppress a duplicate.

failed and blocked events remain retryable.

A suppressed row records duplicate_of in its payload evidence.

## Discord transport

The Discord transport supports:

- severity-based embed colors
- title and message
- category/event/source fields
- optional symbol field
- UTC timestamp
- event ID in the footer

It keeps the legacy scanner-style send interface for compatibility.

## Webapp

The Notification Center page provides:

- Discord readiness/configured state
- persisted event count
- cooldown
- admin-gated Discord test
- manual event routing
- record-only mode
- category/severity selection
- optional symbol and dedupe key
- sent/recorded/suppressed/blocked/failed metrics
- category distribution
- event-history filtering
- event detail
- CSV export

Command Center shows Discord readiness and delivery counters.

System diagnostics exposes readiness and summary contracts.

## Safety and scope

R68.7:

- is Discord-only
- does not add email routing
- does not add WhatsApp routing
- never returns the Discord webhook secret
- does not place broker orders
- does not create paper positions
- does not change scanner eligibility/scoring
- does not trigger notifications from GET requests
- protects all notification mutations with the admin key

The notification_events store uses SQLite and therefore inherits the current Render ephemeral-storage limitation until durable storage is enabled.
