# R69.4 — Fundamental Coverage & Readiness Completion

R69.4 closes the structural coverage gap identified by the production R69.3
scan: scanner execution remained fail-closed because the tested universe had
incomplete mandatory fundamental data.

R69.4 does not relax the Fundamental Engine. It makes missing data visible and
completable across the canonical tradable NIFTY 500 universe.

## Safety invariant

The eight mandatory fundamental fields remain:

- roce
- roe
- sales_growth
- profit_growth
- eps_growth
- debt_equity
- promoter_holding
- pledged

R69.4 does not change R67.3 analysis/execution eligibility, R69.3 blocker
semantics, Fundamental Engine thresholds, Risk Engine thresholds, Market
Regime vetoes, paper auto-entry rules, or broker permissions.

## Universe-aware coverage

The new FundamentalCoverageService loads the canonical NIFTY 500 universe and
excludes index placeholder rows such as DUMMY-prefixed securities in the same
way as the production scanner.

Coverage is measured against every tradable constituent, not only symbols that
already have a SQLite record.

This prevents a small seeded database from reporting deceptively high
completion percentages while hundreds of universe members are absent.

## Readiness states

Each tradable symbol is classified as one of:

- READY_PASS — complete numeric contract and Fundamental Engine quality pass.
- READY_FAIL_QUALITY — complete numeric contract but quality threshold fails.
- NM_READY — accepted evidence-backed N/M scoring path, currently supported for
  EPS growth under the canonical readiness resolver.
- DATA_INCOMPLETE — a database row exists but mandatory scoring inputs/evidence
  are incomplete.
- INVALID — supplied values violate the strict fundamental input contract.
- MISSING — no SQLite fundamental record exists for the universe member.

Staleness is reported separately. R69.4 diagnostics do not silently reinterpret
stale data as missing data.

Because the production scanner deliberately suppresses stale fundamental values
before engine evaluation, R69.4 exposes two readiness layers:

- scoring readiness: whether the stored numeric/evidence contract can be scored;
- scanner data readiness: whether that scoring-ready record is also fresh enough
  to be passed through the production enrichment path.

A numerically complete but stale record can therefore be READY_PASS at the raw
scoring layer while reporting scanner_status=STALE and scanner_usable=false.

## Coverage API

GET /fundamentals/readiness

Query parameters:

- refresh_universe=false
- incomplete_only=false
- limit=5000

The response includes:

- version = R69.4
- tradable_symbols
- database_records
- database_coverage_pct
- missing_database_records
- scoring_ready_records
- scoring_readiness_pct
- scanner_ready_records
- scanner_readiness_pct
- quality_pass_records
- scanner_quality_pass_records
- stale_records
- readiness_counts
- field_coverage
- required_fields
- records

Field coverage reports present, missing, invalid, raw coverage percentage,
fresh-present count, and fresh coverage percentage for all eight mandatory
fields.

## Universe-aware completion workbook

The existing completion CSV/XLSX workflow now uses the canonical NIFTY500
universe when configured by the application factory.

The workbook therefore contains:

1. existing SQLite records that are incomplete; and
2. tradable NIFTY500 members that currently have no SQLite row.

Missing database members start at 0% completeness with all mandatory fields
listed as missing.

DUMMY/index placeholder rows are excluded.

## Creating previously missing records

The completion upload can create a new SQLite fundamental record only when:

- the symbol does not already have a record;
- the application has a canonical universe configured;
- the symbol is a current tradable NIFTY500 constituent; and
- supplied fields pass the existing numeric and standardized evidence
  validation.

Symbols outside the canonical universe remain unknown and are rejected.

Existing values continue to be protected: the completion workflow fills only
fields that are currently missing and never overwrites a present fundamental
value.

For a newly created universe record, source_file and a completion source are
stored, and the snapshot as-of date is derived from validated field evidence.

## Evidence requirements

R69.4 preserves the standardized completion requirements:

- source type
- source
- source reference
- valid as-of date
- FY label for ROE
- exact 3-year fiscal period for EPS Growth CAGR
- point-in-time dates for promoter holding and pledge
- explicit N/M status/reason where applicable

Preview remains non-writing. Apply persists validated numeric fields, field
audit history, and standardized evidence.

## Webapp

The Fundamentals page now surfaces R69.4 coverage metrics and mandatory field
coverage. It also provides the NIFTY500 completion workbook and the existing
preview/apply completion workflow.

## Expected production use

1. GET /fundamentals/readiness.
2. Identify MISSING and DATA_INCOMPLETE counts and lowest-coverage fields.
3. Download /fundamentals/completion.xlsx.
4. Populate only verified values with source/period evidence.
5. Upload in preview mode and correct invalid rows.
6. Apply only after preview is clean.
7. Re-run /fundamentals/readiness.
8. Re-run the scanner and verify R69.3 fundamental:data_incomplete blocker
   counts fall without changing execution gate rules.
