# R70.2 — Windows local engine runtime (safe first deployment)

**Scope:** Local-only observer + database health, Windows Task Scheduler tasks,
explicit Kite authentication check, bounded on-demand 25-symbol NIFTY 500 scan.
**Not included:** unattended scanning, automatic paper fills/SL/targets, broker
orders, cloud sync. Render and Streamlit/FastAPI source remain unchanged.

## Prerequisites
- Windows user can sign in; laptop powered on and plugged in during market hours.
- Windows timezone must read \`India Standard Time\`.
- Existing verified 23-table PC database at \`C:\TrendForgeData\database\trendforge.db\`.
- Existing repository Python \`.venv\Scripts\python.exe\`; preserve original backup.
- Do not put Kite API credentials inside startup scripts, git, or command logs.
- Verify NSE holiday and special-session calendar before any future automated scanning.

## A. Verify and save user-level Windows environment (explicit opt-in)

From \`C:\Users\Lenovo\Desktop\TrendForge\` in PowerShell:

\`\`\`powershell
git fetch origin
git switch feature/r70-2-windows-engine-runtime
git pull --ff-only origin feature/r70-2-windows-engine-runtime

powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\Set-TrendForgeEnvironment.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\Set-TrendForgeEnvironment.ps1" -Apply

[Environment]::GetEnvironmentVariable('DATABASE_PATH','User')
[Environment]::GetEnvironmentVariable('TRENDFORGE_DATA_DIR','User')
\`\`\`

The script first validates the database schema; it does not set variables without
\`-Apply\`. It refuses to overwrite a conflicting user variable. It does **not**
change any Render environment variables.

## B. Run tests and manual preflight
\`\`\`powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_r70_local_storage.py tests/test_r70_local_engine_runtime.py
.\.venv\Scripts\python.exe -m scripts.local_engine_runtime preflight --root C:\TrendForgeData --db C:\TrendForgeData\database\trendforge.db
\`\`\`

Open a fresh PowerShell window before using commands that rely on saved user
environment variables. Child processes launched by already-running VS Code or
terminals may retain old settings until restarted.

To **explicitly verify Kite 2FA/session**, after logging in via your normal
Kite flow and setting the session token securely for the current shell:
\`\`\`powershell
.\.venv\Scripts\python.exe -m scripts.local_engine_runtime kite-check
\`\`\`
No credential refresh or bypass is automated. The command checks \`profile()\`
and only prints success or a generic error class.

To manually run **at most 25 NIFTY 500 symbols**, after preflight and Kite auth:
\`\`\`powershell
.\.venv\Scripts\python.exe -m scripts.local_engine_runtime scan-once --max-symbols 25
\`\`\`
This can fetch market data; it never submits orders. Scan metrics and provider
reliability must be separately verified on the PC before expanding scope.

## C. Optional Windows Task Scheduler (observer only)

\`\`\`powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\Install-TrendForgeTasks.ps1" -Action Status
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\Install-TrendForgeTasks.ps1" -Action Install
\`\`\`

This creates two current-user, signed-in-session tasks for weekdays, **08:45**
and **16:00 Windows local time**. The install refuses a timezone other than
\`India Standard Time\`. It **does not power on a switched-off laptop** and
cannot guarantee execution during sleep, outages or holidays. Observer mode
never starts FastAPI, scans automatically, monitors paper positions or trades.

Status file: \`C:\TrendForgeData\logs\local_engine_status.json\`.
Graceful stop: \`Stop-TrendForgeLocal.ps1\`. To remove only these two tasks:
\`\`\`powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\Install-TrendForgeTasks.ps1" -Action Remove
\`\`\`

## Acceptance gates before moving to R70.3
- Windows-specific tests and full GitHub CI green
- PC environment saved and verified in a **new** terminal
- Observer starts, writes status, and shuts down after 16:00 IST
- Kite check explicitly authenticated before manual scan
- Persistent DB backup verified and no automated orders enabled
- No cloud synchronization until durable cloud receiving storage is provisioned

This change does not migrate Render SQLite, fix its ephemeral storage, or create
a safe unattended paper execution service.
