"""A portable package must match Git and exclude books and credential files."""

import hashlib
import json
import subprocess
import zipfile

import pytest

from scripts.build_pc_paper_package import build_package


def test_source_pinned_package_excludes_runtime_books_and_credentials(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    for name in (
        "start.py",
        "streamlit_app.py",
        "requirements-pc.lock",
        "scripts/windows/Start-TrendForgePaper.ps1",
        "config/pc_paper_policy.json",
        "database/book.db",
        "private/admin-key.txt",
        ".env",
    ):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic package fixture")

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=repo)

    git("init")
    git("add", ".")
    git(
        "-c",
        "user.name=Package Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "Synthetic package source",
    )
    receipt = build_package(repo, tmp_path / "archives")
    assert receipt["source_commit"] == git("rev-parse", "HEAD").decode().strip()
    with zipfile.ZipFile(receipt["archive"]) as archive:
        files = {
            name.split("/", 1)[1]: archive.read(name) for name in archive.namelist()
        }
        assert not {"database/book.db", "private/admin-key.txt", ".env"} & files.keys()
        manifest = json.loads(files["PACKAGE_MANIFEST.json"])
        assert manifest["source_commit"] == receipt["source_commit"]
        for path, checksum in manifest["files"].items():
            assert hashlib.sha256(files[path]).hexdigest() == checksum
        assert b"Start-TrendForgePaper.ps1" in files["START_PAPER.cmd"]
        assert b"-CheckPaper" in files["CHECK_PAPER.cmd"]
    (repo / "start.py").write_text("unreviewed edit")
    with pytest.raises(ValueError, match="Commit"):
        build_package(repo, tmp_path / "second")
