# R72.5.6 — Persistent Strategy Runtime & Restart Reconciliation

R72.5.6 hardens the completed R72.5 strategy stack for Render instance
replacement and process restarts.

The five core strategy batches are already complete:

1. R72.5.1 — Strategy Registry & Indicator Completion
2. R72.5.2 — Multi-Strategy NIFTY Scanner Engine
3. R72.5.3 — Multi-Strategy Backtest & Strategy Validation
4. R72.5.4 — Strategy-Driven Paper Trading
5. R72.5.5 — Strategy Paper Monitoring, Exit Signals & Performance Attribution

R72.5.6 is the persistence/reconciliation hardening layer over those five
batches. It does not change strategy rules, scores or live-trading permissions.

## Problem closed by this batch

Before R72.5.6, three important pieces of runtime state were instance-local:

- the latest R72.5.2 scanner result used by R72.5.4;
- the latest R72.5.3 validation eligibility state;
- the R72.5.4 duplicate execution lineage guard.

Render instance replacement could therefore require a fresh scan/validation and
could erase the in-memory duplicate guard.

## Persistent storage

R72.5.6 adds the SQLite table:

`strategy_runtime_state`

It stores JSON payloads by immutable or well-known keys.

Current keys include:

- `r72.5.latest_scanner`
- `r72.5.scanner:<scan_run_id>`
- `r72.5.latest_validation`
- `r72.5.validation:<validation_run_id>`
- `r72.5.execution:<scan_run_id>:<validation_run_id>:<strategy_id>`

The exact scanner and validation run records allow an open strategy paper
position to be reconciled against the lineage that actually created it.

## Scanner restart behavior

The R72.5.2 scanner now prefers a persisted SQLite snapshot when it starts.

The previous `/tmp` JSON snapshot remains only as a same-instance cache and
fallback. A completed scanner run writes both the latest pointer and its
versioned run record to SQLite.

Viewing scanner results still never starts a scan.

## Validation restart behavior

A completed R72.5.3 validation now persists both:

- latest completed validation; and
- exact validation run ID.

After application restart, the validation runtime restores the completed state
from SQLite before reporting `not_started`.

Failed or running validations do not replace the last known completed
validation snapshot.

## Duplicate strategy execution

R72.5.4 still keeps its in-memory lock for same-process concurrency, but it now
also claims the exact scan + validation + strategy lineage in SQLite before
delegating to R67.2.

The claim is unique and immutable. A second process or restarted Render
instance attempting the same lineage is blocked with:

`persistent_execution_claim_exists`

This remains fail-closed. A claimed execution is not automatically retried
after an unexpected process failure because doing so could create a duplicate
simulated position.

## Runtime reconciliation

R72.5.6 adds a read-only reconciliation service and API:

`GET /paper/strategy-runtime/reconciliation`

For each open strategy-attributed paper position it checks:

- exact scanner run persisted;
- exact validation run persisted;
- exact execution claim persisted.

Rows are labelled:

- `CONSISTENT`; or
- `LEGACY_OR_INCOMPLETE`.

No automatic backfill or mutation is performed. Older positions created before
R72.5.6 can therefore be identified explicitly without inventing missing
lineage.

## UI

The Paper Trading Portfolio now displays:

- strategy runtime status;
- whether the latest scanner is persisted;
- whether the latest validation is persisted;
- count of open positions with incomplete lineage;
- detailed lineage reconciliation when positions exist.

The System diagnostics page also exposes the reconciliation endpoint.

## Safety

R72.5.6 remains paper-only:

- no broker order calls;
- no live-trading enablement;
- no paper kill-switch bypass;
- no strategy rule changes;
- no automatic scan or validation runs;
- no automatic lineage repair.

The existing R67.2 entry gate and R72.5.5 exit-monitoring controls remain
authoritative.
