# R68.8 Scanner, Paper, Risk and System Notification Producers

R68.8 wires real TrendForge producer outcomes into the canonical R68.7 Discord Notification Center.

## Non-interference contract

Notifications are observational.

A notification failure must never change:

- scanner outcome
- scanner HTTP status
- paper-open outcome
- paper-close outcome
- kill-switch state
- auto-entry decision
- quote-monitor exception semantics

The producer bridge catches Notification Center exceptions and exposes them only through producer health.

## Producer health

Read-only:

    GET /notifications/producers

Health includes:

- best_effort
- max_scan_picks
- attempted
- emitted
- failures
- last_event_at
- last_error
- last_result

No new notification mutation API is introduced in R68.8.

## NIFTY 500 scanner

The canonical endpoint:

    POST /scan/universe/nifty500

now invokes the producer bridge after the immutable scan audit is committed and before compact response projection.

Every successful/partial run records:

    scanner_completed
    scanner_partial

respectively.

Run summaries are record-only.

For outcome=completed, the bridge can deliver the first execution-eligible picks to Discord.

Default cap:

    3 picks

Override:

    TRENDFORGE_NOTIFICATION_MAX_SCAN_PICKS

Range:

    0..20

Partial scans do not deliver pick alerts.

Each pick is deduped by run_id + symbol.

The scan response exposes:

    notification_dispatch

for operational visibility.

Scanner ValueError failures preserve HTTP 422 and emit scanner_failed best-effort.

Unexpected scan failures preserve HTTP 503 and emit scanner_failed best-effort.

Duplicate/admission/continuation protocol rejections retain their existing HTTP semantics and are not treated as scanner engine failures.

## Paper trading

PaperTradingService emits:

    paper_position_opened
    paper_position_closed
    paper_kill_switch_enabled
    paper_kill_switch_disabled
    paper_entry_blocked

Open/close events are Discord-delivered.

Closed runtime rows now include trade_id so open/close dedupe can use stable trade identity.

A repeated set_runtime_kill_switch call that does not change state does not emit another producer event.

Manual open attempts blocked by disabled paper trading or an active kill switch emit a risk event before the existing exception is re-raised.

Paper events include:

    paper_only: true

and never imply a live broker order.

## Paper auto-entry risk

PaperAutoEntryService emits a record-only:

    paper_auto_entry_evaluated

for every processed request path, including disabled, blocked, no-entry and executed outcomes.

Only two candidate risk guards automatically deliver Discord risk alerts:

    maximum_daily_loss_reached
    maximum_open_positions_reached

This is deliberate noise control.

Routine candidate rejections such as low score, low confidence, duplicate symbol, invalid risk geometry, reward/risk threshold, or outside entry window remain visible in auto-entry evaluations but do not become Discord alerts.

A process-level:

    paper_trading_not_ready

block also produces a warning risk event.

## Paper quote monitor

A quote/auth/provider failure preserves the original monitor exception and also emits:

    paper_monitor_failed

as a deduplicated system ERROR event.

Notification failure cannot replace or mask the original quote-monitor error.

## Startup/system producers

During FastAPI lifespan:

- restored paper positions are recorded as paper_restore_completed only when restored count > 0;
- paper restore failure delivers paper_restore_failed;
- quote-monitor start failure delivers paper_monitor_start_failed.

Startup notification delivery is best-effort. The application remains governed by the existing startup/lifespan behavior.

## Webapp

Notification Center now displays:

- producer status
- producer attempts
- producer failures
- scanner pick cap
- latest producer error

Command Center includes producer failure count.

System diagnostics includes:

    /notifications/producers

## Discord/noise policy

Automatic Discord delivery is limited to events where immediate operator awareness is useful:

- execution-eligible completed-scan picks
- paper opens
- paper closes
- paper kill-switch changes
- manual paper-entry risk blocks
- daily-loss guard
- max-open-positions guard
- quote-monitor failure
- startup paper/monitor failures

Run summaries, successful restore evidence and auto-entry evaluation summaries are record-only.

## Safety

R68.8:

- does not add WhatsApp
- does not add email
- does not expose Discord secrets
- does not change scanner scoring
- does not change execution eligibility
- does not enable live trading
- does not place broker orders
- does not make notification success a prerequisite for primary operations
