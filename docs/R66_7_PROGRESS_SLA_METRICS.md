# R66.7 Progress Semantics and SLA Metrics

R66.7 removes ambiguity from universe-scan progress reporting introduced by
graceful time-budget degradation.

## Progress semantics

All percentages use the normalized unique universe size as the denominator.

- `accounted_pct` — symbols represented by a terminal result, including
  deferred symbols.
- `processed_pct` — symbols for which scanner execution actually ran.
- `successful_pct` — symbols completed without scanner error.
- `error_pct` — symbols represented by an error result.
- `deferred_pct` — symbols intentionally not executed because a time budget
  stopped the scan.
- `missing_pct` — symbols with no result before final accounting repair.

`completion_pct` is retained for backward compatibility only. It is now
explicitly accompanied by:

```text
completion_pct_semantics=legacy_alias_of_accounted_pct
progress_semantics_version=R66.7
```

Consumers should migrate from `completion_pct` to the explicit metric they
actually need.

For a healthy 50-symbol run:

```text
accounted_pct  = 100
processed_pct  = 100
successful_pct = 100
deferred_pct   = 0
```

For a 50-symbol run where one 25-symbol batch completes and the remainder is
deferred:

```text
accounted_pct  = 100
processed_pct  = 50
successful_pct = 50
deferred_pct   = 50
```

## Scan SLA metrics

The scale gate now reports:

- `scan_budget_utilization_pct`
- `scan_budget_headroom_sec` (signed)
- `scan_sla_met`
- `batch_sla_met`
- `sla_met`
- `sla_status` (`met` or `breached`)
- `max_batch_duration_sec`
- `avg_batch_duration_sec`
- `batch_budget_breach_count`
- `peak_batch_budget_utilization_pct`

A negative headroom value means the corresponding budget was exceeded.

## Per-batch SLA evidence

Each batch report includes:

- `sla_met`
- `budget_headroom_sec`
- `budget_utilization_pct`
- the existing duration and budget-exceeded flag

This makes it possible to distinguish one slow batch from a whole-scan budget
breach.

## Audit persistence

R66.4/R66.6 immutable audit metadata now persists the explicit progress
percentages and SLA evidence so post-run analysis does not depend on the live
API response.

## Compatibility

No scanner strategy, indicator, provider routing, provider circuit breaker,
enrichment, scoring, eligibility, or broker behavior changes in R66.7.
