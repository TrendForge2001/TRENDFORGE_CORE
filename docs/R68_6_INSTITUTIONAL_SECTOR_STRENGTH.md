# R68.6 Institutional / Big Shark Activity and Sector Strength

## Owner-only Big Shark public feeds

The Institutional Scanner can fetch Moneycontrol's public Big Shark catalogue
and reported holdings-change rows, plus actual NSE bulk **or** block disclosures.
The public page is a partial view, not a complete portfolio audit. Quarter,
coverage, source URL, first-seen time and last-fetch time remain visible. An open,
future or unknown source quarter is marked unverified; holding quantities and
Moneycontrol's BOUGHT/SOLD labels never become actual trade quantities.

Only actual NSE quantities or reported traded values drive the approved mean
buying-versus-mean-selling activity rule. Investors match the private workbook by
exact normalized names or owner-verified aliases. Bulk and block reports remain
separate to avoid overlapping aggregates. The NSE archive fallback covers its
reported day only, and that narrower actual window is shown. `BD_DT_ORDER` is
a trade/sort date, never a disclosure publication timestamp.

Authenticated owner controls:

```
GET  /institutional/big-shark/sources
POST /institutional/big-shark/sources/refresh
PUT  /institutional/big-shark/sources/config
```

Refresh accepts `source` (`NSE_BULK` or `NSE_BLOCK`), `metric` (`quantity` or
`value`), an optional past window of at most 31 days and verified investor aliases.
With no window it uses the latest seven calendar days. A new owner can bootstrap
public holdings without uploading a workbook; existing private workbook values
remain intact. Downloads add PUBLIC HOLDINGS, PUBLIC INVESTORS and PUBLIC SOURCE
STATUS sheets.
No holdings-derived buy/sell signal is created during bootstrap.

Moneycontrol access failures never skip the independent NSE request, including
when the owner workspace is empty. A bounded preview of returned NSE records is
available without a workbook, labelled as an unfiltered market report. It does
not create a Big Shark universe or activity signals. Importing the owner's
investor workbook enables exact matching. Reporting windows and future-date
validation both use the request's IST date, including after midnight IST while
the server's UTC date is still the previous day.

An optional private `TRENDFORGE_BIG_SHARK_WORKBOOK_B64` seed fills an empty
workspace only; existing or concurrent owner imports take precedence. An operator
can set a fresh 32-character lowercase hex `TRENDFORGE_BIG_SHARK_REFRESH_REQUEST`
to request one refresh after startup. Its claim is persisted before fetching and
is not replayed on later restarts. It does not enable daily or paper automation.
Startup logs contain fixed statuses, failure codes and counts only, never seed
contents, investor identities or trading records. These settings are private
Render environment values and must never be committed to source.

Daily refresh is enabled explicitly in the source form. A separate backend task
checks every five minutes, refreshes at most daily after successful requests and
backs off an hour after failures. It works without an open browser and does not
use Kite, technical backtests, order endpoints or paper controls. Ordinary paper
restart behavior is unchanged. Open trading positions and account limits are
never altered by a source refresh.

The fetcher uses fixed HTTPS sources, bounded bodies and redirects, and standard
public access. It does not bypass source access restrictions. If a source is
unavailable, the last good data and its original date remain visible. A successful
empty/no-match trade window instead produces NO_DATA for that window. Concurrent
owner imports win over an in-flight refresh. Public-source sites receive no
private workbook, investor aliases, trading book or credentials; a provider's
write-only feed key cannot read or control these owner endpoints.

R68.6 adds canonical persisted dashboard contracts for institutional evidence and NIFTY 500 sector rotation.

## API contracts

Read-only:

    GET /institutional/readiness
    GET /institutional?limit=<1..500>
    GET /institutional/{symbol}
    GET /sector-strength

Admin protected:

    POST /institutional/refresh
    POST /sector-strength/refresh

