# Private scanner workspaces

The navigation has three groups. TECHNICAL SCAN retains Stock Watchlists,
Technical Scanner, Kite Backtesting, Live Paper Trading, Live Kite Session and
Reports at their existing deep links. FUNDAMENTAL SCAN is reserved for owner
rules. AMC / BIG SHARK / INSTITUTIONAL contains the private portfolio selector;
additional institutional rules remain reserved.

## Actual-trade selector

The owner chose actual bought/sold quantities or actual traded values as the
signal input. Quarterly ownership changes, current holdings, holding value and
investor net worth never substitute for trades. A holdings-only upload produces
NO_DATA (Awaiting actual trade data), including rows labelled BOUGHT or SOLD.

For each stock in one common reporting window, choose one metric for the entire
snapshot: shares or INR. Average buying is total bought divided by the number
of buying investors; average selling is total sold divided by selling investors.
The conditions are:

- BUY when average actual buying exceeds average actual selling.
- SELL when average actual selling exceeds average actual buying.
- HOLD when the averages are equal and complete numeric observations exist.
- NO_DATA when no complete actual trade observations exist.

An absent side is zero only when explicitly supplied as zero. Blanks, negative
amounts, nonfinite values and fractional share counts are not valid trade data.
Incomplete observations are excluded and counted. Such coverage is provisional;
it does not represent all institutions. Repeated identical stock/investor rows
are deduplicated; conflicting duplicates or mixed date windows cancel import.

The downloadable workbook keeps BIG SHARK and BIG SHARK STOCKS, adds SIGNALS,
REFRESH STATUS and CONDITIONS, and provides a TRADE FLOWS input sheet:

| Column | Meaning |
| --- | --- |
| Stock Name | Exact company name |
| Investor Name | Reporting investor, one aggregate row per stock/investor |
| Bought Quantity / Sold Quantity | Actual shares transacted, or blank if unavailable |
| Bought Value (₹) / Sold Value (₹) | Actual INR traded value, not crore or current holding value |
| Period Start / Period End | Common date window, YYYY-MM-DD, no future dates |

Fill the chosen metric on both sides (zero for a known absent side), then reimport
to recalculate. This is an upload-based refresh. It does not claim a live source
connection or new filings. Holdings reporting quarters remain unknown unless
explicitly supplied and are labelled unverified.

Only exact owner-supplied NSE symbol mappings enter technical stock selection.
Unmapped names remain visible in the institutional scanner. The shared Big Shark
selector intersects mapped signals with the chosen public stock list. It never
hides existing positions or changes order controls. A current snapshot used to
select stocks for historical technical backtests carries a visible warning about
look-ahead and survivorship bias; it is not an institutional timing backtest.

## Owner access

The unified server provides `/owner/laptop` and `/owner/mobile`. Both require the
existing server-configured `TRENDFORGE_WEBAPP_ACCESS_KEY`. Links contain no
credentials and do not bypass sign-in. They are device-friendly entry routes,
not hardware-bound credentials or a new domain.

Signed owner cookies expire after eight hours and use HttpOnly, SameSite=Strict
and Secure on HTTPS/public hosts. Key rotation invalidates sessions. Logout
revokes the cookie in the running process and closes subsequent WebSocket
traffic. The server checks WebSocket access before accepting and again during
traffic. Login has a signed CSRF token and bounded per-client throttling.
Workspace responses prohibit shared caches and indexing.

In production, business API reads and writes require the separate server-held
admin key, including cached watchlists, fundamentals, institutional data, reports
and API documentation. Only minimal liveness/health is public. Native mobile
Firebase owner verification and narrowly scoped external scheduler authentication
keep their existing independent controls. The scheduler status endpoint now also
requires its scheduler key. UI API clients supply credentials server-side.

## Private storage and release

Portfolio snapshots live in the configured operational SQLite database. Imports
on production require verified persistent storage. Protected read/export/import
routes are under `/institutional/big-shark`; successful imports retain earlier
snapshots and failed validation leaves the last snapshot untouched. The original
file digest, rule, metric and import time are retained for provenance.

An optional `TRENDFORGE_BIG_SHARK_WORKBOOK_B64` private Render environment value
can seed the supplied XLSX without putting it in GitHub. Use a confirmed workspace
and service, preserve unrelated environment values and verify deployment before
claiming import success. The seed is deduplicated by digest and cannot overwrite
later mappings/imports. Remove the seed after a verified durable import. Never
print it, add it to a Blueprint, or include it in logs or workflow artifacts.

Owner workbooks, holdings, private seed values and source credentials must never
enter GitHub or public artifacts. All test fixtures use synthetic trades. Check
repository visibility before publishing proprietary changes. The app login does
not make a public source repository private; changing GitHub visibility is a
separate account setting.

