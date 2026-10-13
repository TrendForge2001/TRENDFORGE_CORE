# R66.6 Scan Time Budgets and Graceful Degradation

R66.6 bounds long-running universe scans without force-cancelling in-flight
provider work.

## Default production budgets

- whole NIFTY 500 scan budget: **450 seconds**
- individual scanner batch budget: **60 seconds**
- normal batch size remains **25**
- normal inter-batch pause remains **1 second**

The 450-second default is intentionally above the current full-universe
production baseline while still placing a finite ceiling on runaway scans.

## Safe enforcement model

Budgets are enforced at **batch boundaries**.

TrendForge never attempts to terminate a running Python thread or interrupt a
live Kite/NSE/Yahoo request. If a batch crosses its batch budget, that batch is
retained and the scan stops before launching the next batch.

The same rule applies to the whole-scan deadline. This is a soft deadline with
safe boundary enforcement, not unsafe asynchronous cancellation.

## Partial result contract

When remaining symbols are skipped because of a time budget, the HTTP request
still returns a structured response with:

- `outcome=partial`
- `time_budget_exhausted=true`
- `processed_symbols`
- `processed_pct`
- `deferred_symbols`
- `deferred_symbol_count`
- `time_budget_stop_reason`
- `time_budget_stop_batch`
- configured scan/batch budgets
- completed batch reports

Deferred symbols are explicitly accounted for with
`time_budget_deferred:<reason>` error evidence. This keeps the universe
accounting closed while distinguishing symbols that were not actually
processed.

## Runtime observability

`GET /observability/scan-runtime` exposes:

- configured scan and batch budgets
- absolute UTC deadline
- elapsed scan time
- remaining budget seconds

The internal monotonic deadline is never exposed.

## Audit

R66.4 immutable scan audits now accept a fourth terminal outcome:

- `completed`
- `partial`
- `failed`
- `rejected`

A budget-limited scan is stored as `partial`, HTTP status 200,
`failure_stage=time_budget`, with stop reason, processed count and deferred
count in metadata.

## Provider behavior

R66.5 provider routing and circuit breakers are unchanged:

Kite primary -> NSE symbol resolution -> Yahoo backup.

Time budgets do not change provider priority or circuit thresholds.

## Validation

Production validation should use two gates:

1. healthy gate with normal budgets, proving no regression;
2. controlled low-budget gate, proving partial return, audit persistence and
   guard cleanup without intentionally degrading any provider.
