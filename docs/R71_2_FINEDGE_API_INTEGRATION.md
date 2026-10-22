# FinEdge fundamentals integration

Updated 2026-10-22. FinEdge is the configured external fundamentals source for
backend financial-data retrieval. The user confirmed `FINEDGE_API_KEY` is already
stored on the Render backend. No key value is stored in this repository.

## Backend configuration

```text
FINEDGE_API_KEY=<existing Render secret>
FINEDGE_ENABLED=true
FINEDGE_RATE_LIMIT_PER_MINUTE=280
FINEDGE_CACHE_TTL_SECONDS=21600
```

The active Render reference includes these settings, with `sync: false` for
the key. Keep the existing secret when applying it. A key enables the provider
when `FINEDGE_ENABLED` is absent; an explicit false disables it. Only the backend
needs the FinEdge secret. The webapp uses its existing TrendForge admin header.
Manual Render services may need their environment settings updated directly;
changing this file alone does not update a dashboard-managed service.

## Data flow

1. An authenticated user opens Fundamentals. The page requests
   `GET /fundamentals/finedge/readiness`; this performs no upstream request.
2. Load a symbol using `POST /fundamentals/finedge/fetch` with JSON:
   `{"symbol":"ITC","statement_type":"c","force_refresh":false}`.
3. On a cache miss the backend fetches profitability ratios, leverage ratios,
   growth metrics and quarterly shareholding (four requests per symbol).
4. Subsequent requests for the same symbol and statement type use a six-hour
   in-memory cache. Consolidated and standalone statements have separate keys.
   Concurrent requests coalesce into one fetch. Cache entries are capped at 512.
5. The webapp shows the source groups and offers a JSON download. A refresh
   checkbox explicitly bypasses the cache. Cache hits consume zero new API calls.

Both endpoints require `X-TrendForge-Admin-Key`, including in factory-created
test/local applications. The symbol and statement type are validated before
provider work. Readiness does not prove that a token is accepted or that every
symbol is included in the account plan.

## Quota and failure handling

The default cap is **280 requests per rolling 60 seconds**, below the account's
stated 300 calls/minute. Values above 300 are clamped. All clients sharing a key
in one Python process share the most conservative requested cap, including failed
calls. A lower cap cannot create a separate quota. Waiting for capacity no longer
blocks health/cooldown updates.

HTTP 429 establishes a Retry-After cooldown. There are no automatic retry storms.
Both numeric delays and HTTP-date headers are supported, including delays longer
than five minutes. Valid provider cooldowns are not shortened. Explicit
`from_env()` overrides take precedence without duplicate keyword errors; an empty
rate-limit setting uses 280, while malformed values produce a sanitized
configuration error.
Failed, partial and explicit upstream error responses are not stored as successful
reports. No missing financial metric is replaced with zero. Transport errors are
sanitized because the upstream protocol uses a query token; redirects are rejected.

This limiter is **process-local**, not a global account coordinator. Run one
backend worker for this account, or split the total budget across independent
clients. CLI tools, other services and redeploying processes consume the same
account quota and do not share this in-memory limiter. The six-hour cache also
expires on process replacement. A distributed quota/cache requires a shared store.

## Schema and scanner boundary

Source JSON is retained with symbol, statement family and retrieval time.
Retrieval time is not substituted for a fiscal period or publication date.
The existing reviewed SQLite fundamentals continue to feed scoring. Live API
values require verified field names, units, periods and source evidence before
mapping into those scanner-ready fields. No BUY/SELL or execution gate is changed
by successful transport.

Authenticated FinEdge responses could not be inspected from the execution
workspace: the key is on Render, and the public docs endpoint returned HTTP 403.
The previously documented host/auth/path contracts still require a live account
probe before claiming production coverage. Different free/trial plans may expose
different symbols; do not assume a 300/minute quota means NIFTY 500 entitlement.

Sources to verify against the account documentation:
- https://www.finedgeapi.com/
- https://github.com/marketcalls/StockLens/blob/main/docs/prd/02-data-source-inventory.md

## Existing CLI

`python -m scripts.finedge_fundamental_candidates --symbols ITC,RELIANCE,HDFCBANK`
prints a plan without network work. Add `--collect --out <new-file.json>` to
fetch up to 25 symbols per batch. It uses server/process environment credentials
and does not share the backend cache across processes. Prefer backend fetches
when using the same account concurrently. Candidate exports are exclusive-create.

## Validation and deployment

Offline tests cover authentication, symbol validation, cache expiry/force refresh,
statement isolation, duplicate-request coalescing, shared quotas, error redaction
and exclusion of provider errors from cache. No real account request was made in
this workspace. Deploy the tested release through the normal CI gate, then verify
readiness and one entitled symbol from the running Fundamentals page.

After main-branch CI passes, the `render-deployment` job polls the public service
for up to ten minutes and requires this exact commit SHA from `/production/health`,
HTTP 200 from `/livez` and HTTP 200 from `/app/`. This is a read-only verification
of the existing Render auto-deploy, not a paid-resource provisioning action.

Local validation: 1,285 tests passed, 2 skipped, with the existing Starlette/httpx
deprecation warning. Compilation, dependency consistency, deployment preflight
and whitespace checks passed. A Streamlit page smoke test verified backend
readiness, symbol loading and returned source rendering using injected fixtures.
