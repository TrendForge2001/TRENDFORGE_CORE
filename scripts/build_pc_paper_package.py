"""Build a source-pinned Windows paper package without reading runtime data."""

import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

EXCLUDED_DIRECTORIES = {".git", "private", "logs", "backups", "reports", "__pycache__"}


def source_path_allowed(name):
    path = PurePosixPath(name)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and not set(path.parts) & EXCLUDED_DIRECTORIES
        and not path.name.startswith(".env")
        and ".env" not in path.name
        and not path.name.endswith(
            (".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3", ".pyc")
        )
        and "storage-proof" not in path.name
        and path.name not in {"admin-key.txt", "webapp-key.txt"}
    )


def build_package(repo: Path, output: Path):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=repo)

    if git("status", "--porcelain", "--untracked-files=all").strip():
        raise ValueError("Commit the reviewed source before packaging")
    commit = git("rev-parse", "HEAD").decode().strip()
    prefix = "Trendforge-PC-Paper-" + commit[:12]
    paths = git("ls-tree", "-r", "--name-only", "HEAD").decode().splitlines()
    files = {
        name: git("show", f"HEAD:{name}") for name in paths if source_path_allowed(name)
    }
    required = {
        "start.py",
        "streamlit_app.py",
        "requirements-pc.lock",
        "scripts/windows/Start-TrendForgePaper.ps1",
        "config/pc_paper_policy.json",
    }
    if not required.issubset(files):
        raise ValueError("The PC package is missing a required runtime file")
    for name, arguments in {
        "START_PAPER.cmd": "",
        "CHECK_PAPER.cmd": "-CheckPaper",
        "CHECK_KITE.cmd": "-CheckKite",
    }.items():
        command = (
            "@echo off\r\n"
            "powershell.exe -NoProfile -ExecutionPolicy Bypass -File "
            '"%~dp0scripts\\windows\\Start-TrendForgePaper.ps1" '
            + arguments
            + " %*\r\n"
            "if errorlevel 1 pause\r\n"
        )
        files[name] = command.encode("utf-8")
    files["OPEN_PAPER.cmd"] = (
        b'@echo off\r\nstart "" "http://127.0.0.1:10000/app/paper_session"\r\n'
    )
    files["READ_ME_FIRST.txt"] = f"""Trendforge PC paper package
Source commit: {commit}

1. Extract this entire folder. Python 3.12 for Windows and its py launcher
   are required. First startup downloads the pinned dependencies.
2. Back up your existing DataRoot, ledger, private keys and proof files.
   Default DataRoot: %LOCALAPPDATA%\\TrendForgeCore.
   Preserve a custom DataRoot by passing -DataRoot "D:\\YourExistingFolder"
   to START_PAPER.cmd and both CHECK scripts. Never replace an existing book
   with an empty database or delete proof files to bypass recovery checks.
3. Save current Kite credentials locally in DataRoot\\private\\kite.env.
   Fields: KITE_API_KEY, KITE_API_SECRET, KITE_ACCESS_TOKEN.
   No credentials are included in this archive; never put them in chat/Git.
4. Run START_PAPER.cmd. For the first installation, stop with Ctrl+C after
   the initial storage probe, then run it again with the same DataRoot.
5. Run OPEN_PAPER.cmd after the backend starts. Local sign-in keys are in
   DataRoot\\private\\webapp-key.txt and admin-key.txt. Never share the keys.
6. Run CHECK_KITE.cmd and CHECK_PAPER.cmd. Resolve reported blockers, run
   saved-strategy validation, then explicitly press Start in the PC page.

Paper policy: INR 100,000 capital; no fixed reserve; three concurrent
positions; six new entries/day across strategies; 3% marked-loss entry guard.
See config\\pc_paper_policy.json and docs\\PC_PAPER_DEPLOYMENT.md for sizing
and carried-position limitations. Paper P&L excludes fees/slippage.

Automation starts OFF after every backend restart. Broker orders stay disabled.
Stop automation blocks new entries; existing positions still need the backend
running for monitoring and exits. Keep the PC awake with reliable connectivity.
Closing the browser is fine; sleeping/shutting down the PC stops execution.
The Render website stays read-only and does not display this PC's local book.

This archive was prepared and tested in isolated environments. No installation,
Kite session, Windows drive or live-paper session on your laptop is certified.
""".encode()
    manifest = {
        "source_commit": commit,
        "paper_only": True,
        "laptop_files_accessed": False,
        "files": {
            name: hashlib.sha256(data).hexdigest() for name, data in files.items()
        },
    }
    files["PACKAGE_MANIFEST.json"] = json.dumps(manifest, indent=2).encode()
    output.mkdir(parents=True, exist_ok=True)
    destination = output / (prefix + ".zip")
    staging = destination.with_suffix(".zip.partial")
    with zipfile.ZipFile(staging, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(prefix + "/" + name, data)
    with zipfile.ZipFile(staging) as archive:
        if archive.testzip() is not None:
            raise ValueError("Package archive integrity failed")
    staging.replace(destination)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(".zip.sha256").write_text(
        digest + "  " + destination.name + "\n"
    )
    return {
        "archive": str(destination),
        "sha256": digest,
        "source_commit": commit,
        "files": len(files),
        "paper_only": True,
        "laptop_files_accessed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build_package(Path(__file__).resolve().parents[1], args.output_dir),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
