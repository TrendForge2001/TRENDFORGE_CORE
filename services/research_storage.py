"""Report durability is independent of the live/paper execution role."""

from pathlib import Path

from core.deployment_role import on_render
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
    if on_render() and not mounted:
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
    saved = repository.finish(batch_id, report)
    if saved:
        try:
            from services.scanner_workflow import record_completed_scan

            record_completed_scan(repository, archive, batch_id)
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning(
                "scanner_handoff_pending error_type=%s", type(exc).__name__
            )
    return saved
