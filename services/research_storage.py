"""Report durability is independent of the live/paper execution role."""

from pathlib import Path

from core.deployment_role import cloud_read_only
from core.storage_config import storage_health
from services.research_archive import ResearchArchive


def report_archive(database_path):
    if database_path == ":memory:":
        return None
    health = storage_health()
    mounted = (
        health["persistent_mount_is_mountpoint"]
        and health["database_within_persistent_mount"]
        and health["database_path"] == str(Path(database_path).resolve())
    )
    if cloud_read_only() and not mounted:
        return None
    return ResearchArchive.for_database(database_path)


def complete_batch(repository, archive, batch_id, report):
    if archive is not None:
        from database.repositories.research_batches import utc_now

        batch = repository.get(batch_id)
        if batch["status"] != "running":
            return False
        batch.update(
            status="completed",
            phase="completed",
            report=report,
            finished_at=utc_now(),
            updated_at=utc_now(),
        )
        try:
            archive.save(batch)
        except (OSError, ValueError):
            repository.fail(batch_id, "report_archive_failed")
            return False
    return repository.finish(batch_id, report)
