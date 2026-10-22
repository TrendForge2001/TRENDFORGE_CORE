# B03 — Paper entry durability policy

Implemented 2026-10-22 after the verified `29ddf36` release.

## Admission and recovery

Production paper entry now requires an enabled paper service, an inactive kill
switch, and either verified persistent storage or explicit ephemeral simulation.
Local development remains local simulation. The shared service checks admission
again immediately before opening a position, covering manual API calls, scanner
handoffs, strategy execution and scheduled/background entry. The direct API
also rejects blocked entries with HTTP 423 before constructing the service.
Existing admin authentication remains mandatory.

The default `TRENDFORGE_PAPER_ALLOW_EPHEMERAL_SIMULATION=false` blocks new
production entries on the active free Render service. An operator may explicitly
set it to true for disposable simulation. That setting does not enable paper
trading, release a kill switch, bypass risk limits, authorize broker orders or
unlock fundamental administrative writes. Simulated state may disappear with an
ephemeral instance. No paid resources are provisioned by this batch.

All repositories now resolve the same database as diagnostics: explicit
constructor paths take precedence, followed by `DATABASE_PATH`, then
`TRENDFORGE_DATA_DIR/database/trendforge.db`, then the legacy local path.
Production admission rejects an actual runtime database that differs from the
configured target. API, local diagnostics and entry policy share the same mount
and recovery checks; root, temporary and unsuitable mounts remain ineligible.

Runtime kill state uses the paper database's existing `settings` table. The
service restores it before admitting entries. Invalid or unreadable state locks
entries with safe diagnostic references. Activation remains effective in memory
if persistence fails; clearing commits before releasing the in-memory kill.
SQLite operations on a shared connection are serialized, and failed writes roll
back before releasing that connection. A later query cannot commit a failed clear.
Readiness exposes `entry_storage_policy`, `kill_switch_storage` and
`can_open_new_positions`. The UI disables new-entry actions and ignores stale
enabled toggles while preserving scans, previews, monitoring, exits and kill
controls. It distinguishes verified storage from explicit disposable simulation.

## Durable activation

Keep paper entry disabled and the environment kill switch active while preparing
storage. The persistent Render manifest remains an opt-in reference. Configure
the actual persistent mount and canonical database path, preserve existing data,
and perform a controlled backup/write/restart/read-back check covering trades,
open positions, execution lineage, realized-risk accounting and saved kill state.
Only then set `TRENDFORGE_STORAGE_RECOVERY_VERIFIED=true`. A configured path or
successful local reopen is insufficient. Review readiness before separately
enabling entry and releasing the relevant kill controls.

No cloud restart or persistent-disk acceptance was performed in this batch.
Local tests exercise real temporary SQLite close/reopen recovery and failed
read/write behavior without placing orders or touching production positions.
Current admission locks and cached kill state cover one process; multiple workers
require shared coordination before deployment.

## Validation

Local Python 3.12 full suite: **1,439 passed, 2 skipped**. Compilation,
dependency consistency, deployment preflight and whitespace checks passed.
The existing Starlette/httpx test-client deprecation remains scheduled for B07.

Regression coverage includes default blocking, explicit simulation, retained
enable/kill/risk gates, mount/recovery revocation, runtime database identity,
storage failure redaction, SQLite commit visibility, saved-kill recovery,
monitor/strategy exits while blocked, background entry races, and actual Streamlit
interaction with disabled entry and available safety controls.

Release CI runs Python 3.11/3.12, the production lock and scoped FinEdge analysis.
After merging, the Render verifier requires the exact release SHA and HTTP 200
for `/livez`, `/app/` and `/production/health`.
