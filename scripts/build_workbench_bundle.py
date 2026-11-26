"""Package the Next.js static export for the existing Python Render service."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from core.workbench_assets import workbench_entries

root = Path(__file__).resolve().parents[1] / "frontend"
export = root / "out"


def main():
    if not (export / "scanner" / "index.html").is_file():
        raise SystemExit("Build the frontend with npm run build before packaging it.")
    candidate = root / "workbench.tmp.zip"
    try:
        with ZipFile(
            candidate, "w", compression=ZIP_DEFLATED, compresslevel=9
        ) as bundle:
            for path in sorted(export.rglob("*")):
                if path.is_file():
                    entry = ZipInfo(path.relative_to(export).as_posix())
                    bundle.writestr(
                        entry,
                        path.read_bytes(),
                        compress_type=ZIP_DEFLATED,
                        compresslevel=9,
                    )
        with ZipFile(candidate) as bundle:
            workbench_entries(bundle, candidate.stat().st_size)
        candidate.replace(root / "workbench.zip")
    finally:
        candidate.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
