# R67.2 Risk-Governed Scanner Signal to Paper Entry

R67.2 connects completed NIFTY 500 scanner results to the canonical paper-trading runtime.

## Scope

The release adds an explicit, fail-closed scanner-to-paper handoff.

A paper entry can occur only when all of the following are true:

1. production paper trading is enabled;
2. the paper kill switch is open;
3. R67.2 auto-entry is enabled by environment;
4. the individual scan request explicitly asks for paper auto-entry;
5. the scan finishes with outcome `completed`;
6. the scan is not a continuation/resume child;
7. the scanner candidate is eligible;
8. the final signal is in the configured auto-entry signal allowlist;
9. score and confidence meet minimum thresholds;
10. stop/target geometry is valid;
11. reward/risk meets the configured minimum;
12. position sizing produces a positive quantity;
13. the maximum-open-position limit is not reached;
14. the symbol is not already open;
15. the symbol has not already been traded that IST date;
16. the daily realized-loss circuit breaker has not been reached;
17. the request occurs inside the 09:15-15:00 IST paper-entry window.

The service is long-only in R67.2. It accepts only scanner BUY-family signals from the allowlist and emits BUY paper orders.

## Fail-closed activation

The feature defaults OFF:

```text
TRENDFORGE_PAPER_AUTO_ENTRY_ENABLED=false
```

Even when enabled globally, each universe scan must also explicitly include:

```json
{
  "paper_auto_entry": true
}
```

This two-key activation prevents ordinary scanner requests from creating paper positions.

## Default risk policy

```text
TRENDFORGE_PAPER_CAPITAL=100000
TRENDFORGE_PAPER_RISK_PER_TRADE_PERCENT=1.0
TRENDFORGE_PAPER_MAX_DAILY_LOSS_PERCENT=3.0
TRENDFORGE_PAPER_MAX_OPEN_POSITIONS=5
TRENDFORGE_PAPER_MAX_CAPITAL_PER_TRADE_PERCENT=20.0
TRENDFORGE_PAPER_MINIMUM_RR=2.0
TRENDFORGE_PAPER_AUTO_ENTRY_MIN_SCORE=90.0
TRENDFORGE_PAPER_AUTO_ENTRY_MIN_CONFIDENCE=60.0
TRENDFORGE_PAPER_AUTO_ENTRY_MAX_PER_SCAN=1
TRENDFORGE_PAPER_AUTO_ENTRY_SIGNALS=STRONG BUY,BUY
```

Position quantity is the smaller of:

- risk-budget quantity, using configured capital and risk percentage;
- capital-cap quantity, using configured maximum capital per trade.

The scanner's own suggested quantity is retained as evidence but is not trusted as the production paper sizing authority.

## Daily loss circuit breaker

Paper entries now persist an explicit IST entry timestamp.

The trade repository exposes:

- net realized P&L for entries on an IST date;
- gross realized loss for entries on an IST date;
- whether a symbol was already traded on that date.

The daily loss guard uses **gross realized losses**, not net P&L. Profitable trades therefore do not erase prior realized losses for the purpose of the daily loss circuit breaker.

Because current TrendForge paper positions are intraday and force-exited at 15:00 IST, grouping by entry date is a valid session boundary for R67.2.

## Completed-scan rule

R67.2 will not execute from a partial scan.

It also will not execute from a continuation child, even if that child completes, because a continuation represents only the previously deferred subset and its ranking is not equivalent to a complete fresh universe ranking.

A fresh completed scan is required for automatic paper entry.

## Production security

R67.2 makes `POST /scan/universe/nifty500` an admin-key-protected production route.

Production callers must provide:

```text
X-TrendForge-Admin-Key
```

This protects both the execution-capable scan path and the expensive full-universe resource boundary.

Non-production test/dev applications are unchanged unless wrapped by the production security layer.

## Observability

New endpoint:

```text
GET /paper/auto-entry/readiness
```

Application health includes:

```text
execution.paper_auto_entry
```

The service reports:

- enabled/status
- paper_only=true
- broker_orders_allowed=false
- allowed signals
- score/confidence thresholds
- capital and sizing limits
- reward/risk threshold
- max entries per scan
- processed scan count
- execution attempts
- opened/rejected counts
- last run and last status

When `paper_auto_entry=true`, the universe scan response includes a `paper_auto_entry` execution report.

## Safety boundary

R67.2 does not call Kite order-placement APIs.

The canonical execution path remains:

```text
Scanner
-> R67.2 risk gate
-> PaperTradingService
-> SQLite paper trade
-> R67.1 Kite LTP monitor
-> SL / target / 15:00 simulated exit
```

Real broker execution remains separately controlled by:

```text
TRENDFORGE_LIVE_TRADING_ENABLED=false
```

and must remain false for R67 paper validation.

## Initial production rollout

R67.2 should first be deployed with:

```text
TRENDFORGE_PAPER_AUTO_ENTRY_ENABLED=false
```

Validate readiness and security first.

Then during an NSE session:

1. refresh the daily Kite access token;
2. verify R67.1 monitor is running;
3. enable R67.2 auto-entry;
4. run a deliberately small, fresh completed scan with `paper_auto_entry=true`;
5. permit at most one paper entry;
6. verify quantity, entry, stop, target, and auto-monitor state;
7. verify no real broker order was created;
8. verify automatic exit behavior.

## Current storage limitation

R66.2 durable storage remains deferred on Render Free.

Paper entries and daily risk history can disappear on redeploy or instance
replacement. Production entry now requires verified persistent storage in
addition to all R67.2 gates. An operator may explicitly enable supervised,
disposable paper simulation with
`TRENDFORGE_PAPER_ALLOW_EPHEMERAL_SIMULATION=true` (default false). This never
enables paper trading or bypasses kill/risk controls, does not affect fundamental
administrative write guards, and makes no durability claim. Local development
remains local simulation.

`/paper/readiness.entry_storage_policy` describes this boundary, while
`can_open_new_positions` combines storage, enable and kill-switch admission.
The UI disables paper-entry toggles when admission is unavailable and strips
stale enabled toggle state from submitted scan requests. Scanning and paper
preview remain available without creating positions. Monitoring, exits and kill
controls are retained even when new entries are blocked.
