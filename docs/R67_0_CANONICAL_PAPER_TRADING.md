# R67.0 Canonical Paper Trading API and Safety Gate

R67.0 promotes the existing tested paper-trading runtime into the canonical
production FastAPI application used by Render.

## Why this batch exists

Before R67.0, paper-trading routes lived only in `api/scan_api.py`, while
Render starts:

```text
uvicorn start:app
start.py -> api.app:app
```

Therefore the production R66 service did not expose the legacy paper endpoints.

R67.0 wires paper trading into `api.app` and the canonical
`ApplicationFactory`.

## Production endpoints

```text
GET  /paper/readiness
GET  /paper
POST /paper/open
POST /paper/monitor
POST /paper/kill-switch
```

In production, all `/paper` routes require the existing
`X-TrendForge-Admin-Key`.

Paper-trading routes do not require persistent storage because they never place
broker orders. On the Render Free plan, however, the SQLite paper history and
open-position restore state may disappear on redeploy or instance replacement.

## Fail-closed activation

New paper entries require both:

```text
TRENDFORGE_PAPER_TRADING_ENABLED=true
TRENDFORGE_PAPER_TRADING_KILL_SWITCH=false
```

Defaults are:

```text
enabled=false
environment kill switch=true
```

A new deployment therefore cannot begin opening simulated positions merely
because the R67.0 code is present.

The runtime kill switch can be enabled through the API and blocks new entries.
An environment kill switch cannot be disabled through the API.

## Paper-only guarantee

The canonical service reports:

```text
mode=paper_only
broker_orders_allowed=false
```

R67.0 never invokes a Kite broker order-placement endpoint.

Live broker execution remains controlled separately by the existing
`TRENDFORGE_LIVE_TRADING_ENABLED` flag and is not enabled by this release.

## Existing runtime behavior retained

R67.0 reuses the existing `PaperTradingRuntime`, including:

- persistence in `trade_history`;
- restore of OPEN paper trades at process startup;
- side-aware P&L;
- stop-loss exits;
- target exits;
- no entries outside 09:15-15:00 IST on weekdays;
- automatic force-exit semantics at/after 15:00 IST when monitored.

## Lifecycle

During canonical API startup:

1. database migrations run;
2. paper service is constructed;
3. persisted OPEN paper trades are restored;
4. restore result is exposed through `/paper/readiness`.

During shutdown, the trade repository connection is closed.

## Current limitation

R67.0 is an authenticated manual/supervised paper execution surface. It does
not yet create an autonomous monitoring loop and it does not automatically
convert scanner signals into paper orders.

Those are separate production gates:

- R67.1: live Kite quote monitor + timed 15:00 force-exit loop;
- R67.2: risk-governed scanner-signal -> paper-order handoff;
- R67.3: Discord paper execution alerts and session report.

## Free-plan storage

R66.2 durable storage remains deferred.

Paper positions and history are therefore not guaranteed to survive a Render
redeploy or instance replacement. This is acceptable for initial supervised
paper validation, but not for unattended multi-day paper sessions.
