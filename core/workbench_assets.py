"""Structural validation for the checked-in Next.js workbench export."""

import re
import stat
from pathlib import PurePosixPath
from zipfile import ZipFile, ZipInfo

WORKBENCH_BUNDLE_PATH = "frontend/workbench.zip"
_MAX_EXPANDED_BYTES = 20_000_000
_MAX_ENTRIES = 256
_TEXT_EXTENSIONS = frozenset({".css", ".html", ".js", ".txt"})
_FONT_PATH = re.compile(
    r"_next/static/media/(?:inter|jetbrains-mono)-"
    r"[a-z0-9-]+\.[a-z0-9_-]+\.woff2"
)


def workbench_entries(archive: ZipFile, size: int) -> list[ZipInfo]:
    """Bound expansion and admit only regular files in the static export."""
    entries = archive.infolist()
    if (
        not 1 <= len(entries) <= _MAX_ENTRIES
        or size > _MAX_EXPANDED_BYTES
        or sum(entry.file_size for entry in entries) > _MAX_EXPANDED_BYTES
    ):
        raise ValueError("Workbench bundle exceeds its static export limits")
    seen = set()
    offset, central_size = 0, 0
    for entry in entries:
        name = entry.filename
        path = PurePosixPath(name)
        if (
            name in seen
            or name != entry.orig_filename
            or not name.isascii()
            or any(ord(char) < 32 for char in name)
            or "\\" in name
            or ":" in name
            or entry.extra
            or entry.comment
            or entry.header_offset != offset
            or path.is_absolute()
            or ".." in path.parts
            or path.as_posix() != name
            or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG)
            or entry.flag_bits
            or (path.suffix not in _TEXT_EXTENSIONS and not _FONT_PATH.fullmatch(name))
        ):
            raise ValueError("Workbench bundle contains an unsupported entry")
        seen.add(name)
        # The packager writes standard local and central headers with ASCII
        # names, no extra fields, and no trailing descriptors.
        offset += 30 + len(name) + entry.compress_size
        central_size += 46 + len(name)
    if archive.comment or size != offset + central_size + 22:
        raise ValueError("Workbench bundle includes data outside the static export")
    return entries
