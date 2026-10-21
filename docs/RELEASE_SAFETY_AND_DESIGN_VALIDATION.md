# Safety and workspace design release validation

Date: 2026-10-21 (IST). Based on GitHub main `2cd97db` with the preceding
uncommitted safety changes included in this release branch.

## Delivered

- Production authentication for scanner execution and private portfolio aliases;
  production factory construction also installs the middleware.
- Request-scoped validation parameters, serialized worker admission in both
  runtimes, retained worker handles and distinct temporary output names.
- Canonical database path resolution and explicit persistent-mount/recovery
  confirmation requirements. Root and temporary filesystems cannot qualify.
- Correctly labelled JSON validation export using an admin header.
- Refreshed webapp theme, responsive workspace bar, watchlist search/sector
  filters, expandable CSV source controls and honest credential/health labels.
- Production-lock CI job extended to execute the full regression suite.
- Audit findings, fix batches and webapp design/deployment guidance documented.

## Local evidence

| Check | Result |
| --- | --- |
| Python 3.12 full regression suite | 1,273 passed; 2 skipped; one Starlette/httpx deprecation warning |
| Source compilation | Passed |
| Dependency consistency (`pip check`) | Passed |
| R72.5.7 deployment preflight | Passed |
| Unified Render ASGI import | Passed; `/health`, `/`, `/app`, core mount present |
| Actual Uvicorn smoke | `/livez` 200; portfolio/paper-workspace/P&L/performance reads return 401 without credentials |
| Chromium desktop and mobile preview | Rendered with labelled sample fixtures; search empty state verified; no Streamlit exceptions |
| Whitespace validation (`git diff --check`) | Passed |

The browser preview used fake market data solely for local layout inspection.
No broker orders, production scans or production state mutations were executed.
Runtime locks are process-local and do not replace a distributed job coordinator.

## External release gates

Git transport is available, but the GitHub API and Render HTTPS probes return
`Forbidden` / proxy CONNECT 403 from this environment, including after escalation.
No Render API key or deploy hook is available in the environment. Consequently:

- Live GitHub Actions success on the release commit has not been observed.
- Render deployment has not been triggered or verified by this session.
- No claim is made that production runs this release.
- Authenticated provider acceptance and real restart recovery remain open.

Publish the reviewed changes to a release branch. Merge/promote only after the
GitHub checks pass; then deploy the exact approved commit through the existing
Render service and check its deployed SHA, `/livez`, `/app/`, private-route
authorization and provider readiness. The active free plan is unchanged.

For a persistent disk service, configure `TRENDFORGE_PERSISTENT_MOUNT=/var/data`
alongside `DATABASE_PATH`. Set `TRENDFORGE_STORAGE_RECOVERY_VERIFIED=true` only
after a successful controlled write/restart/read-back check. A missing flag
deliberately keeps persistence-protected fundamental writes unavailable.

Remaining findings and batches are tracked in `OPEN_ISSUES_AND_FIX_BATCHES.md`.
