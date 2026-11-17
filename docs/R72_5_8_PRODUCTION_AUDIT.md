# R72.5.8 — Production End-to-End Functional Validation & Scanner Reliability Audit

## Scope

Production service: `trendforge-core`, Render workspace `tea-daoa153m8hqs73ds6hgg`. Preserve all credentials and disable live order execution throughout the audit.

## Acceptance gates

| Gate | Required evidence |
| --- | --- |
| Deployment | Render live deploy SHA equals GitHub main SHA; build and runtime logs show no startup errors. |
| Liveness | `GET /livez` returns HTTP 200 repeatedly; it must not depend on external providers. |
| Security | Anonymous access to privileged routes is denied; no credentials appear in logs. |
| Strategy registry | `GET /technical/strategies` returns documented strategies. |
| Scanner readiness | `GET /technical/multi-strategy/readiness` returns a serializable response with explicit provider and universe diagnostics. |
| Scanner results | `GET /technical/multi-strategy/results` returns structured results or an explicit empty/no-run state; no silent blank page. |
| Scanner status | `GET /technical/multi-strategy/status` exposes progress and errors without raw thread objects. |
| Universe/watchlists | NIFTY 100 selection remains populated from an identified constituent source; `GET /watchlists` reports explicit data. |
| Scan execution | Authorized, controlled scan completes for RELIANCE, TCS, SBIN with accounted=3, errors=0, and explicit provider provenance. Run only after confirming safe operation. |
| Backtesting | Historical validation produces deterministic, non-trading output and retains run lineage. |
| Paper monitoring | With kill switch engaged, no new entries; separately validate paper-only exit attribution in isolated tests. |
| Persistence | Confirm storage mount durability; successful SQLite writes alone do not prove persistence across redeploy. |

## Release rules

- Fail closed on missing credentials, stale market data, provider errors, incomplete scans, or unverified durable storage.
- Never treat `GET /livez` alone as proof of scanner or trading readiness.
- No POST scan, broker, or paper execution calls from anonymous production smoke tests.
- Record status as PASS, FAIL, BLOCKED, or NOT_TESTED, including the evidence timestamp and deployed SHA.
- Do not enable live trading or paid infrastructure as part of this batch.

## Initial evidence (2026-10-21)

Render reports `dep-dbc52qm8bjmc73d6mjl0` LIVE on SHA `4f2d6c7e355e681d9c21f22ab7e0c6b50bdfab09`. Build and deployment events succeeded, and `/livez` logged HTTP 200. All deeper functional gates remain NOT_TESTED until runtime evidence is captured.