This change prepares scanning and access controls. It does not activate live
broker orders or assert that delayed holdings are an executable trading feed.

## Trade disclosures and confirmation

The institutional page accepts UTF-8 trade CSVs, including NSE bulk/block-deal
headers, and provides a blank CSV template. Records require trade date, exact
exchange symbol, investor name, BUY/SELL and actual quantity. A reported price is
required for INR value comparisons; gross value is quantity times reported price,
before fees, and can reflect the source's rounded weighted average price.

Investors match exact names from the private workbook. Owner-supplied aliases
must target a tracked investor. Unknown investors are reported separately; no
fuzzy matching or inference from holding changes occurs. Import replaces the
active activity window rather than appending amounts. Identical records are
deduplicated; explicit Trade IDs distinguish separate otherwise identical trades.
Conflicting IDs, negative/nonfinite values, future evidence and invalid windows
reject the import and preserve the previous snapshot.

| Display column | Meaning |
| --- | --- |
| Activity Signal | The existing BUY/SELL average rule, scoped to supplied records |
| Technical Confirmation | NOT_CHECKED, BUY_CONFIRMED, SELL_EXIT_CONFIRMED, WAIT, NO_DATA or STALE_DATA |
| Data Coverage | DISCLOSED_ONLY, OWNER_SUPPLIED_WINDOW, PARTIAL_INPUT or no trade evidence |
| Disclosure Time | Latest supplied publication time, only when all relevant records have one |

Public disclosure imports are always DISCLOSED_ONLY. A zero on one side means
no matching reported trade on that side in the supplied window; it never proves
zero undisclosed activity. Stocks without matched records remain NO_DATA, not
HOLD. Missing prices never become zero traded values. Review investor counts,
window dates and coverage together with averages.

Disclosure times must include a timezone, cannot predate the trade date and
cannot be in the future. They remain source-supplied and unverified. A trade date
and an upload time are not substituted for a publication time. First-seen time
is recorded separately and is the earliest availability evidence established by
this system for an untimestamped import. The table displays timestamps in IST.
Historical research must not move an untimestamped disclosure back to trade date.

The exported workbook retains individual TRADE DISCLOSURES and coverage metadata.
Reimport preserves disclosure-only coverage, missing timestamps and exact investor
aliases; it does not promote aggregates into a complete transaction ledger.

### Scoped feed integration

Protected routes under `/institutional/big-shark`:

- `GET /trades/template`: blank CSV template, owner admin key required.
- `POST /trades/import`: CSV upload with source, metric, optional reporting window,
  optional actual disclosure timestamp and verified investor aliases.
- `POST /trades/feed`: JSON submission of actual trade records. This is a working
  ingestion endpoint, not a configured subscription or automatic exchange poller.
- `POST /confirm`: read-only daily confirmation for up to five mapped stocks and
  the current snapshot ID. No broker order endpoint is called.

A provider can use `X-TrendForge-Feed-Key`, configured through the private
`TRENDFORGE_BIG_SHARK_FEED_KEY` environment value. It must have at least 32
characters and differ from the owner admin key. This credential works only for
the JSON feed endpoint; it cannot retrieve the portfolio, exports or reports, or
run technical checks or trading operations. Its response contains only an ingest
receipt. An owner can also submit using the existing server-held admin key.
Never give a provider the owner password or general admin key.

Example feed payload using synthetic data:

```json
{
  "source": "OWNER_CSV",
  "metric": "quantity",
  "records": [{
    "trade_date": "2026-01-05",
    "symbol": "EXAMPLE",
    "stock_name": "Example",
    "investor_name": "Fund A",
    "side": "BUY",
    "quantity": 100,
    "price": "20.50",
    "disclosed_at": "2026-01-05T18:00:00+05:30",
    "trade_id": "example-1"
  }]
}
```

### Daily confirmation rules

This separate confirmation profile reuses canonical VWMA20/50, Wilder RSI14,
Volume SMA20 and previous completed year's Fibonacci calculations. BUY requires
close > VWMA20 > VWMA50, RSI 55–75, volume >=1.5 times SMA20 and a fresh R1/R2/R3
crossing. SELL/EXIT requires RSI <50 and a fresh cross below VWMA20 or yearly
P/S1/S2/S3. It confirms only matching institutional activity; disagreement is WAIT.
It does not change the existing technical scanner's strategy or backtest rules.

Checks use only completed daily Kite candles, fetch bounded sequential history,
retain indicator/check evidence and reject insufficient or stale sessions.
Freshness follows the existing conservative weekday session check; it does not
claim an independent holiday-calendar audit. Old confirmations become STALE_DATA
when a newer completed session is expected. Confirmation requests are blocked
during active cloud paper/research work and cannot overwrite a newer import that
arrived while candles were being fetched. No live orders are enabled.
