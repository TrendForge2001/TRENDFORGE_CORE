# R69.5 — Fundamental Bulk Ingestion & Coverage Expansion

R69.5 operationalizes the R69.4 coverage model so verified fundamental data can
be expanded from the current small SQLite baseline toward full NIFTY500
coverage without weakening scanner execution gates.

## Objective

The production R69.4 readiness report established that only a small subset of
the tradable NIFTY500 had scanner-usable fundamental data. R69.5 adds a staged,
resumable ingestion workflow for curated completion datasets.

The workflow is built on the existing standardized completion engine. It does
not introduce a second fundamental schema and does not bypass evidence
requirements.

## Stage sizes

Supported stages are:

- 25 rows
- 50 rows
- 100 rows
- 250 rows
- 500 rows

A run persists its current offset in SQLite. The same source file can therefore
be re-uploaded with the same run ID and advanced through progressively larger
stages.

Example rollout:

```text
preview 25
apply   25
preview 50
apply   50
preview 100
apply   100
preview 250
apply   250
preview 500
apply   500
```

The final stage is automatically bounded by the number of rows remaining.

## Persisted run identity

Every bulk run stores:

- run_id
- source file name
- SHA256 of the uploaded file
- total row count
- next offset
- run status
- last preview range
- last preview stage size
- last preview gate result
- aggregate import counters
- coverage snapshot before the run
- latest coverage snapshot after apply
- timestamps

A run ID cannot be reused with a different file SHA256 or changed row count.

## Mandatory preview-before-apply

Apply is fail-closed.

For every stage:

1. submit with `apply=false`;
2. TrendForge validates the exact stage and persists the preview;
3. correct any gate failures;
4. re-submit the same run ID, same file and same stage size with
   `apply=true`;
5. TrendForge re-runs validation before writing.

An apply request without a previously persisted clean preview returns
`preview_required` and performs no database write.

## Stage gate

A stage is blocked when any of the following are non-zero:

- unknown symbols
- invalid rows
- duplicate symbols
- overwrite attempts
- evidence failures

The gate response includes explicit counts and blocker reasons.

### Unknown symbols

The existing R69.4 universe rule remains in force. New database rows can be
created only for current tradable NIFTY500 members.

### Duplicate symbols

R69.5 rejects a source file containing duplicate normalized symbols. The same
symbol must not appear twice across the bulk file, even if the duplicate would
fall in a later stage.

### No-overwrite protection

The completion engine still fills only currently missing fields.

R69.5 additionally detects when the upload supplies a value for an already
present fundamental field. Such a supplied value is reported as an overwrite
attempt and blocks the bulk stage.

This includes fully complete existing records.

### Evidence failures

Standardized completion evidence remains mandatory. A row can fail for missing
or invalid source type, source, source reference, as-of date, ROE fiscal-year
period, EPS 3Y CAGR period, N/M evidence, or point-in-time shareholding dates.

The underlying completion report retains row-level validation errors.

## Coverage delta

Every applied stage snapshots R69.4 readiness before and after the write.

The response includes a coverage delta for:

- database records
- missing database records
- scoring-ready records
- scanner-ready records
- quality-pass records
- scanner-quality-pass records
- stale records
- database coverage percentage
- scoring-readiness percentage
- scanner-readiness percentage

This lets each stage prove that coverage improved rather than merely reporting
that rows were written.

## Resumability

The `fundamental_bulk_runs` SQLite table stores the next offset and aggregate
counters.

If a client connection drops after the server applies a stage, the persisted
run can be inspected with its run ID before retrying.

If a retry encounters fields already filled by the previous successful apply,
the no-overwrite gate prevents a second write.

## API

### Readiness

`GET /fundamentals/bulk/readiness`

Returns:

- version = R69.5
- supported stage sizes
- preview requirement
- strict gate policy
- broker-order prohibition

### Run history

`GET /fundamentals/bulk/runs?limit=50`

### Run detail

`GET /fundamentals/bulk/runs/{run_id}`

### Preview/apply stage

`POST /fundamentals/bulk/upload`

Multipart form fields:

- file
- run_id
- stage_size
- apply
- source
- as_of
- sheet

The upload route is protected by the production admin-key gate and persistent
storage requirement.

Read-only readiness and run inspection remain non-admin routes.

## Webapp

The Fundamentals page now includes an R69.5 staged-ingestion panel with:

- bulk completion file upload
- persistent run ID
- stage-size selector
- preview/apply switch
- run offset
- total rows
- remaining rows
- run status
- stage-gate output
- coverage delta
- recent run history

## Safety invariants

R69.5 does not change:

- R67.3 analysis eligibility
- R67.3 execution eligibility
- R69.3 blocker semantics
- Fundamental Engine thresholds
- Market Regime vetoes
- Risk Engine requirements
- paper auto-entry rules
- broker permissions

Live broker orders remain disabled.

R69.5 is a data-quality and coverage workflow only.
