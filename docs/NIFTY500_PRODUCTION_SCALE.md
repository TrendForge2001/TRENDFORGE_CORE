# R65 — Canonical NIFTY 500 Universe & Production Scale Gate

## Canonical universe source

TrendForge loads the NIFTY 500 constituent list from the official NSE CSV:

`https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv`

The provider parses the published company name, industry, symbol, series and
ISIN fields. It does not pad, infer or hardcode constituent symbols.

NIFTY 500 is a nominal 500-company index, but the official NSE constituent
file can contain more than 500 tradable securities when an indexed company has
an additional eligible security/share class. TrendForge therefore treats the
official NSE file as authoritative for symbol membership instead of assuming
that the file must contain exactly 500 rows.

A valid production refresh must contain at least 500 and no more than 525
unique valid constituent securities. The upper bound is a sanity guard, not a
target. Partial downloads, duplicate symbols, malformed source data or an
implausibly large source fail closed. TrendForge never pads the list to a
target count.

## Universe lifecycle

`NSEIndexConstituentProvider` is read-only and performs no network work at
import time. Successful source payloads are cached for six hours.

`Nifty500Universe` is the single application-level source of truth. It tracks:

- source name and source URL;
- expected and loaded constituent counts;
- fetch and load timestamps;
- source Last-Modified and ETag headers when available;
- invalid row and duplicate-symbol counts;
- freshness age and maximum age;
- the last refresh error.

A stale in-memory universe refreshes before use. A failed refresh is surfaced
as degraded rather than silently serving an unverified source as healthy.

Legacy NIFTY 500 loading in `api/kite_service.py` delegates to the canonical
provider/universe contract; it no longer reads an independent
`data/nifty500.csv` file.

## API

### Inspect or refresh universe

`GET /universe/nifty500`

Query parameters:

- `refresh=true` forces a source refresh;
- `include_members=true` includes constituent records.

### Run a staged universe scan

`POST /scan/universe/nifty500`

Example request:

```json
{
  "period": "6mo",
  "interval": "1d",
  "capital": 100000,
  "top_n": 20,
  "batch_size": 25,
  "batch_pause_seconds": 1.0,
  "limit": 25,
  "full_universe": false,
  "refresh_universe": false,
  "compact": true
}
```

The default stage is deliberately 25 symbols. Increase `limit` only after the
previous production stage passes. A one-second pause is applied between
batches by default to reduce provider bursts; it is configurable from 0 to 10
seconds.

`compact=true` is the production default. It returns one lightweight
`symbol_results` row per constituent plus the scale-gate diagnostics and
top picks, instead of serializing every engine payload for the entire source
universe. Set `compact=false` only when detailed per-engine output is
required.

## Scale execution contract

The canonical pipeline supports bounded batches. Each batch uses the market
adapter's bounded parallel candle retrieval when available, then runs the
existing enrichment and engine contracts without changing thresholds or
scores.

Every requested unique symbol is accounted for. A symbol ends in either a
normal scanner result or an explicit ERROR result. Missing batch output is
converted into an explicit `scanner_batch_missing_result` error instead of
being silently dropped.

The response contains `scale_gate` diagnostics including:

- requested, unique and accounted symbol counts;
- completed, error and missing symbol counts;
- completion percentage;
- batch size, batch count and per-batch durations;
- symbol-level error details;
- enrichment-failure symbols;
- engine-execution-error symbols;
- total duration.

## Production gate sequence

Run the stages in order:

1. 25 securities;
2. 50 securities;
3. 100 securities;
4. the full source universe using `"full_universe": true`.

Do not infer the final security count from the index name. The full gate scans
every unique security returned by the verified official NSE source. For
example, if the source contains 501 securities, the full gate must account for
all 501.

For every stage require:

- universe status `healthy`;
- source `NSE_NIFTY500_CSV`;
- loaded security count between the validated source bounds;
- nominal company count 500;
- duplicate symbols 0;
- invalid source rows 0;
- accounted symbols equal unique requested symbols;
- missing symbols 0;
- no systemic scanner exception;
- individual provider/engine failures explicitly surfaced;
- application remains operational after the scan.

A zero eligible count is not a failure. R65 validates universe integrity,
coverage and operational scale; it does not weaken strategy thresholds to
manufacture BUY candidates.


## R65.2 enrichment scale controls

The first 25-security production gate proved scanner accounting and runtime
health, but uncovered a production-specific enrichment bottleneck: symbols
outside the pinned nine-symbol enrichment snapshot fell through to live NSE
and Yahoo providers. Render received NSE HTTP 403 responses and Yahoo HTTP 429
rate limits, causing repeated slow upstream attempts.

R65.2 keeps those failures observable and does not synthesize replacement
evidence. The scale path now prepares market-data payloads first and resolves
enrichment concurrently across the bounded scanner batch using the existing
StockEnricher worker limit.

Blocked/rate-limited providers use in-memory circuit breakers. NSE access
403/401 failures and Yahoo rate limits stop repeated upstream calls during the
cooldown window; Big Shark may continue to its existing source-backed BSE or
Screener fallbacks where usable evidence exists. A failed corporate-action
lookup is never converted into an empty action list, and unavailable sector
data is never replaced with invented sector momentum.

Scale-gate diagnostics now expose:

- symbols with enrichment failures;
- total enrichment failure events;
- counts grouped by enrichment field;
- per-symbol failure detail;
- engine execution errors separately from enrichment-provider failures.

Enricher health also reports the complete provider chain. A healthy pinned
snapshot no longer hides the runtime state of a lower-priority live fallback.

The compact API response serializes signal objects by their canonical signal
name (for example `HOLD`) rather than their Python object representation.

R65.2 changes operational execution and observability only. Strategy
thresholds, engine weights, mandatory-engine rules, evidence semantics and
eligibility rules are unchanged.


## R65.3 NIFTY 500 enrichment snapshot expansion

R65.2 reduced the 25-security stage from roughly 509 seconds to roughly
28 seconds, while preserving 25/25 accounting. The remaining production gap
was source availability: Render received NSE HTTP 403 for Corporate Actions
and NSE/Yahoo metadata failures for Sector on every snapshot-uncovered symbol.

R65.3 moves those fields out of the Render request path:

- Corporate Actions are collected with one successful broad query and then
  grouped across the official constituent universe.
- A no-event `[]` is valid only after that bulk query succeeds.
- Sector classification comes directly from the official NIFTY 500
  constituent Industry field.
- Sector proxy momentum is added when source-backed history is available.
- Classification-only sector records are explicitly marked and remain
  low-confidence; no momentum or relative-strength numbers are fabricated.
- Existing Big Shark snapshot evidence is preserved. Full-universe Big Shark
  refresh remains optional because R65.2 already verified the live,
  source-backed fallback path.

Before replacing the Render secret file, run
`verify-nifty500`. Do not deploy a bundle unless it reports
`production_ready: true`.

After deployment, repeat the 25-security gate. The expected R65.3 operational
change is that Corporate Actions and Sector no longer generate live enrichment
failures for the covered NIFTY 500 symbols. The next scale stage remains 50
securities only after 25/25 accounting, zero missing symbols, zero execution
errors, and stable runtime health are reconfirmed.
