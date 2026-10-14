# R66.11 Lineage Integrity and Orphan Detection

R66.11 adds read-only integrity diagnostics over the resumable scan lineage
introduced by R66.8-R66.10.

The goal is to distinguish a lineage that merely has a terminal status from a
lineage whose persisted audit and continuation references are internally
consistent.

## Integrity contract

Every lineage rollup now includes:

```text
integrity_status
integrity_issue_count
integrity:
  status
  valid
  issue_count
  error_count
  warning_count
  audit_record_count
  continuation_record_count
  executable_continuation_count
  issues[]
```

Status values are:

- `healthy` — no integrity findings.
- `warning` — no hard invariant is broken, but historical evidence is
  incomplete or has retention-related gaps.
- `unhealthy` — at least one hard lineage invariant is broken.

## Dedicated endpoint

```text
GET /observability/scan-lineages/{run_id}/integrity
```

The endpoint is read-only and accepts either the lineage root or a child run
ID. It returns the resolved root, current lineage status and integrity report.

## Hard invariants

R66.11 checks for:

- continuation root mismatch;
- missing continuation parent audit;
- parent/root mismatch;
- invalid or duplicate generations;
- parent/child generation mismatch;
- multiple simultaneously executable continuations;
- pending continuation retaining a child run;
- active continuation without a claimed child;
- consumed continuation without a child;
- consumed continuation whose child audit is missing;
- consumed child root/parent/generation mismatch;
- consumed continuation pointing to failed/rejected child outcome;
- child requested-symbol count differing from persisted continuation symbols;
- parent deferred-symbol set differing from continuation symbols;
- continuation attempt audit with missing parent;
- cumulative committed completed/processed counts exceeding the root universe.

Each issue has a stable code, severity and relevant run/generation context.

## Historical cleanup resilience

R66.9 intentionally cleans old consumed continuation rows after the retention
window. R66.10 originally depended on consumed continuation rows to reconstruct
the committed path.

R66.11 also reconstructs committed history from immutable continuation child
audits with:

```text
is_continuation=true
outcome in {completed, partial}
```

Therefore deleting an old consumed continuation row no longer erases historical
completion from a lineage rollup.

If an immutable continuation audit remains but its continuation row has already
been cleaned, integrity reports:

```text
CONTINUATION_RECORD_ABSENT
severity=warning
```

The lineage remains valid and its committed completion metrics remain intact.

## Diagnostic-only policy

R66.11 never repairs, deletes or mutates audit/continuation state.

The batch only:

- reads existing immutable audit rows;
- reads current continuation rows;
- computes integrity diagnostics;
- exposes stable issue codes.

Any future repair workflow must be a separate explicitly gated release.

## Compatibility

R66.11 does not change:

- scanner execution;
- strategy or indicators;
- provider routing or R66.5 circuit breakers;
- R66.6 time budgets;
- R66.7 progress/SLA semantics;
- R66.8 continuation execution;
- R66.9 TTL/cleanup/claim guardrails;
- R66.10 lineage status definitions;
- enrichment, scoring, eligibility or broker execution.

R66.2 durable storage remains deferred on Render Free.
