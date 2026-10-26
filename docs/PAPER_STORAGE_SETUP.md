# Resolve the paper storage requirement

`persistent_storage_required` means the backend cannot verify a persistent disk
and restart recovery. `paper_runtime_not_ready` is a related entry block; it does
not by itself indicate a strategy failure. Applying the automation switch cannot
create storage or override readiness.

## Use the PC disk (selected operating mode)

Render cannot mount a drive on your PC. Run the paper engine and the same
five-tab webapp on the PC. Its SQLite database then remains on your local drive
across application restarts and Git updates. The existing Render deployment is
a separate instance and will continue to block entries until its own storage
is verified. It does not sync or read the PC ledger.

Install **64-bit Python 3.12** on Windows, download/clone the updated repository,
then run this command in PowerShell from its root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\Start-TrendForgePaper.ps1
```

The launcher creates a private Python environment and installs pinned packages
on the first run. The default data location is
`%LOCALAPPDATA%\TrendForgeCore\database\trendforge.db`. This folder is outside
Git; your existing repository and old databases are not deleted or overwritten.
If an existing PC book is in `C:\TrendForgeData`, select it explicitly:

```powershell
.\scripts\windows\Start-TrendForgePaper.ps1 -DataRoot C:\TrendForgeData
```

**First run:** it records a SQLite probe and a matching file on that fixed local
drive. Entries remain blocked. Stop the launcher with Ctrl+C and run the same
command again. On the second process launch, it reads back the probe, verifies
integrity and preserves the saved ledger. Missing or mismatched evidence stops
startup instead of creating an empty replacement book. The existing position
restoration gate still has to succeed.

Open **http://127.0.0.1:10000/app/** on that PC. The launcher generates two separate local login files in
`%LOCALAPPDATA%\TrendForgeCore\private`: `webapp-key.txt` for **Manual Access Key**
and `admin-key.txt` for **Admin API Key**. Open these locally and copy their values
into the sign-in fields. The admin key is required for paper controls.

For current Kite credentials, create `private\kite.env` inside the data folder
with `KITE_API_KEY`, `KITE_API_SECRET` and `KITE_ACCESS_TOKEN` assignments. The
launcher loads only those three fields; update the manual access token daily.
Keep this file local and do not commit or send its contents. Existing process
credentials and a private repository `.env` are also supported. Keys are never
printed in startup logs. Real brokerage execution stays disabled.
Review readiness and enable automation with the existing switch; it always starts
OFF after a restart. Keep the PC awake, connected to the internet, and the launcher
running during market hours. Closing the launcher stops monitoring.

The server binds only to localhost. No PC drive, database or API is exposed to
the internet, and no paid Render resources are created. Access through the Render
URL would need a separately configured secure connection to the PC; this setup
does not create that connection.

## Render storage alternative

The optional M02 launcher can generate and check matching database/file restart
evidence automatically on a real mounted disk. See
[M02/M03 activation](M02_M03_OPERATIONS.md) before changing the service start
command. It requires the existing book to be restored first and does not attach
paid storage. The manual operator-confirmed procedure below remains available
for services retaining the original `uvicorn start:app` command.

The active `render.yaml` remains a free service without a disk. The following
steps apply only if you later choose a cloud-hosted paper engine instead of PC
storage. Paid Render compute and disk charges apply.

## If no disk is attached

1. Turn automated entries OFF and preserve the current database and any exports
   before changing the plan or redeploying. An ephemeral database can disappear
   during the upgrade. Keep a verified backup outside the current service; a
   backup stored only on the same ephemeral filesystem is not sufficient.
2. In Render, open the existing **trendforge-core** service, choose an always-on
   paid instance, and attach a **1 GB persistent disk mounted at `/var/data`**.
   Use the existing service rather than starting an unrelated empty deployment.
3. Restore the preserved SQLite database to `/var/data/trendforge.db`. The
   existing copy-only migration utility refuses to overwrite a destination:

   ```bash
   python -m scripts.initialize_local_storage --migrate /path/to/preserved.db /var/data/trendforge.db
   ```

   If no prior database exists, normal application initialization creates its
   schema after the environment is configured. Do not silently replace an
   existing book with an empty database.
4. Set these environment values on that backend service:

   ```text
   DATABASE_PATH=/var/data/trendforge.db
   TRENDFORGE_DATA_DIR=/var/data
   TRENDFORGE_PERSISTENT_MOUNT=/var/data
   TRENDFORGE_PAPER_ALLOW_EPHEMERAL_SIMULATION=false
   TRENDFORGE_STORAGE_RECOVERY_VERIFIED=false
   WEB_CONCURRENCY=1
   ```

5. Deploy, then run these commands in the service shell:

   ```bash
   python -m scripts.initialize_local_storage --verify /var/data/trendforge.db
   python -m scripts.check_paper_storage
   ```

   The diagnostic intentionally reports failure while recovery is unconfirmed.
   Confirm the database path is on the mounted disk, check saved settings and
   known ledger/position/execution-claim records, perform a controlled restart,
   then confirm those records remain and positions restore successfully.
6. Only after that read-back succeeds, set
   `TRENDFORGE_STORAGE_RECOVERY_VERIFIED=true`. Render redeploys for the environment
   change; run the diagnostic again. It must return `verified: true` and exit 0.
7. Review `/paper/readiness` for successful restoration and other risk/kill/session
   requirements, then apply automation ON again. A restart deliberately starts
   automation OFF.

## If a disk already exists

Do not attach a second disk or move a working database unnecessarily. Use its
actual mount path for `TRENDFORGE_PERSISTENT_MOUNT`, and the existing database's
absolute path for `DATABASE_PATH`. `TRENDFORGE_DATA_DIR` must also point to the
persistent disk. Run the read-only diagnostic to identify the missing check.

A recovery flag alone does not make storage persistent. The guard continues to
reject an unmounted disk, a relative database path, a database outside the disk,
or unconfirmed recovery. The storage setup changes never enable real brokerage
orders, weaken risk checks, or automatically release a kill switch.

## Valid Kite credentials but session unavailable

The session warning distinguishes missing settings, a rejected key/token pair,
permission denial, TLS/proxy/connectivity failures, rate limits and unexpected
responses. It no longer assumes every failure is an expired token. Windows
UTF-8 files with a BOM are supported; whitespace surrounding private-file values
is removed and token values are not interpolated.

After updating the repository, run this read-only diagnostic in PowerShell:

```powershell
& "$env:USERPROFILE\TrendForgeSetup\TRENDFORGE_CORE-main\scripts\windows\Start-TrendForgePaper.ps1" -CheckKite
```

This mode prints the report and exits; it does not start a second web server.
Python CLI users can run `python -m scripts.check_kite_session` from the repo root.

For a custom PC data folder, pass `-DataRoot` to the PowerShell launcher (or
`--data-dir` to the Python CLI) with that folder's full path. The
report contains file-existence flags, field-presence booleans, profile and quote
availability, and a fixed error category/HTTP status. It does not print keys,
tokens, broker error bodies or account information. It makes at most one profile
request and one quote request; it cannot submit broker orders.

- `possible_txt_extension: true` with `credential_file_found: false`: Windows
  saved the file as `kite.env.txt`. Rename it to `kite.env` in the private folder.
- Missing field flags: inspect the local file's setting names, save it and restart
  the launcher. An API secret is needed for token generation; the direct profile
  diagnostic uses the supplied API key and access token.
- `token_rejected`: the broker rejected the loaded pair. Check the token belongs
  to the same API app; the report does not assume why it was rejected.
- `permission_denied` after `profile_authenticated: true`: login worked but Kite
  denied the quote request. Check the app's market-data access/permissions.
- `tls_failure`, `proxy_failure`, `connection_failed`, `request_timeout`: investigate
  network/proxy/trusted-certificate configuration. Keep TLS verification enabled.
- `ready` while the UI is unavailable: confirm the Backend URL is the local
  `http://127.0.0.1:10000`, restart the local launcher to reload the edited file,
  and refresh. The broker health probe may cache results for up to 60 seconds.

Share only the diagnostic JSON for troubleshooting, never the credential file.
