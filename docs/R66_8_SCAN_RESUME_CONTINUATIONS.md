# R66.8 Scan Resume and Continuation Tokens

R66.8 turns an R66.6/R66.7 `partial` NIFTY 500 scan into a resumable,
auditable workflow.

## Partial response

When a time budget stops a universe scan and deferred symbols remain,
TrendForge persists those symbols in `scan_continuations` and returns an
opaque continuation token:

```text
outcome: partial

continuation:
  token: <opaque one-time token>
  status: pending
  parent_run_id: <partial run id>
  lineage_root_run_id: <first run in the chain>
  generation: 1
  symbol_count: <deferred count>
```

The raw token is returned only in the scan response and stored in the
continuation table. It is intentionally not copied into immutable audit
metadata.

The parent audit stores:

- the exact deferred-symbol list;
- lineage root;
- continuation generation for the current run;
- whether a next continuation exists.

## Resume request

Resume the same endpoint with a **new immutable run ID** and the token:

```text
POST /scan/universe/nifty500
     ?run_id=<new-run-id>
     &continuation_token=<token>
```

Only the persisted deferred symbols are selected. TrendForge validates that
every deferred symbol is still present in the current tradable NIFTY 500
universe before scanning.

Signal-defining inputs are inherited from the parent request:

- period
- interval
- capital
- top_n

Operational controls may be overridden explicitly on the continuation request:

- batch_size
- batch_pause_seconds
- scan_time_budget_seconds
- batch_time_budget_seconds
- compact

When an operational field is omitted, the parent value is inherited.

## One-time lifecycle

Continuation states are:

```text
pending -> active -> consumed
```

The claim from `pending` to `active` is an atomic SQLite update.

A successfully committed child run consumes the token. Replaying a consumed
token returns HTTP 409 and never re-executes the deferred symbols.

If the child scan fails before its terminal audit can commit, TrendForge rolls
the token back to `pending`. The same token can then be retried under a new
run ID.

An R66.3 single-flight overlap rejection does not consume the continuation.

## Chained partial runs

If a continuation run is itself partial:

1. the source token is consumed;
2. a new pending token is created for the newly deferred subset;
3. generation increments;
4. the lineage root remains the original run.

This supports bounded multi-step completion without mutating historical audit
records.

## Audit lineage

A continuation child audit records:

- `is_continuation=true`
- `parent_run_id`
- `lineage_root_run_id`
- `continuation_generation`
- deferred symbols and R66.7 progress/SLA metrics
- whether another continuation is available

The parent audit remains immutable.

Inspect continuation state and linked audit records with:

```text
GET /observability/scan-continuations/{token}
```

The inspection response does not echo the raw token.

## Storage boundary

Continuation state uses the same SQLite database as scan audits.

R66.2 durable storage remains deferred on the Render Free plan. Therefore a
pending continuation token is valid only while the current ephemeral database
survives. A Render redeploy, instance replacement, or filesystem reset can
remove pending tokens and their local audit history.

Do not treat continuation tokens as durable across deployments until R66.2 is
enabled on persistent infrastructure.

## Compatibility

R66.8 does not change:

- scanner indicators or strategy rules;
- R66.5 provider priority or circuit breakers;
- R66.6 time-budget enforcement;
- R66.7 progress/SLA semantics;
- enrichment, scoring, eligibility, or broker execution.
