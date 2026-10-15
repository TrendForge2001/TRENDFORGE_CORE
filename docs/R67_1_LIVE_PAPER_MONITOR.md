# R67.1 Live Kite Quote Monitor and Automatic Paper Exits

R67.1 makes canonical paper positions self-monitoring.

## Scope

The release adds one application-scoped background monitor that:

- discovers currently open paper positions;
- reads live LTPs from the configured quote provider;
- prefers authenticated Kite when Kite credentials are present;
- feeds those LTPs into the existing PaperTradingService;
- therefore enforces the existing stop-loss, target and 15:00 IST force-exit rules;
- exposes monitor health and a manual diagnostic tick endpoint;
- never calls a broker order-placement endpoint.

## Fail-closed activation

The background monitor is disabled by default.

Enable it with:

```text
TRENDFORGE_PAPER_MONITOR_ENABLED=true
```

Optional timing:

```text
TRENDFORGE_PAPER_MONITOR_INTERVAL_SECONDS=15
TRENDFORGE_PAPER_MONITOR_IDLE_SECONDS=30
```

Values are clamped to safe bounds:

- active polling: minimum 5 seconds, maximum 300 seconds;
- idle polling: minimum 5 seconds, maximum 600 seconds.

Paper-trading activation remains separate:

```text
TRENDFORGE_PAPER_TRADING_ENABLED=true
TRENDFORGE_PAPER_TRADING_KILL_SWITCH=false
```

Real broker execution must remain separately disabled for paper validation:

```text
TRENDFORGE_LIVE_TRADING_ENABLED=false
```

## Canonical lifecycle

During FastAPI startup:

1. database migrations run;
2. persisted OPEN paper trades are restored;
3. the quote monitor is created;
4. the monitor background task starts only when explicitly enabled.

During shutdown:

1. the monitor is stopped and awaited;
2. the paper repository is closed.

## Quote source

`ProviderFactory.quote()` now uses this priority:

```text
explicit Kite instance
-> authenticated Kite runtime
-> explicit NSE instance
-> Yahoo fallback
```

Production therefore uses Kite for live paper-position LTP monitoring when the
daily Kite access token is valid.

## Safety behavior

A monitoring tick is all-or-nothing for the current open-position set.

If any open symbol is missing a usable live quote, that tick fails and no
partial set of positions is evaluated. This avoids closing only part of the
book from an incomplete quote payload.

Quote/auth failures are recorded in monitor health and retried on the next
scheduled tick.

The monitor continues to evaluate restored/open positions after 15:00 IST.
Because the existing PaperTradingRuntime gives the 15:00 force-exit rule
priority, the first successful quote after the cutoff closes the position with:

```text
FORCE_EXIT_15_00_IST
```

## Production endpoints

All are covered by the existing production admin-key boundary:

```text
GET  /paper/readiness
GET  /paper/monitor-runtime
POST /paper/monitor/tick
```

`/paper/readiness` now includes:

- `automatic_monitor`
- `automatic_monitor_start`

The monitor health contract includes:

- enabled / running / status
- quote_source
- active and idle intervals
- open symbols
- iterations
- quote successes / failures
- closed count
- last poll / success / error
- last quotes / closed positions
- broker_orders_allowed=false

## Current boundary

R67.1 automates quote monitoring and exit management only.

It does not create paper entries from scanner signals. That handoff belongs to
R67.2 so risk approval, duplicate prevention, sizing and execution audit can be
gated independently.
