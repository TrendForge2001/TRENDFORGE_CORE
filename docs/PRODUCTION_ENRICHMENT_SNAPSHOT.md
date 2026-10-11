# Production Enrichment Snapshot

TrendForge production enrichment can run in **snapshot-first** mode so scanner
requests do not depend on NSE/Yahoo accepting requests from the Render cloud
runtime.

## Why this exists

Some public data providers allow browser/residential traffic but block or rate
limit cloud-hosted application traffic. TrendForge therefore supports a
read-only JSON enrichment snapshot generated from a workstation or another
network that can reach those sources.

The snapshot covers:

- `corporate_actions`
- `big_shark`
- `sector`

Fundamentals continue to use the existing SQLite/bootstrap path.

## Export on a workstation

Example for the canonical production smoke universe:

```powershell
$symbols = "BSE,CAMS,COFORGE,FORCEMOT,JYOTICNC,LUPIN,MCX,POWERINDIA,SUZLON"
$out = "$env:USERPROFILE\Downloads\trendforge_enrichment_snapshot.json"

.\.venv\Scripts\python.exe -m scripts.enrichment_snapshot export `
    --symbols $symbols `
    --pause 2 `
    --out $out

.\.venv\Scripts\python.exe -m scripts.enrichment_snapshot verify $out

