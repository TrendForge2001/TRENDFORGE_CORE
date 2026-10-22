# Open issues and fix batches

## Current batch status — 2026-10-22

The audit below is historical. B01, B02, B04 and B05 were released previously.
Release `29ddf36` passed GitHub Actions; the Render verifier confirmed its exact
SHA with `/livez`, `/app/` and `/production/health` HTTP 200
([release checks](https://github.com/TrendForge2001/TRENDFORGE_CORE/actions/runs/39769469800)).

The released B03 policy requires verified storage or explicit ephemeral simulation
for production paper entries and persists runtime kill state alongside trades.
See [B03 validation and activation](B03_PAPER_ENTRY_DURABILITY.md).

B06's broker boundary is implemented in `67aa524` and included in this branch.
Its Actions run has not registered; merge and deployment remain pending.
See [B06 policy and validation](B06_BROKER_EXECUTION_BOUNDARY.md).

B07 adds required dependency/secret reports, broader scoped analysis and the
supported test-client transport. A resolver-derived lock refresh fixes 35 of 38
unique advisory IDs. Three remaining SDK advisories block release; no risk
waiver or suppression was added. See [B07 evidence and blockers](B07_CI_SECURITY_EVIDENCE.md).

Next release work: resolve the SDK dependency blockers and verify remote CI,
then B08 authenticated production acceptance and B09 webapp migration. Live persistent-disk restart
acceptance remains a B08 gate; local close/reopen tests do not establish cloud
durability. Controls are process-local and do not coordinate multiple workers.
Broader read admission and domain-result/notification audits remain hardening work.

## Original audit

Reviewed 2026-10-21 against local `work` at `89e7297`, including the preceding
uncommitted safety changes. This is a local repository review; live GitHub CI,
Render deployment and authenticated Kite acceptance are not verified here.

## Overall status

### Follow-up implementation

The release branch includes the earlier safety work and incorporates upstream
`2cd97db` (R72.5.9, five consolidated navigation entries). The findings below
are retained as the original audit record. Current implementation status:

- F01: private portfolio, P&L, performance and paper-workspace aliases are
  protected in production; factory-created production applications also install
  the security middleware. Positive and negative authentication tests were added.
- F02/F05: both validation runtimes serialize admission, refuse overlapping
  forced execution, retain thread handles/metadata and use run-specific temporary
  filenames. Deterministic event-controlled tests cover concurrent requests.
  These are process-local controls; distributed job coordination remains future work.
- F03/F04: canonical database resolution is shared; root/temporary mounts are
  rejected. Verified storage additionally requires explicit operator confirmation
  after restart recovery testing. No real recovery test has been performed here.
- F06: frontend/backend now agree on an admin-header-authenticated JSON export.
- F11: the production-lock job runs the full regression suite. B07 adds mandatory
  dependency/secret checks and scoped analysis, and resolves the test-client
  deprecation. SDK advisories and remote release evidence remain blocked.
- F12: current Streamlit design and watchlist filtering were updated; Next.js
  migration remains future work. See `WEBAPP_DESIGN_UPDATE.md`.
- F08: B03 implements the paper durability policy; actual persistent-disk
  restart acceptance remains a B08 gate.
- F10: B06 centralizes broker guards and restricts retries to known reads.
- F07/F09: B05 implements safe API errors and provider workload controls;
  broader domain-result and notification audits remain hardening work.
- F13 and the F11 dependency/remotely verified release gates remain open.

The historical status and baseline counts below refer to the original audit,
not the final release branch. See release validation evidence for current results.

Integration candidate; production acceptance remains open. The preceding batch
adds production scanner authentication and captures validation arguments per
request, but does not finish runtime concurrency, privacy or durability work.
Those changes remain uncommitted and undeployed. Preserve them when applying
the batches below. Passing offline tests does not close production gates.

## Findings

| ID | Priority | Evidence | Issue and impact |
| --- | --- | --- | --- |
| F01 | P0 | Reproduced with injected fake services | `GET /workspace/paper-portfolio` and `GET /portfolio` return private fixture positions/holdings without an admin header under `secure_application()`. `/paper/positions` returns 401 under the same configuration. The middleware protects the `/paper` namespace, but the workspace alias and broker portfolio reads bypass it. See `api/trading_workspace_router.py`, `services/trading_workspace_service.py:paper_portfolio`, `api/app.py:portfolio_snapshot`, `api/production_runtime.py:_protected_admin_request`. |
| F02 | P1 | Reproduced with two event-controlled workers | R71.5 `force=True` starts a second worker while the first is alive. Completing the first overwrites the second run's state. Both write the same `.json.tmp` and final output path. Captured capital/chunk size fixes argument sharing only. R72.5.3 also performs an unlocked check-then-start; review both runtimes. See `services/technical_validation_runtime.py:start_validation`, `services/multi_strategy_validation_runtime.py:start_validation`. |
| F03 | P1 | Reproduced locally | `DATABASE_PATH=/tmp/trendforge-audit.db`, `TRENDFORGE_PERSISTENT_MOUNT=/` produces `verified_persistent=True`. Explicit mount configuration is an improvement, but mountpoint/path containment does not establish restart durability. Reject unsuitable roots and separate mounted/configured status from verified recovery. `core/storage_config.py` still returns `durability_verified=False`, creating inconsistent diagnostics. |
| F04 | P1 | Source review | `storage_health()` counts `TRENDFORGE_DATA_DIR` as configured, but obtains its database from `core.database.database_path()`, which only reads `DATABASE_PATH`. `resolve_storage()` supports the data-directory override. Different components can therefore report/use different paths. Resolving paths before testing `is_absolute()` also makes that check ineffective. |
| F05 | P1 | Source review; response shape confirmed with fast completion | Worker completion replaces the state dictionary and drops `_thread`, capital and chunk size. A fast worker can finish before `start_validation()` returns. The new regression accesses `_thread` and assumes a running response, so it can fail depending on timing. Status can lose the worker handle while work is still completing. |
| F06 | P1 | Source contract mismatch | R71.5 UI expects `export_token` from start, but runtime never returns it. UI sends that token in a URL and labels the download Excel; backend uses `TRENDFORGE_R715_EXPORT_TOKEN` and serves JSON. The normal download flow cannot complete. See `webapp/pages/technicals.py` R71.5 download block, `api/app.py:technical_validation_export`, `docs/R71_5_TECHNICAL_VALIDATION.md`. |
| F07 | P1 | Source review | Unexpected errors are exposed through `detail=str(exc)`, worker `error` strings, and public diagnostics containing local paths/bootstrap errors. Existing scanner middleware only covers three read paths and catches uncaught exceptions; it does not sanitize deliberately returned HTTP errors. Review health, workspace and legacy scanner routes. Avoid blanket removal of useful, validated client errors. |
| F08 | P1 | Source review | Active Render configuration remains free/ephemeral. Paper positions, kill state and execution lineage can be lost across instance replacement. Existing policy explicitly allows paper routes without durable disk, so this requires an explicit durability policy and compatibility update, not merely changing health labels. Preserve emergency kill/exit operations when introducing new entry gates. |
| F09 | P1 | Source review | Newly added scanner guards are applied through production middleware on the module-level app. `create_app()` returns an app without that wrapper. Alternate factory deployment can omit protections. Expensive public reads such as `/universe/nifty500?refresh=true` can also trigger provider work. Define intended public reads and enforce protected execution consistently at composition boundaries. |
| F10 | P2 | Source review | `api/kite_service.py` direct place/modify/cancel wrappers do not enforce a central live-trading guard. No API exposure of these wrappers was established in this review. Treat as a latent integration risk and verify callers before changing broker behavior. |
| F11 | P2 | Workflow review | Full CI tests install broad `requirements.txt`; the production lock job checks versions/imports but does not run the suite. No vulnerability, secret-scan, lint or type-check gate is present in that workflow. Current Starlette/httpx deprecation remains open. Dependency consistency is not a vulnerability scan. |
| F12 | P2 | Documentation and navigation review | R72.0 claims 22 reachable pages; current navigation exposes seven. Runtime/protocol docs and the R71.5 export behavior disagree. Replacement webapp design and deployment choice have not been implemented or validated. |
| F13 | Release gate | Existing acceptance ledger | Release SHA/CI, Render SHA, authenticated provider checks, browser checks, controlled scanner accounting and restart recovery remain pending or blocked in `docs/R72_5_8_2_PRODUCTION_ACCEPTANCE.md`. |

P0 means close before public deployment; P1 means close before production
acceptance; P2 means scheduled hardening or product work. These are review
priorities, not claims that live exploitation or data loss occurred.

## Execution batches

| Batch | Priority / dependencies | Work | Acceptance checks |
| --- | --- | --- | --- |
| B01 — Private data and route authorization | P0; first | Close F01. Inventory broker/paper/history/performance reads and aliases. Add explicit authentication where needed; cover factory-created and production apps (F09). Keep intended public market reads documented. | Missing/wrong keys cannot obtain fixture holdings or positions through any alias; correct key succeeds. Disabled credentials fail closed. UI configured with credentials still works. |
| B02 — Validation lifecycle and deterministic tests | P1; after B01 | Close F02/F05 in both validation runtimes. Serialize start admission; prevent force from launching parallel work; keep worker handles outside replaceable public state; bind progress/completion to run ID. Use distinct per-run output files and a controlled latest pointer. Replace timing-dependent tests with events/barriers. | Simultaneous requests create one worker; force while active is rejected or returns existing run; stale completion cannot replace current state; fast completion/failure has a stable response contract; files and exports correspond to the requested run. |
| B03 — Storage identity and durability policy | P1; after B01 | Close F03/F04/F08. Resolve one canonical DB path. Reject `/`, temporary paths and invalid mount configuration for durability claims. Distinguish configuration, mount detection and measured recovery. Decide durable paper entry policy or clearly explicit ephemeral simulation mode. Update Render reference/env docs without provisioning resources. | Root/tmp false positives fail; nested paths and symlinks resolve correctly; all diagnostics use the same database; write/restart/read-back evidence is required before claiming recovery; entry gates preserve kill/exit controls. Real restart test is a B08 deployment gate. |
| B04 — Export contract | P1; after B01/B02 | Close F06. Prefer existing admin-header auth over URL secrets; update backend, frontend and documentation together. Choose JSON download or implement actual XLSX generation. Bind export to a completed run. | Normal UI download works; unauthenticated export fails; filename, MIME and file contents agree; no secret appears in URL; incomplete/unknown run returns a clear response. |
| B05 — Safe errors and provider workload limits | P1; after B01 | Close F07 and remaining F09 workload gaps. Introduce safe error codes and correlation IDs; redact logs. Separate or protect explicit refresh actions, and add appropriate caching/rate/concurrency limits to provider-backed routes. | Injected exception containing a sentinel secret never reaches response or unredacted logs; correlation remains useful; provider timeout returns bounded safe failure; unauthenticated refresh cannot trigger work; normal cached reads continue. |
| B06 — Broker execution boundary | P2; before any live feature | Close F10. Audit callers; centralize guarded execution for place/modify/cancel. Keep current disabled defaults and establish explicit emergency-operation policy. | Fake broker receives no call when execution disabled; enabled-path contract tests cover allowed requests without real orders; read-only Kite features remain available. |
| B07 — CI and release evidence | P2; can follow B01 in parallel as separate work | Close F11. Run full suite under the production lock; add scoped lint/type checks and secret/dependency scans with actionable reports. Resolve test-client deprecation compatibly. | Python 3.11/3.12 jobs and locked-production test job pass on release SHA; scans produce reviewed reports; lock graph remains consistent; deterministic concurrency tests are included. |
| B08 — Production acceptance | Release gate; after B01–B05/B07 | Close F13. Reconcile deployed SHA, inspect CI/deploy results, probe readiness and Kite read-only data, verify browser navigation, run controlled no-order scanner checks, and perform persistence recovery test when appropriate resources/access are available. | Dated evidence per gate in existing acceptance ledger; scanner completed + error + deferred equals requested; recovery checks preserve state. Do not mark blocked gates passed from offline tests. |
| B09 — Webapp design and first migrated screen | Product; after B01/B04 API contracts | Close F12. Reconcile seven active pages and legacy requirements. Produce a responsive design inspired by Liquide research summaries, Kite watchlist/chart density and Streak strategy workflows. Build a TypeScript/Next.js shell with watchlist/detail first, FastAPI backend and server-side credential handling. Assess Render Node deployment beside the API; compare Vercel for frontend hosting. | Reviewable design artifact; authenticated read-only watchlist/detail using real API contracts; loading/error/stale states; keyboard/mobile checks; credentials absent from browser bundles. |
| B10 — Feature migration and cutover | Product; after B08/B09 | Migrate scanner/results, strategies/backtests, paper portfolio, broker portfolio, fundamentals and corporate actions in reviewed increments. Choose durable database and background job hosting based on actual deployment constraints. | Feature parity checklist, browser tests, job progress and cancellation policy, deployment smoke tests and rollback plan before Streamlit retirement. |

Recommended next implementation: B01, then B02 and B03, then B04/B05.
Keep each batch independently reviewable and record its test evidence. Commit
and release tracking must include the preceding uncommitted safety work; it is
not yet present in a deployed release.

## Verification performed for this review

- Reproduced unauthenticated portfolio disclosure with injected fake services;
  no production data or broker calls were used.
- Reproduced root-mount persistence false positive with temporary environment
  overrides only.
- Reproduced overlapping forced validation and stale state overwrite with two
  event-controlled fake workers and temporary output files.
- Forced a valid fast-completion schedule and observed that the return payload
  omits capital/chunk-size metadata and the final state loses `_thread`.
- Full local suite: **1,249 passed, 2 skipped**, with one Starlette/httpx
  deprecation warning. `git diff --check` passed. A green result does not
  disprove the controlled concurrency reproductions above.

This document adds a fix plan; application code was not changed during this
review. Existing uncommitted application edits were retained.
