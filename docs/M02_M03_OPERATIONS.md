# M02 persistent runtime and M03 mobile owner login

## Delivery status

M02 supplies an optional paid-deployment template and a strict mounted-book
launcher. It does not attach a disk or change the existing free Render plan.
M03 supplies owner-only Firebase token verification and two protected mobile
read endpoints. It does not create a Firebase/FlutterFlow project or an APK.
Neither batch enables paper entries or real broker orders automatically.

The active `render.yaml` is deliberately unchanged. Review
[`deploy/render-persistent.yaml`](../deploy/render-persistent.yaml) before making
paid account changes. Apply its settings to the EXISTING `trendforge-core`
service; do not accidentally provision a second empty trading instance. Preserve
the existing Admin, webapp and Kite secret settings when changing configuration.
The template is an activation reference, not a one-step migration of existing
data. The strict launcher requires a previously initialized/restored book.

## M02: activation on the existing Render service

1. Stop automatic entries. Export the current paper ledger/P&L and preserve a
   verified SQLite backup OUTSIDE the current service before any plan change or
   redeploy. Use the existing online backup utility; do not copy an open SQLite
   database file while ignoring its WAL. Keep the original book until recovery
   has been tested. If the old ephemeral book is already missing, reconcile it
   from backups/exports rather than silently replacing it with an empty book.
2. In Render, choose always-on paid compute and attach a persistent disk at
   `/var/data`. This is an owner account action with compute/disk charges. No
   account-management connector is available in this workspace to perform it.
3. Before changing database paths/start commands, restore the preserved book to
   `/var/data/trendforge.db`. In the service shell, the existing copy-only command
   is:

   ```bash
   python -m scripts.initialize_local_storage --migrate /path/to/verified-backup.db /var/data/trendforge.db
   python -m scripts.initialize_local_storage --verify /var/data/trendforge.db
   ```

   `/path/to/verified-backup.db` means the actual uploaded backup path. The copy
   refuses to overwrite a destination. A genuinely new installation with NO
   prior book may explicitly initialize a new schema using
   `python -c "from core.database import initialize_database; initialize_database('/var/data/trendforge.db')"`.
   Run that only after confirming there is no existing book to restore. It is
   not a recovery procedure. Existing books needing additive migrations can run
   the same initializer after backup; it does not replace the file.
4. Configure these values and preserve the service's existing feature, session,
   risk and kill-switch settings:

   ```text
   DATABASE_PATH=/var/data/trendforge.db
   TRENDFORGE_DATA_DIR=/var/data
   TRENDFORGE_PERSISTENT_MOUNT=/var/data
   TRENDFORGE_STORAGE_RECOVERY_VERIFIED=false
   TRENDFORGE_PAPER_ALLOW_EPHEMERAL_SIMULATION=false
   TRENDFORGE_ALLOW_EPHEMERAL_ADMIN_WRITES=false
   TRENDFORGE_PRODUCTION_RUNTIME=true
   TRENDFORGE_UNIFIED_UI_ENABLED=true
   WEB_CONCURRENCY=1
   ```

   Change the existing service start command to
   `python -m scripts.render_paper_runtime`. Do not run two server processes
   against this book. Existing paper feature flags remain necessary; this
   launcher does not turn them on or release an existing kill switch.
5. First successful launch records matching random evidence in SQLite settings
   and `/var/data/paper-cloud-storage-proof.json`, then serves the app with
   `persistent_storage_verified: false`, `phase: restart_required`. Preserve
   this companion file with the database in future recovery packages.
6. Use Render's controlled service restart. The next process generates a new
   boot identity, checks the real mount, database integrity/schema and matching
   evidence, then sets recovery verification in THAT PROCESS to true. The saved
   Render recovery variable can remain false. A same-process recheck is not
   restart evidence. An unmounted path, missing book, missing probe or mismatch
   blocks startup without overwriting evidence or creating an empty database.
7. In a running service shell, `python -m scripts.check_paper_storage` reads the
   shell's environment, not the launcher's process-local verification flag. It
   may therefore still show recovery false. Check the running server's protected
   `/paper/readiness` and `/paper/automation`, or the public boolean storage
   fields under `/production/health`, to observe the server's actual state.
   Confirm known ledger records, restoration and worker status after restart.
   Automatic entries remain OFF and require an operator Start.

The real mount check still applies; changing environment flags cannot turn the
free service's ephemeral filesystem into a persistent disk. The wrapper refuses
`/tmp`, root/system pseudo-mounts and a data directory outside the mounted disk.
Keep `WEB_CONCURRENCY=1` and use one service instance for this SQLite paper book.
The launcher also holds an interprocess book lock throughout server lifetime;
a second launcher cannot start a worker against the same data root.

For ongoing backups, use `python -m scripts.initialize_local_storage --backup
/var/data/trendforge.db` with the configured data directory. That command creates
an integrity-checked, uniquely named online backup and reports its SHA-256. A
backup on the same disk is not disaster recovery: retain verified off-service
copies and the companion proof file, and test restoration before relying on
the schedule. Automated off-service backup scheduling is still pending; no
object-storage account or retention policy has been provisioned by M02.

