# R66.10 Continuation Lineage Rollup and End-to-End Completion

R66.10 adds an operational view over R66.8/R66.9 continuation chains.

A resumable scan may span multiple immutable audit rows. The lineage rollup
answers whether the original scan eventually finished, how much work remains,
and which attempts actually belong to the committed continuation path.

## Endpoint

```text
GET /observability/scan-lineages/{run_id}
```

The supplied run ID may be either the root run or any audited child/attempt.
TrendForge resolves the lineage root automatically.

## Lineage states

The rollup reports one of:

- `completed` — committed continuation path completed the root workload.
- `resumable` — a pending continuation can resume remaining symbols.
- `in_progress` — a continuation is currently active.
- `blocked` — continuation is expired, claim-limited, or maximum generation
  has been reached while work remains.
- `failed` — latest committed run failed and no resumable continuation exists.
- `rejected` — root/latest committed run was rejected.
- `partial` — work remains but no stronger continuation state is available.

## Committed path versus attempts

R66.4 preserves every immutable attempt, including failed child attempts and
consumed-token replay rejections.

R66.10 distinguishes:

- `committed_runs` — root plus child runs referenced by consumed continuation
  records.
- `attempt_runs` — every audited run in the lineage, including failed/rejected
  attempts.

Only committed runs contribute to end-to-end completion counters. This avoids
double-counting work when a failed continuation is retried under a new run ID.

## Aggregate progress

The rollup reports:

- root_requested_symbols
- cumulative_completed_symbols
- cumulative_processed_symbols
- remaining_symbols
- end_to_end_completion_pct
- end_to_end_processed_pct
- committed_run_count
- attempt_run_count
- continuation_count

For a 50-symbol root that processes 25 and later resumes/completes the remaining
25:

```text
root_requested_symbols        = 50
cumulative_completed_symbols  = 50
remaining_symbols             = 0
end_to_end_completion_pct     = 100
status                        = completed
```

## Aggregate operational evidence

The rollup also includes:

- cumulative_scan_duration_sec
- end_to_end_elapsed_sec
- lineage_sla_status
- fallback_count
- nse_resolution_count
- latest committed run/outcome
- continuation generation/status/attempt information

A lineage can be operationally `completed` while its `lineage_sla_status`
remains `breached` if an earlier committed partial run exceeded its budget.
Completion and SLA compliance are intentionally separate.

## Continuation expiry semantics

Consumed continuation records remain historical evidence after their token TTL
passes. Expiry only blocks a continuation that is still pending for execution.
A completed lineage never regresses to `blocked` merely because its consumed
token later ages past the R66.9 TTL.

## Storage boundary

R66.10 is a read-only rollup over existing immutable audits and continuation
state. It adds no new database tables.

R66.2 durable storage remains deferred on Render Free, so lineage history still
shares the existing ephemeral SQLite durability boundary.

## Compatibility

R66.10 does not change:

- scanner strategy or indicators;
- provider routing or R66.5 circuit breakers;
- R66.6 time budgets;
- R66.7 progress/SLA semantics;
- R66.8 continuation execution;
- R66.9 TTL/cleanup/abuse guardrails;
- enrichment, scoring, eligibility or broker execution.
