# Original cloud URL and PC paper execution

Canonical repository: `TrendForge2001/TRENDFORGE_CORE`, branch `main`.
Original Render service: `trendforge-core`, My Workspace.

<https://trendforge-core.onrender.com/app/>

This is the read-only cloud research workspace. It does not mirror the PC book.
A free service can sleep; allow startup time. Manual access/backend admin keys
are separate from Kite credentials.

## Cloud role

The service-level Render environment is the operational source of these flags:

```text
TRENDFORGE_CLOUD_READ_ONLY=true
TRENDFORGE_PAPER_TRADING_ENABLED=false
TRENDFORGE_PAPER_AUTO_ENTRY_ENABLED=false
TRENDFORGE_LIVE_TRADING_ENABLED=false
TRENDFORGE_UNIFIED_UI_ENABLED=true
TRENDFORGE_KITE_SESSION_PROBE_ON_START=true
```

Update these keys with merge semantics, preserving all secrets and other settings.
The existing Blueprint omits them; avoid adding conflicting values later.
Do not add recovery bypasses or paid disks for this role.

Saved credentials need a fresh deployment. Restarting an older deployment can
reuse its environment. After a main merge, monitor the automatic deploy to
`live` and confirm its commit; avoid duplicate deploys.

Only `KITE_API_KEY`, `KITE_API_SECRET` and `KITE_ACCESS_TOKEN` are accepted from a
credential file. Complete process credentials take precedence. On Render,
missing credentials can come from `/etc/secrets/kite.env`; an explicit
`TRENDFORGE_KITE_ENV_PATH` selects another file. Partial key/token sources must
match before combining. Files cannot enable trading or change admin keys.
If complete process and file values disagree, update the intended process
values: file values do not override them silently.

`kite_session_probe authenticated=true code=ok orders_submitted=0` in startup logs
confirms a read-only profile request. `token_rejected` means that process's
API-key/token pair was rejected. Save a valid session for the same API key securely
and deploy again. Never paste credentials into chat, source, screenshots or issues.
Authentication does not establish fresh quotes or authorize order placement.

## Windows PC

1. Back up the existing paper ledger, proof file and private settings externally.
   Update the existing checkout to merged `main`. Do not combine the two older
   databases or create a new empty book over one.
2. Select one DataRoot on a local fixed drive. Default:
   `%LOCALAPPDATA%\TrendForgeCore`. Canonical ledger:
   `database\trendforge.db`; private credentials: `private\kite.env`.
   Save the current API key, secret and access token there with no `.txt` suffix.
3. In PowerShell from the repository:

   ```powershell
   .\scripts\windows\Start-TrendForgePaper.ps1
   ```

   Preserve an existing custom root by adding `-DataRoot 'D:\TrendForgeData'`
   to every launcher/diagnostic command. Python 3.12 and the Windows Python
   launcher are required. The script installs the pinned Windows dependencies
   in a private environment and does not upload the book.
4. For a new runtime, stop with Ctrl+C after the first storage probe and launch
   again. Restart read-back must pass. Missing/mismatched existing books or
   proof files stop startup: do not delete evidence to bypass this guard.
5. Open <http://127.0.0.1:10000/app/> on the PC. Sign-in keys are in DataRoot's
   `private` directory; the launcher never prints their values. It binds
   loopback and does not expose the PC to the Internet.
6. Run these read-only checks in another PowerShell window:

   ```powershell
   .\scripts\windows\Start-TrendForgePaper.ps1 -CheckKite
   .\scripts\windows\Start-TrendForgePaper.ps1 -CheckPaper
   ```

   Confirm profile/quotes, paper readiness, quote/exit monitors and storage
   recovery. After token changes, stop and relaunch the process.
7. Revalidate against the current registry, review risk/strategy readiness, then
   explicitly start paper automation. It restarts OFF. Reconcile a complete
   session's fills and P&L before unattended use.

The launcher clears inherited cloud read-only state and keeps real orders disabled.
The original Render URL cannot execute trades in the local PC process. Actual
PC installation and Windows fixed-drive recovery require checks on that PC.

Research backtests and permanent reports also use the PC. Completed reports are
saved under `reports/research` and recover missing research indexes on startup.
Before replacing the Render instance, preserve any remaining cloud reports with
`Save-CloudReports.ps1`. See [research recovery](RESEARCH_RECOVERY.md).