## M03: Firebase and FlutterFlow configuration

The owner supplied Firebase project ID **`trendforge-bd7a0`**, owner Authentication
UID **`project-39777890491`**, and FlutterFlow project ID **`liquid-track-ec26r4`**.
The owner explicitly confirmed that the `project-` value is the account UID,
not a replacement Project ID. These are distinct identifiers;
their connection has not been verified from this workspace. The non-secret
configuration reference is [deploy/mobile.env.example](../deploy/mobile.env.example).
The backend API-key configuration and real-device acceptance are still required.

1. Create/use the owner's Firebase project and connect it to the FlutterFlow
   Android project. Register the intended Android application ID. Enable the
   selected Firebase sign-in provider and create the personal owner account.
   The server requires its exact UID. Do not ship a self-registration UI;
   non-owner accounts are denied even if Firebase issues them valid tokens.
2. Set these backend environment values through Render's settings:

   ```text
   TRENDFORGE_MOBILE_ENABLED=true
   FIREBASE_PROJECT_ID=trendforge-bd7a0
   FIREBASE_WEB_API_KEY=<project API key for Identity Toolkit requests>
   TRENDFORGE_MOBILE_OWNER_UID=project-39777890491
   TRENDFORGE_MOBILE_TOKEN_MAX_AGE_SECONDS=900
   TRENDFORGE_MOBILE_AUTH_EPOCH=0
   ```

   Angle-bracket values above are descriptions, not literal settings. Keep the
   backend Identity Toolkit API key restricted to the required API with
   application restrictions compatible with server requests. Use appropriate
   Android restrictions for client configuration. A Firebase API key identifies
   a project; it is not a substitute for user-token authorization. No service
   account private key or Firebase Admin SDK credential is required by this
   implementation. Existing Admin/Kite credentials stay separate and are never
   sent to the Android app.
3. FlutterFlow signs in using Firebase Authentication. Obtain the current Firebase
   ID token using the Firebase SDK and send it as
   `Authorization: Bearer <ID token>` over HTTPS. Do not pass a Firebase custom
   token, refresh token, webapp key or Core Admin key as the bearer token.
4. `GET /mobile/v1/auth/session` returns authenticated UID, UTC ISO expiry and
   `trading_mutations_available: false`, `broker_orders_allowed: false`.
   `GET /mobile/v1/readiness` returns authentication and storage check labels/
   booleans, without database paths. Both endpoints require the owner token and
   return `Cache-Control: no-store`, including authorization failures.
5. Refresh the SDK ID token before it is 15 minutes old (default server limit),
   even though Firebase's original expiry can be one hour. On 401, refresh once
   for these read-only requests; if rejected again, sign in again. Do not blindly
   replay future trading mutations. Handle 403 as a non-owner denial, and 503
   as disabled/misconfigured/unavailable identity infrastructure. No offline
   authentication fallback is allowed for protected data.

The backend uses Google's `google-auth` Firebase verifier for RS256 signature,
audience and expiry verification, a fixed Google certificate URL, bounded
certificate caching and explicit issuer/time/owner checks. Each accepted request
also makes an Identity Toolkit account lookup to check disabled state and
`validSince` against token `auth_time`. Account lookup is not positively cached;
Google/account-service failure denies access rather than bypassing revocation.

To force reauthentication locally, set `TRENDFORGE_MOBILE_AUTH_EPOCH` to a new
Unix UTC second and redeploy; earlier authentication times are rejected. For a
lost device, also revoke the owner's Firebase sessions/disable the account using
Firebase administration. Signing out on one device clears its SDK/local state;
it is not server-wide revocation. Device logout/secure storage must be wired and
tested in the actual FlutterFlow project. Never log request authorization headers,
ID tokens or the account lookup response.

Core protected endpoints continue requiring Core Admin authorization. A Firebase
token does not unlock them. M03 does not implement a generic forwarding proxy,
mobile trading controls, durable scan/backtest jobs or real broker order writes.
Those remain the later mobile adapter/UI batches in
[FLUTTERFLOW_MOBILE_HANDOFF.md](FLUTTERFLOW_MOBILE_HANDOFF.md).

## Acceptance before operator activation

- Mount/read-back and known paper records survive a controlled Render restart;
  the first boot is blocked, and missing/mismatched evidence fails closed.
- A separate verified off-service backup and a rehearsed restore procedure exist.
- Real Firebase owner login succeeds from the Android device; missing, expired,
  wrong-project, wrong-issuer, invalid-signature, non-owner, disabled and revoked
  identities fail. Verification network failure must also deny access.
- No Admin/Kite secret is present in the app or logs, and protected responses
  are not cached or restored after device sign-out.
- Paper automation remains OFF across server restart. Review storage, positions,
  worker, validation, fresh quotes, risk and market-session status before Start.

Local signed-token/SQLite tests demonstrate implementation behaviour; they do
not prove that a Render disk or the owner's Firebase project is configured.