Institutional refresh request:

    {
      "symbols": ["TCS", "INFY"]
    }

At most 25 symbols may be refreshed in one request.

Sector refresh request:

    {
      "limit": 100,
      "period": "1y",
      "interval": "1d",
      "refresh_universe": false
    }

The sector sample can be 25-500 securities and uses one or two years of daily history.

## Institutional / Big Shark methodology

R68.6 uses the existing YahooInstitutionalEnrichmentProvider as the live evidence adapter.

That provider can collect:

- Yahoo institutional holder rows
- Yahoo mutual-fund holder rows
- NSE shareholding filings
- BSE shareholding fallback
- Screener published shareholding fallback
- NSE bulk deals
- NSE block deals

Classification remains conservative. FII/DII/promoter labels are accepted only when source evidence explicitly supports those categories.

The resulting evidence payload is evaluated by the existing canonical Big Shark Engine.

Persisted output includes:

- score
- confidence
- grade
- institutional bias
- data-quality flag
- hard-block flag
- ownership
- holding changes
- deals
- promoter evidence
- conviction evidence
- reasons
- warnings
- provider/source metadata

No missing institutional field is manufactured. A provider response with insufficient usable evidence can persist as a degraded zero/low-confidence snapshot.

## Sector-strength methodology

Sector Strength does not introduce a replacement scoring engine.

R68.6:

1. loads the canonical NIFTY 500 constituent universe;
2. evenly samples the requested number of securities across that symbol-ordered universe;
3. retrieves daily candles through the canonical market-data adapter;
4. derives per-security:
   - 1-day return
   - 1-week return using 5 sessions
   - 1-month return using 21 sessions
   - 3-month return using 63 sessions
   - latest volume / 20-session average volume
5. groups securities by the official NIFTY 500 sector/industry classification;
6. derives per-sector:
   - mean 1d/1w/1m/3m return
   - average volume ratio
   - advancing / declining count
   - 1-month positive-constituent leadership percentage
   - relative performance against the sampled market composite
7. evaluates each sector snapshot through the canonical Sector Engine;
8. ranks sectors by engine score and confidence.

The persisted response includes score components, reasons, warnings, coverage/failure evidence and market-data provider diagnostics.

## Institutional sector-flow limitation

The canonical Sector Engine contains an institutional-flow component, but R68.6 does not have a verified sector-level FII/DII flow source.

Therefore:

    institutional_sector_flow_available = false

for R68.6 sector snapshots.

No stock-level Big Shark evidence is summed or transformed into a sector-level FII/DII flow number.

The flow component remains neutral/missing under the existing Sector Engine behavior.

## Persistence

R68.6 adds:

    institutional_sector_snapshots

The table is keyed by snapshot kind + snapshot key.

Institutional snapshots use:

    kind = institutional
    snapshot_key = symbol

Sector strength uses:

    kind = sector_strength
    snapshot_key = NIFTY 500

Refreshes update the latest snapshot in place.

## Webapp

### Big Shark Activity

- engine/provider readiness
- symbol inspection
- up to 25-symbol refresh
- score/confidence/grade/bias
- data-quality and hard-block flags
- ownership table
- shareholding-change table
- bulk/block deal evidence
- promoter and conviction detail
- provider provenance
- persisted ranking
- CSV export

### Sector Strength

- explicit sample/history refresh
- coverage and market-composite metrics
- strongest/weakest sector
- ranked sector table
- score chart
- component detail
- participation/breadth detail
- reasons/warnings
- symbol-level coverage failures
- provider diagnostics
- CSV export

## Safety

R68.6 is diagnostic only.

It:

- does not place broker orders
- does not create paper positions
- does not change scanner scoring weights
- does not infer unavailable FII/DII sector flow
- does not run live provider calls from GET dashboard reads
- protects only explicit refresh operations with the admin key

The snapshots are SQLite-backed and remain subject to the existing Render ephemeral-storage limitation.
