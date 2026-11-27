"""Recover space from redundant report exports and losslessly compress archives."""

import gzip
import hashlib
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

from services.research_archive import MAX_BATCH_BYTES, ResearchArchive

LOG = logging.getLogger(__name__)


def digest(path, opener=open):
    with opener(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").digest()


def compact_reports(database):
    root = Path(database).parent
    before = shutil.disk_usage(root).free
    archive = ResearchArchive.for_database(database)
    compressed = removed = 0
    if before < 192 * 1024**2:
        for path in sorted(archive.root.glob("*/batch.json")):
            folder = path.parent
            if (
                folder.is_symlink()
                or path.is_symlink()
                or not re.fullmatch("[0-9a-f]{64}", folder.name)
                or path.stat().st_size > MAX_BATCH_BYTES
            ):
                continue
            try:
                batch = archive.read(path)
                if archive._target(batch["batch_id"]) != folder:
                    continue
                report = batch["report"]
                for filename, key in (
                    ("report.csv", "sha256"),
                    ("report.xlsx", "xlsx_sha256"),
                ):
                    copy = folder / filename
                    if (
                        copy.is_file()
                        and not copy.is_symlink()
                        and digest(copy).hex() == report.get(key)
                    ):
                        copy.unlink()
                        removed += 1
                del batch, report
                with tempfile.NamedTemporaryFile(dir=folder, delete=False) as tmp:
                    temp = Path(tmp.name)
                try:
                    with (
                        path.open("rb") as source,
                        gzip.open(temp, "wb", compresslevel=3) as dest,
                    ):
                        shutil.copyfileobj(source, dest)
                    if temp.stat().st_size < path.stat().st_size and digest(
                        temp, gzip.open
                    ) == digest(path):
                        with temp.open("rb") as stream:
                            os.fsync(stream.fileno())
                        temp.replace(path.with_suffix(".json.gz"))
                        fd = os.open(folder, os.O_RDONLY)
                        try:
                            os.fsync(fd)
                        finally:
                            os.close(fd)
                        path.unlink()
                        compressed += 1
                finally:
                    temp.unlink(missing_ok=True)
            except (ValueError, OSError, KeyError, EOFError) as exc:
                LOG.warning("archive_compaction_skipped type=%s", type(exc).__name__)
    LOG.warning(
        "archive_headroom free_before=%d free_after=%d compressed=%d "
        "redundant_exports=%d",
        before,
        shutil.disk_usage(root).free,
        compressed,
        removed,
    )
