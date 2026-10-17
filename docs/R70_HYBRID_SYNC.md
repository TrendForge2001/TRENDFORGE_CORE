# R70.3 — Hybrid synchronization foundation (disabled by default)

## Deployment status and safety
This branch is **not deployed**. R70.2 PC observer continues without network
activity. This batch adds a separate opt-in local SQLite outbox, a signed-in
HTTPS receiver using a separate shared key, and a receiver persistence gate.
It does **not** make Render Free's ephemeral database durable.

The live receiver is **blocked on Render Free** because it requires an actual
verified persistent mount. Its readiness endpoint may say \`disabled\` or
\`blocked\`. Do not use fake flags to bypass the mount verification.

**Never synchronize Kite keys, tokens, account numbers, passwords or secrets.**
Only approved small event payloads may be queued. This event store does not
automatically synchronize the main TrendForge SQLite database.

## On your Windows PC
After switching to the feature branch, with the verified R70.2 environment:

\`\`\`powershell
cd C:\Users\Lenovo\Desktop\TrendForge
git fetch origin
git switch feature/r70-3-hybrid-sync-foundation
git pull --ff-only origin feature/r70-3-hybrid-sync-foundation

.\.venv\Scripts\python.exe -m pytest -q tests/test_r70_hybrid_sync.py
.\.venv\Scripts\python.exe -m scripts.hybrid_sync_cli status
.\.venv\Scripts\python.exe -m scripts.hybrid_sync_cli queue-heartbeat
.\.venv\Scripts\python.exe -m scripts.hybrid_sync_cli status
\`\`\`

These commands **create and test only the local journal** in
\`C:\TrendForgeData\sync\outbox.db\`. They do not send HTTP requests.
Do not put tokens in a queued payload.

## Future enablement (NOT during this batch)

A durable cloud volume must be provisioned and mounted as a dedicated path
(e.g. \`/var/data\`) on the Render service. Configure these Render secrets and
settings through the platform dashboard only after verifying the mount:

- \`TRENDFORGE_SYNC_RECEIVER_ENABLED=true\`
- \`TRENDFORGE_SYNC_STORAGE_ROOT=/var/data\` (must itself be a verified mount)
- \`TRENDFORGE_SYNC_SHARED_KEY\` (random secret with 32+ characters)

Then set the matching key on the PC, enable the sender explicitly with
\`TRENDFORGE_SYNC_SENDER_ENABLED=true\`, and set
\`TRENDFORGE_SYNC_URL=https://trendforge-core.onrender.com/sync/events\`.
Only manually run \`python -m scripts.hybrid_sync_cli send-once\`
after verifying cloud readiness and endpoints. Automatic transmission is
deliberately not implemented.

The cloud receiver checks authorization, enforces event limits, rejects
duplicate IDs with altered bodies, and writes to a separate SQLite inbox on
the verified persistent mount with synchronous commits. A successful HTTP
response includes \`durable: true\`; the PC acknowledges only a matching
event_id and a confirmed durable acknowledgment. Otherwise it retains the
event for retry. Server credential rotation, cloud audit trails, token replay
hardening, external backups, monitoring, rate limiting and privacy review are
still required before accepting sensitive paper-trading records.

If cloud costs must remain at zero, retain local-only journaling for now and
do **not** enable cloud receipt of trading-critical data. R70.3.2 may add
noncritical, explicitly ephemeral dashboard heartbeat as a separate contract.

Existing Render deployment, main PC database, Streamlit UI and trading controls
are unchanged by this feature branch until explicitly merged and deployed.
