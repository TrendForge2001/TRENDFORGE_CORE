# R71.2 — FinEdge India financial-data API (300 calls/minute)

## Scope and source confidence

FinEdge API (`https://www.finedgeapi.com/`) publicly advertises a
**300 API calls/minute** limit for Basic, Individual and Professional
accounts. The Basic tier includes trial access to ITC, RELIANCE and
HDFCBANK only. Other symbols require suitable subscription entitlements.

The detailed `https://data.finedgeapi.com/api/v1` host, `token` query
authentication and `ratios`, `financial-metrics`, `shareholdings` paths
are documented by an independent open-source integration inventory,
not an official authenticated OpenAPI document. Verify these contracts
against a **licensed FinEdge account** before expanded use.

Sources:
- https://www.finedgeapi.com/
- https://github.com/marketcalls/StockLens/blob/main/docs/prd/02-data-source-inventory.md

## No change to Kite or risk gates

- Kite remains primary for OHLCV and quotes.
- FinEdge is optional, read-only, and **disabled by default**.
- It does not write to production or local SQLite; does not auto-import
  values into the eight required fundamental fields; does not qualify
  a symbol as BUY/SELL; does not change scoring, execution blocks,
  paper trading, live trading, or production startup.
- A human must reconcile currency and percentages, fiscal periods,
  ROE/ROCE measurement, 3Y growth methods, promoter holding and
  pledge dates. Source reference/period evidence is mandatory for the
  R69.4 completion workbook.
- Startup behavior does **not** execute a FinEdge request.

## Server-side configuration

Configure in the local Windows process environment or on the **staging
Streamlit service only** after obtaining a FinEdge credential:

```text
FINEDGE_ENABLED=true
FINEDGE_API_KEY=<secret from your FinEdge account>
FINEDGE_RATE_LIMIT_PER_MINUTE=300
```

Leave production Render configuration unchanged unless a separately
approved deployment requires a backend integration. No credential value
belongs in GitHub, screenshots, chat, URLs in logs, or the browser's
Webapp Access Key or Admin API Key fields.

The authenticated third-party API requires `token` as a query
parameter. The client never logs request URLs and never propagates
upstream exception text which could contain the token; redirects are
not followed.

## UI usage (staging)

After setting staging environment vars and deploying staging, sign
in with the Webapp Access Key, set the TrendForge Admin API Key,
open **Data → Fundamentals → FinEdge API — read-only source preview**,
choose a symbol and financial-statement mode, and click
**Fetch FinEdge data**. One symbol invokes four read-only requests:

1. `GET /api/v1/ratios/{symbol}?ratio_type=pr&statement_type=c|s`
2. `GET /api/v1/ratios/{symbol}?ratio_type=le&statement_type=c|s`
3. `GET /api/v1/financial-metrics/{symbol}?ratio_type=gr&statement_type=c|s`
4. `GET /api/v1/shareholdings/pattern/{symbol}?period=quarterly`

The returned JSON is labelled **unverified candidate data**, downloadable
for offline audit. No mapping to scanner scores occurs.

## Windows batch candidate export

Run from the repository root with Python 3.12:

```powershell
cd C:\Users\Lenovo\Desktop\TrendForge
$py = ".\.venv\Scripts\python.exe"
$env:FINEDGE_ENABLED = "true"
# Set FINEDGE_API_KEY in Windows user environment; do not paste it in terminal logs.

# Preview estimated quota consumption without network access.
& $py -m scripts.finedge_fundamental_candidates --symbols ITC,RELIANCE,HDFCBANK

# Explicit network request (up to 25 symbols x 4 endpoints = 100 calls).
& $py -m scripts.finedge_fundamental_candidates `
    --symbols ITC,RELIANCE,HDFCBANK --collect `
    --out "C:\TrendForgeData\fundamentals\finedge-candidates-001.json"
```

The output directory may exist, but the JSON file **must not** exist:
R71.2 will never overwrite collected source evidence. Importing into
R71.1 is a separate validation task and not implemented as an
automatic copy-to-DB step.

## Rate-limit safety

The adapter enforces a rolling 60-second sliding-window limit of at
most **300 reserved requests per minute per Python process**.
This includes failed HTTP requests. A smaller configured limit is
allowed; values over 300 are clamped. The adapter shares a limiter
between FinEdge clients in one process and respects HTTP 429
`Retry-After` cooldown; no automatic 401, 429 or 5xx retry storm.

**Important:** FinEdge's account quota is shared across applications.
A rate limiter in one process cannot coordinate multiple PCs,
Render instances, or independent scripts. Operate from **one FinEdge
worker/process at a time**, or implement an approved centralized,
durable distributed quota coordinator before running multiple
instances. This version must not be described as global account-wide
rate limiting. Use a conservative limit lower than 300 if other
clients share the same FinEdge credential.

The detailed schema and entitlement behavior have not been verified
with your API key, which was not supplied. In particular, the
provider does not assert that ROCE, ROE, growth and ownership fields
have comparable units or usable as-of evidence until checked.