Get-FileHash $out -Algorithm SHA256
```

The exporter is deliberately sequential and includes pauses so it does not
hammer public upstreams. It records per-symbol failures instead of silently
inventing enrichment data.

## Configure Render

Create a Render Secret File named:

```text
trendforge_enrichment_snapshot.json
```

Render exposes that file at:

```text
/etc/secrets/trendforge_enrichment_snapshot.json
```

TrendForge automatically detects that default path.

Optionally set:

```text
ENRICHMENT_SNAPSHOT_SHA256=<sha256 from Get-FileHash>
```

You may also override the path with:

```text
ENRICHMENT_SNAPSHOT_PATH=/custom/path/file.json
```

After saving the secret file/environment variable, redeploy.

## Runtime behavior

For Corporate Actions, Big Shark and Sector, provider priority is:

1. verified local enrichment snapshot;
2. live resilient provider fallback.

If a symbol/field exists in the snapshot, the scanner does **not** call the
live provider for that field. This includes an empty corporate-action list,
which is a valid snapshot result meaning the source was queried successfully
but no matching event existed.

If a symbol or field is absent from the snapshot, TrendForge may use the live
fallback. Existing rate-limit/cooldown protections remain active.

## Health

`GET /health` includes:

```text
enrichment_snapshot.status
enrichment_snapshot.generated_at
enrichment_snapshot.symbols_loaded
enrichment_snapshot.field_records
enrichment_snapshot.file_sha256
enrichment_snapshot.pinned_sha256
```

When snapshot providers are primary, each corresponding enrichment provider
health entry reports `runtime_verified` without making a health-check network
request.

## Refresh

Regenerate the file and replace the Render Secret File whenever you want to
refresh enrichment data. A redeploy loads the replacement snapshot.

This is intentionally read-only. It does not enable HTTP mutation endpoints or
change Render persistence requirements.


## Big Shark evidence semantics

Big Shark coverage is evidence-aware. A provider response containing only
metadata does **not** count as usable Big Shark coverage.

The local exporter attempts, in order of available evidence:

- official NSE shareholding-pattern filings and their XBRL documents;
- NSE bulk/block deal history;
- Yahoo institutional and mutual-fund holder tables.

NSE shareholding XBRL is parsed conservatively into promoter, FII, DII and
public aggregate percentages. When two filing periods are available, TrendForge
also emits quarter-over-quarter FII/DII/promoter changes. These classifications
come from the official filing taxonomy; generic Yahoo institutions are never
relabeled as FII or DII.

Snapshot verification now reports both raw `field_records` and semantic
`coverage`. For Big Shark, use `coverage.big_shark` as the production gate.


## BSE Regulation-31 fallback

When the NSE shareholding-filings endpoint returns no usable filing evidence for
an NSE symbol, the Big Shark exporter now falls back to BSE Regulation-31
shareholding filings.

The fallback is generic rather than symbol-specific:

1. resolve the exact BSE scrip code from the NSE-style symbol with BSE
   `PeerSmartSearch`;
2. fetch quarterly shareholding filings from
   `Corp_Shareholding_ng`;
3. download the latest BSE iXBRL filings from the official
   `/XBRLFILES/` path;
4. extract promoter, FII, DII and public aggregate percentages from the filing
   taxonomy;
5. use the two latest parsed quarters to derive holding changes.

BSE is queried only when the NSE shareholding path produced no usable evidence.
Yahoo holder tables remain generic and are never relabeled as FII/DII.


## Last-resort Screener shareholding fallback

If both exchange shareholding paths fail to produce usable ownership evidence,
the local snapshot exporter may use the public quarterly shareholding table on
Screener as a last-resort fallback.

This fallback is deliberately source-labelled as
`SCREENER_SHAREHOLDING`. It is not represented as NSE/BSE filing evidence.
TrendForge retains only categories explicitly published by the table
(Promoter/FII/DII/Public), derives quarter-over-quarter changes from adjacent
published quarters, and does not infer investor classifications.

Provider precedence for Big Shark ownership evidence is therefore:

1. NSE shareholding XBRL;
2. BSE Regulation-31 iXBRL;
3. Screener published shareholding table;
4. generic Yahoo holders and NSE large-deal evidence remain independent inputs.

The Screener fallback is intended to close source-availability gaps such as an
empty NSE filing index plus BSE API rejection. It does not change Big Shark
engine thresholds or scoring rules.


## NIFTY 500 expansion workflow

For production scale, do not export Corporate Actions and Sector by making
three live requests per constituent. Use the NIFTY 500 expansion workflow.

The expansion command:

1. refreshes the official NSE NIFTY 500 constituent CSV;
2. treats all verified source securities (currently 500-525 allowed) as the
   snapshot universe;
3. performs one broad corporate-action request and groups successful results
   by symbol;
4. records `[]` only when that broad corporate-action request succeeded and
   a symbol genuinely had no matching action;
5. uses the official constituent Industry field as source-backed sector
   classification, avoiding per-company NSE/Yahoo metadata lookups;
6. attempts cached Yahoo sector-proxy history to add momentum evidence without
   repeating history downloads for every stock;
7. falls back to explicit classification-only sector records when proxy
   momentum cannot be obtained; it never invents momentum values;
8. preserves existing Big Shark evidence from an optional base snapshot;
9. keeps full-universe Big Shark refresh opt-in because it is a
   high-request-volume operation.

Example:

```powershell
$old = "$env:USERPROFILE\Downloads\trendforge_enrichment_snapshot.json"
$new = "$env:USERPROFILE\Downloads\trendforge_enrichment_snapshot_nifty500.json"

.\.venv\Scripts\python.exe -m scripts.enrichment_snapshot expand-nifty500 `
    --base $old `
    --corporate-days 120 `
    --out $new

.\.venv\Scripts\python.exe -m scripts.enrichment_snapshot verify-nifty500 $new

Get-FileHash $new -Algorithm SHA256
```

`verify-nifty500` reports both source coverage and signal coverage. In
particular, `coverage.sector` counts verified source classification, while
`signal_coverage.sector` counts sector records containing actual momentum /
relative-strength inputs. Classification-only records stop blocked live
metadata fallbacks but remain low-confidence and do not masquerade as sector
momentum evidence.

The NIFTY 500 snapshot is production-ready only when:

- the bundle declares the canonical `NSE_NIFTY500_CSV` universe;
- the snapshot symbol count equals the verified source security count;
- Corporate Actions coverage equals the full source security count;
- Sector classification coverage equals the full source security count;
- there are no global corporate-action retrieval failures.

Big Shark coverage remains evidence-aware and can continue to use the existing
live fallback while its full-universe snapshot refresh is handled separately.
