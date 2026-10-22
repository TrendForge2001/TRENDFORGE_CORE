# B05 — Safe errors and provider workload

Implemented 2026-10-22, following the verified `e087e6e` release.

## Behavior

- Factory-created APIs share a safe error boundary. Unexpected exceptions and
  HTTP server errors return a stable error code, a 12-character reference and
  `X-Error-Reference`. Logs record route templates, exception types and references,
  excluding exception messages, request query strings and tracebacks. Intentional
  validation/authentication/client errors retain their existing contracts.
- Legacy scan provider failures and invalid pipeline results return HTTP 503.
  Fatal scan audit/notification messages use a safe message; the response and
  persisted failure share a reference. Continuation cleanup errors remain logged
  with their run ID without raw exception tracebacks.
- Production `/health` and `/production/health` return public summaries.
  `?details=true` requires the admin header. The public production report retains
  `deployment.render_git_commit` for exact-release verification. Scanner runtime,
  configured import/snapshot and NSE failure diagnostics retain safe references.
- Explicit `refresh=true` on `/universe/nifty500` and
  `refresh_universe=true` on `/fundamentals/readiness` require authentication
  before factory/provider work. Ordinary cached reads remain public.
- Watchlist quote snapshots, including failed fetches, are shared for five seconds.
  Concurrent polls share one request; only three normalized index cache keys are
  admitted. Responses expose quote age and fetch time; unavailable prices remain
  null. Stock-detail input is validated before provider access; provider
  `ValueError`s return a safe service failure.
- NSE constituent cold reads share one fetch per index. An uncached failure
  receives a five-second retry cooldown. Existing six-hour validated/stale
  constituent caching is retained. Fallback warnings preserve source freshness
  information and omit raw exceptions.

## Validation

Local Python 3.12 regression suite: **1,363 passed, 2 skipped**. Dependency
consistency, source compilation, deployment preflight and whitespace checks passed.
One existing Starlette/httpx test-client deprecation warning remains for B07.

Regression coverage injects sentinel credentials into HTTP/unhandled failures,
provider timeouts, provider `ValueError`s, runtime health, input-file failures,
NSE fallbacks and public diagnostics. Tests assert safe responses and logs,
stable correlation, unchanged client validation, authenticated refresh admission,
TTL expiry, recovery and deterministic concurrent request coalescing.

The release workflow runs Python 3.11/3.12, the exact production dependency lock,
FinEdge lint/type checks and a post-merge Render verifier. The verifier requires
the merged SHA and HTTP 200 for `/livez`, `/app/` and `/production/health`.

## Remaining limits

Caches, locks and cooldowns apply to one Python process. Stock-detail and other
market/provider read routes still need a broader admission policy before scaling
to multiple workers. The API boundary does not rewrite successful domain result
payloads or arbitrary logs from third-party components; deeper result/notification
auditing remains scheduled. No live orders, authenticated broker scan, persistence
restart or paid-resource provisioning was performed in this batch.
