# R65 — Canonical NIFTY 500 Universe & Production Scale Gate

## Canonical universe source

TrendForge loads the NIFTY 500 constituent list from the official NSE CSV:

`https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv`

The provider parses the published company name, industry, symbol, series and
ISIN fields. It does not pad, infer or hardcode constituent symbols.

A valid production refresh must contain exactly 500 unique valid symbols.
Partial downloads, duplicate symbols or malformed source data fail closed.

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
  "refresh_universe": false
}
```

The default stage is deliberately 25 symbols. Increase `limit` only after the
previous production stage passes. A one-second pause is applied between
batches by default to reduce provider bursts; it is configurable from 0 to 10
seconds.

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

1. 25 symbols;
2. 50 symbols;
3. 100 symbols;
4. full 500 symbols.

For every stage require:

- universe status `healthy`;
- source `NSE_NIFTY500_CSV`;
- loaded constituent count 500;
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
