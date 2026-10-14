# R66.9 Continuation Expiry, Cleanup and Abuse Guardrails

R66.9 bounds the lifecycle introduced by R66.8 so continuation state cannot
remain usable or accumulate indefinitely.

## Production policy

Default continuation guardrails are:

- token TTL: **3600 seconds (60 minutes)**
- stale active recovery: **1200 seconds (20 minutes)**
- maximum continuation generation: **4**
- maximum claim attempts per token: **3**
- expired-row retention before cleanup: **86400 seconds (24 hours)**

The 20-minute stale-active threshold is intentionally longer than the maximum
R66.6 scan budget of 15 minutes, so a valid in-flight scan is not recovered
prematurely.

## Expiry

Each continuation stores `expires_at`.

A pending token past its expiry cannot be inspected for execution or claimed.
A resume attempt returns HTTP **410 Gone** and is immutably audited as:

```text
outcome       = rejected
failure_stage = continuation_expiry
http_status   = 410
```

The scanner and universe loader are not invoked.

Expired rows remain observable during the cleanup retention window.

## Claim-attempt budget

Each atomic `pending -> active` claim increments `claim_attempts`.

Failed child execution may restore the token to `pending`, but it does not
reset the attempt counter. After the configured maximum is reached, further
resume attempts return HTTP **410 Gone** and are audited with:

```text
failure_stage = continuation_attempt_limit
```

This prevents a repeatedly failing token from being retried indefinitely.

## Maximum chain depth

Continuation generations are bounded at **4**.

If a generation-4 continuation runs and is still partial:

- the generation-4 source token is consumed normally;
- the partial child audit remains valid and immutable;
- no generation-5 token is created;
- the response includes `continuation_limit.reason=maximum_generation_reached`;
- the audit records `next_continuation_available=false`.

The scan result is not converted into a failure merely because the continuation
chain reached its safety limit.

## Stale active recovery

A token can remain `active` if a process disappears after claim but before
normal rollback or consume logic executes.

Maintenance safely returns an active token to `pending` only when:

- its claim age exceeds the stale-active threshold; and
- the token itself has not expired.

Recovery increments `recovery_count` and records `last_recovered_at`.
It does not reset `claim_attempts`.

## Cleanup

Maintenance deletes expired `pending` and `consumed` rows after the
configured retention window.

An expired `active` row is deleted only after the active claim is also stale.
This prevents cleanup from removing a recently claimed record merely because
its TTL boundary passed during a legitimate child run.

## Health and observability

`/health` continuation observability adds:

- token_ttl_seconds
- stale_active_seconds
- max_generation
- max_claim_attempts
- cleanup_retention_seconds
- expired_records
- exhausted_pending
- stale_active
- maintenance_last
- maintenance_totals

Continuation inspection exposes effective state and remaining claim attempts
without echoing the token itself.

## Storage boundary

R66.2 durable storage remains deferred while TrendForge uses the Render Free
plan. R66.9 bounds and cleans the current SQLite state, but it does not make
that state durable across Render instance replacement or filesystem reset.

## Compatibility

R66.9 does not change:

- R66.3 single-flight scan admission;
- R66.4 immutable audit identity;
- R66.5 provider circuit breakers;
- R66.6 time-budget enforcement;
- R66.7 progress/SLA semantics;
- R66.8 deferred-symbol resume behavior;
- indicators, strategy, scoring, enrichment, eligibility or broker execution.
