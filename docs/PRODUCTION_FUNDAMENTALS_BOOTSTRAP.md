# Production Fundamentals Bootstrap

TrendForge keeps the active `render.yaml` on the Free plan. Free Render web
services use ephemeral filesystems, so SQLite changes are not durable there.
The production entrypoint therefore supports a verified secret-file bootstrap
on every empty startup and disables HTTP mutations unless storage is verified
persistent.

## Create the bootstrap bundle

Run against the verified local database:

```powershell
.\.venv\Scripts\python.exe -m scripts.fundamental_bootstrap export `
  --out "$env:USERPROFILE\Downloads\trendforge_fundamentals_bootstrap.json"
```

Record the `file_sha256` printed by the command.

## Configure Render Free for safe read-only production

In Render **Environment**:

1. Add secret file `trendforge_fundamentals_bootstrap.json` using the exported
   file contents. Render exposes it at
   `/etc/secrets/trendforge_fundamentals_bootstrap.json`.
2. Add `FUNDAMENTALS_BOOTSTRAP_SHA256` with the exported `file_sha256`.
3. Add a strong `TRENDFORGE_ADMIN_API_KEY` of at least 32 characters.

After redeploy, `/production/health` should report bootstrap `applied` (or
`skipped_nonempty`) and storage `ephemeral_or_unverified`. HTTP fundamental
writes remain disabled on Free storage so a successful response can never
pretend an ephemeral write is durable.

## Enable true SQLite persistence

A Render persistent disk requires paid compute. After separately approving the
billing change, upgrade the current service and attach a 1 GB disk at
`/var/data`, then set:

```text
DATABASE_PATH=/var/data/trendforge.db
```

`deploy/render-persistent-disk.yaml` is an opt-in reference configuration; the
active `render.yaml` is intentionally left unchanged.

When `/production/health` reports `storage.verified_persistent=true`, admin
mutations are enabled for requests carrying:

```text
X-TrendForge-Admin-Key: <TRENDFORGE_ADMIN_API_KEY>
```

The bootstrap is empty-only. Once a persistent database contains fundamentals,
startup never overwrites them.
