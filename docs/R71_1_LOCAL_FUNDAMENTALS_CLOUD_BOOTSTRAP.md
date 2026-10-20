# R71.1 — Local Fundamentals Completion, Backup & Cloud Bootstrap Handoff

**Scope:** feature branch only. R71.1 prepares a cloud release on the Windows PC. It
does **not** write to Render, change production FastAPI or its env vars,
enable ephemeral uploads, change scoring/eligibility, or enable broker orders.

## Preconditions

- Windows Python 3.12 environment and TrendForge checkout are available.
- Set `DATABASE_PATH` to the **existing local** SQLite database, for example
  `C:\TrendForgeData\database\trendforge.db`. The CLI requires an existing
  complete 23-table schema and never creates a replacement DB.
- Download a current **official NIFTY 500 constituents CSV** from NSE.
  Its 500–525 constituent rows must be unique and contain a Symbol column.
  Supplying and SHA-pinning a CSV ensures file identity, **not authenticity**;
  users must verify provenance and current index membership separately.
- Obtain the R69.4 **NIFTY500 completion workbook** from the webapp or
  existing local pipeline. Populate actual numbers and source evidence:
  source type, source, source reference, as-of, ROE FY, EPS 3Y CAGR period,
  and shareholding dates as applicable. Do not use the scanner gaps CSV as
  financial values. Never fabricate missing metrics.
- Production startup bootstrap enforces an empty-only restore and a 1 MiB
  JSON bundle limit. This workflow explicitly refuses to bypass either.

## Run from PowerShell on Windows

```powershell
cd C:\Users\Lenovo\Desktop\TrendForge
$py = ".\.venv\Scripts\python.exe"
$db = "C:\TrendForgeData\database\trendforge.db"
$constituents = "$env:USERPROFILE\Downloads\ind_nifty500list.csv"
$completion = "$env:USERPROFILE\Downloads\trendforge_fundamental_completion.xlsx"

# Obtain the SHA256 independently from the actual file you downloaded.
$pin = (Get-FileHash $constituents -Algorithm SHA256).Hash.ToLowerInvariant()

# Stage 1: validate without altering source or cloud.
& $py -m scripts.r71_local_fundamentals_sync preview `
  --db-path $db --universe-file $constituents `
  --universe-sha256 $pin --completion $completion

# Stage 2: only after a clean preview, prepare a NEW isolated handoff.
# Pick a unique output folder each time; existing folders are never replaced.
$out = "C:\TrendForgeData\fundamentals\r71-1-handoff-001"
& $py -m scripts.r71_local_fundamentals_sync prepare `
  --db-path $db --universe-file $constituents `
  --universe-sha256 $pin --completion $completion --out-dir $out
```

If your local database is stored elsewhere, use its existing actual path.
For prior R70.2 local runtime installs, inspect the persisted user
`DATABASE_PATH` and `TRENDFORGE_DATA_DIR` values first. The script refuses
a missing or degraded database; **do not** point at Render's
`database/trendforge.db` or a newly generated empty database.

### Safety contracts

- `preview`: no SQLite fundamentals are changed; unknown members, invalid
  source evidence, overwrites, and empty batches block the next stage.
- `prepare`: creates `original-backup.db` using SQLite's online backup API
  (WAL-aware), then `completed-working.db` from that backup; applies
  completion **only to the isolated working copy**. The original local DB is
  unchanged. Source and backup integrity are checked.
- After a clean apply the existing canonical bootstrap exporter serializes
  the working copy to `fundamentals-bootstrap.json`. The existing
  `read_verified_bundle` verifies file and payload SHA-256.
- `handoff-manifest.json` records the constituent pin, completion-file
  hash, backup hash, completed-record counts and bootstrap SHA. Output is
  never overwritten and nothing is pushed to Git or Render.
- Strict evidence and no-overwrite policies remain in force. A full
  500-stock complete snapshot may exceed the current **1 MiB** Render
  secret-file cap; fail closed rather than silently truncate or shard it.
- The local working database is **not** automatically promoted to the
  user's live Windows database; doing so would require a stopped writer,
  audited backups and an explicit controlled promotion procedure.

## Render cloud bootstrap: approval gate (NOT AUTOMATIC)

**Do not upload or redeploy this handoff to production without a separate
approved migration plan.** The existing production bootstrap:
- loads a file from `FUNDAMENTALS_BOOTSTRAP_PATH` (default
  `/etc/secrets/trendforge_fundamentals_bootstrap.json`);
- requires pinned `FUNDAMENTALS_BOOTSTRAP_SHA256`;
- verifies the bundled payload SHA; and
- **skips** startup apply when the cloud SQLite fundamentals table already
  has data (`skipped_nonempty`).

Production already had **11 fundamentals** at this audit. Uploading a
new snapshot or changing its SHA **will not** update or merge those rows.
On the Render Free plan the SQLite database is currently ephemeral or
unverified; it is not a durable synchronization destination.

The future cloud cutover must include: preservation of existing cloud
records and evidence, a versioned rollback image/backup, authorized
activation strategy for a clean target, validation of the new bootstrap
SHA and record coverage, and a controlled rollback test. No service
restart, deletion, clearing fundamentals or enabling
`TRENDFORGE_ALLOW_EPHEMERAL_ADMIN_WRITES` is part of R71.1.

After separately approved cloud activation, download **read-only**
`https://trendforge-core.onrender.com/production/health` as JSON, then:

```powershell
& $py -m scripts.r71_local_fundamentals_sync verify-cloud `
  --manifest "$out\handoff-manifest.json" `
  --production-health-json "$env:USERPROFILE\Downloads\production-health.json"
```

Expected `status=verified` requires cloud
`bootstrap.status=applied`, a matching file SHA and pinned verification,
and the expected fundamental row count. `skipped_nonempty` is not
verification, and an ephemeral cloud DB is never considered durable merely
because bootstrap verification succeeds. R71.1 reports it separately.

## Known limitations and next acceptance gate

- Source financial values are **not** fetched automatically from Kite, Yahoo,
  Tijori or Screener; the operator supplies verified evidence.
- The SHA-pinned source CSV is not a cryptographic attestation by NSE.
- No automatic PC-to-Render network synchronization exists.
- Preparing the handoff does not immediately reduce cloud
  `DATA_INCOMPLETE` blockers. That requires an approved cloud cutover,
  rerunning scanner readiness and confirming fewer missing records.
- There is no programmatic way for this assistant to access the user's
  Windows SQLite files unless the user uploads them or runs local commands.
- Any future online synchronization must reconcile 11 existing cloud
  records without modifying the production storage guard.
