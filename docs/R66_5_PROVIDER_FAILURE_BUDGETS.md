# R66.5 Provider Failure Budgets and Circuit Breakers

R66.5 protects full-universe scans from repeated upstream failure storms while
preserving the production routing order:

```text
Kite primary
-> NSE symbol validation/resolution for Kite failures
-> Yahoo backup only for unresolved symbols
```

## Router circuit breaker

Each candle provider has an application-scoped circuit breaker.

- consecutive systemic batch-failure threshold: **2**
- open-circuit cooldown: **120 seconds**
- circuit state survives individual scan runs
- per-run counters/events reset at the start of each universe scan
- provider authentication failures are never converted into fallback traffic

Systemic failures include rate limits, access blocks, connection/time-out
failures, and upstream HTTP 502/503/504 responses. Symbol-specific conditions
such as an unknown broker instrument do not consume the provider failure
budget.

While a circuit is open, TrendForge records a skip and moves to the next
configured provider instead of calling the degraded upstream again.

## Yahoo protection

Yahoo remains backup-only.

- HTTP 429 / Too Many Requests starts a **180 second** Yahoo cooldown.
- 429 and active-cooldown errors are not retried internally.
- skipped requests do not extend the existing cooldown.
- router circuit state provides a second protection layer across scan batches.

## NSE resolver protection

NSE keeps its existing provider cooldowns:

- HTTP 429: **120 seconds**
- HTTP 401/403 access block: **900 seconds**
- failed-symbol lookup pacing: **1.5 seconds** between live lookups

R66.5 checks cooldown state before applying the 1.5-second pace, so an already
blocked NSE session returns immediately instead of sleeping for a request that
will be rejected.

For other systemic resolver failures, each scanner batch has a budget of
**2 live NSE resolution failures**. Remaining failed symbols skip NSE
resolution and continue to Yahoo backup.

## Observability

Universe scan responses now expose:

- `circuit_skip_count`
- `nse_resolver_attempts`
- `nse_resolver_skips`
- `circuit_breakers`

The full provider observability payload also includes `circuit_events`.

`GET /health` exposes current provider circuit state and provider-specific
cooldown state.

R66.4 audit metadata persists the circuit snapshot/counters for completed and
failed universe runs.

No strategy, indicator, scoring, enrichment, eligibility, or broker-order
logic is changed by R66.5.
