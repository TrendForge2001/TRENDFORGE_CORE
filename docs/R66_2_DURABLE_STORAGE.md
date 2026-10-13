# R66.2 Durable Audit Storage and Redeploy Survival

R66.2 makes TrendForge capable of proving that its SQLite database survived a
production restart or redeploy. It does not silently enable paid Render
resources.

## Current production boundary

The active `render.yaml` remains on Render Free. Free filesystem writes are
ephemeral. A persistent disk must be attached to a paid web-service instance.

TrendForge already routes all SQLite repositories through `DATABASE_PATH`.
Therefore moving the database to a mounted path moves fundamentals, evidence,
scan-run audits, and the rest of the SQLite schema together.

## Required Render configuration

Upgrade the existing `trendforge-core` web service to the smallest paid web
service plan, attach a 1 GB persistent disk, and use:

```text
Mount path:    /var/data
DATABASE_PATH=/var/data/trendforge.db
```

Do not mount over `/etc/secrets`. Keep the existing fundamentals bootstrap
secret file and pinned SHA configured. On the first boot of an empty persistent
disk, database migrations run first and the fundamentals bootstrap can safely
restore the verified fundamentals dataset.

The repository file `deploy/render-persistent-disk.yaml` is reference-only
and intentionally does not change the active free-plan manifest.

## Persistence evidence

R66.2 adds `storage_runtime_state` with a stable `storage_id` and
`boot_count`.

On every production application boot:

1. migrations ensure the storage-state table exists;
2. TrendForge preserves the existing `storage_id`, or creates one for a new
   database;
3. `boot_count` increments;
4. the current Render git commit and service ID are recorded.

`GET /production/health` returns both:

- `storage.verified_persistent`: whether the database path is on a mounted
  persistent filesystem;
- `storage_boot`: stable database identity and boot evidence.

## Redeploy-survival gate

After persistent storage is enabled:

1. capture `storage_boot.storage_id` and `storage_boot.boot_count`;
2. run a named 25-security scan and confirm its audit record exists;
3. redeploy the same service;
4. call `/production/health` again;
5. confirm the same `storage_id`, a higher `boot_count`, and
   `storage.verified_persistent=true`;
6. fetch the pre-redeploy audit run by its run ID and confirm it still exists.

This proves database continuity using both a stable storage identity and a
real persisted application record.

## Transition note

The current Free-plan SQLite file is ephemeral and is not automatically copied
onto a newly attached persistent disk. The verified fundamentals bootstrap
restores fundamentals into an empty persistent database. Existing ephemeral
scan-audit test records should be treated as pre-persistence validation data;
create the durability proof record after the persistent disk is live.
