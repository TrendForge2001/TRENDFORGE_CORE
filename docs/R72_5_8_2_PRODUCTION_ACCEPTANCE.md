# R72.5.8.2 — Production acceptance and audit-cleanup gates

## Scope and safety

This batch addresses silent scan-continuation restoration errors and checks production readiness. No broker orders, paper entries, credentials, paid resources, or destructive restart tests are authorized. Never publish Kite or admin secrets.

## Acceptance evidence

| Gate | Required evidence | Status |
| --- | --- | --- |
| CI | Python 3.11, 3.12 and dependency audit green on release SHA | PENDING |
| Render | Live deploy SHA equals merged GitHub SHA; build and startup successful | PENDING |
| Liveness | Post-deploy `/livez` HTTP 200 in Render logs | PENDING |
| UI shell | Post-deploy `/app/` HTTP 200 in Render logs | PENDING |
| Scanner read | Authenticated readiness/status/results calls with schema, accounting and timestamps | BLOCKED: needs authenticated production probe |
| Kite | Read-only instrument mapping and completed candles for RELIANCE/TCS/SBIN | BLOCKED: requires authenticated provider check |
| NIFTY 100 | Verify member count and selector in running UI, not just source contract | BLOCKED: browser validation |
| Scanner run | Controlled no-order scan, completed + error + deferred = requested, inspect per-symbol errors | BLOCKED: requires authorized run |
| Persistence | Verified persistent mount and read-back after restart without trading data loss | BLOCKED: durable disk and safe restart approval |
| Audit cleanup | Failed restore emits exception log with run ID and still releases execution guard | COVERED BY CODE AND REGRESSION TEST; CI PENDING |

## Known limitations

The new storage diagnostics explicitly report `durability_verified: false` until a mount/restart test is performed. Existing offline tests inspect source and do not substitute for production acceptance. Do not declare all seven risks closed based only on liveness.
