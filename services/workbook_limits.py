"""Bound XLSX and XLSM imports before pandas expands the archive."""
from zipfile import BadZipFile, ZipFile


def validate_workbook_size(path):
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 2048 or sum(item.file_size for item in entries) > 32 * 1024 * 1024:
                raise ValueError("Workbook exceeds the expanded size or entry limit.")
    except BadZipFile as exc:
        raise ValueError("Invalid workbook archive.") from exc
