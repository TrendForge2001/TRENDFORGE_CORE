"""Bound the expanded size of uploaded Office archives before parsing."""

from io import BytesIO
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException


def check_workbook_size(payload, suffix):
    if suffix not in {".xlsx", ".xlsm"}:
        return
    try:
        with ZipFile(BytesIO(payload)) as archive:
            if sum(entry.file_size for entry in archive.infolist()) > 40 * 1024**2:
                raise HTTPException(413, "Expanded workbook exceeds 40 MiB")
    except BadZipFile:
        raise HTTPException(422, "Invalid workbook archive") from None
