"""PC disk recovery, inherited execution flags and Windows installation contract."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from scripts import pc_paper_runtime as pc


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    # Environment changes must not leak into another application's tests.
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.setattr(pc, "fixed_drive_mount", lambda root: root.anchor)
    return tmp_path


def test_restart_verifies_same_database_and_preserves_rows(isolated):
    root = isolated
    database, verified = pc.prepare_storage(root, session_id="first")
    assert verified is False
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "INSERT INTO settings(key, value) VALUES ('kept', 'paper-risk-setting')"
        )
        connection.commit()
    assert pc.prepare_storage(root, session_id="first")[1] is False
    assert pc.prepare_storage(root, session_id="second")[1] is True
    with closing(sqlite3.connect(database)) as connection:
        assert (
            connection.execute(
                "SELECT value FROM settings WHERE key='kept'"
            ).fetchone()[0]
            == "paper-risk-setting"
        )


def test_lost_database_is_not_replaced_by_an_empty_book(isolated):
    database, _ = pc.prepare_storage(isolated, session_id="first")
    database.unlink()
    with pytest.raises(ValueError, match="missing"):
        pc.prepare_storage(isolated, session_id="second")
    assert not database.exists()


@pytest.mark.parametrize("damage", ["missing_file", "changed_file", "missing_row"])
def test_mismatched_restart_evidence_blocks_instead_of_resetting_it(isolated, damage):
    database, _ = pc.prepare_storage(isolated, session_id="first")
    proof = isolated / "paper-storage-proof.json"
    if damage == "missing_file":
        proof.unlink()
    elif damage == "changed_file":
        proof.write_text("{}", encoding="utf-8")
    else:
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("DELETE FROM settings WHERE key=?", (pc.PROBE_KEY,))
            connection.commit()
    with pytest.raises(ValueError, match="restart proof|lost its restart probe"):
        pc.prepare_storage(isolated, session_id="second")


def test_pc_settings_override_inherited_cloud_and_real_order_flags(isolated):
    os.environ.update(
        {
            "TRENDFORGE_LIVE_TRADING_ENABLED": "true",
            "TRENDFORGE_STORAGE_RECOVERY_VERIFIED": "true",
            "TRENDFORGE_PAPER_ALLOW_EPHEMERAL_SIMULATION": "true",
        }
    )
    assert pc.configure(isolated, port=10000, session_id="first") is False
    assert os.environ["TRENDFORGE_LIVE_TRADING_ENABLED"] == "false"
    assert os.environ["TRENDFORGE_STORAGE_RECOVERY_VERIFIED"] == "false"
    assert os.environ["TRENDFORGE_PAPER_ALLOW_EPHEMERAL_SIMULATION"] == "false"
    assert os.environ["DATABASE_PATH"] == str(isolated / "database" / "trendforge.db")
    assert os.environ["TRENDFORGE_PRODUCTION_RUNTIME"] == "true"
    assert os.environ["TRENDFORGE_PAPER_MONITOR_ENABLED"] == "true"
    assert os.environ["TRENDFORGE_STRATEGY_PAPER_MONITOR_ENABLED"] == "true"
    key = os.environ["TRENDFORGE_ADMIN_API_KEY"]
    assert len(key) >= 32
    assert pc.configure(isolated, port=10000, session_id="second") is True
    assert os.environ["TRENDFORGE_ADMIN_API_KEY"] == key


def test_invalid_private_key_is_never_silently_replaced(isolated):
    private = isolated / "private"
    private.mkdir()
    path = private / "admin-key.txt"
    path.write_text("bad", encoding="utf-8")
    with pytest.raises(ValueError, match="administrative key"):
        pc.admin_key(isolated)
    assert path.read_text() == "bad"


def test_launcher_binds_loopback_and_does_not_expose_the_pc(monkeypatch, isolated):
    import uvicorn

    calls = []
    monkeypatch.setattr(
        uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs))
    )
    assert pc.main(["--data-dir", str(isolated), "--port", "10000"]) == 0
    assert calls[0][1] == {"host": "127.0.0.1", "port": 10000, "workers": 1}


def test_pc_lock_does_not_allow_two_paper_engines(isolated):
    from scripts.local_engine_runtime import exclusive_lock

    with exclusive_lock(isolated / "paper-webapp.lock"):
        assert pc.main(["--data-dir", str(isolated)]) == 1


def test_windows_requirements_keep_production_versions_and_exclude_linux_uvloop():
    root = Path(__file__).resolve().parents[1]
    production = {
        line
        for line in (root / "requirements-production.lock").read_text().splitlines()
        if line and not line.startswith("#")
    }
    windows = {
        line.split(";")[0].strip()
        for line in (root / "requirements-pc.lock").read_text().splitlines()
        if line and not line.startswith("#")
    }
    assert production == windows
    assert (
        'uvloop==0.23.0; sys_platform != "win32"'
        in (root / "requirements-pc.lock").read_text()
    )


@pytest.mark.skipif(os.name != "nt", reason="Requires a real Windows fixed drive")
def test_real_windows_drive_satisfies_durable_policy_after_restart(
    tmp_path, monkeypatch
):
    from core.paper_storage_policy import paper_entry_storage_policy

    monkeypatch.setattr(os, "environ", dict(os.environ))
    root = tmp_path.resolve()
    assert pc.configure(root, port=10000, session_id="first") is False
    assert paper_entry_storage_policy()["entry_allowed"] is False
    assert pc.configure(root, port=10000, session_id="second") is True
    policy = paper_entry_storage_policy()
    assert policy["mode"] == "durable" and policy["entry_allowed"] is True


def test_windows_dependency_health_does_not_require_a_linux_only_loop(
    tmp_path, monkeypatch
):
    from api import production_runtime

    lock = tmp_path / "runtime.lock"
    lock.write_text("uvloop==0.23.0\nrequests==2.34.2\n")
    monkeypatch.setattr(production_runtime.platform, "system", lambda: "Windows")

    def version(name):
        assert name != "uvloop"
        return "2.34.2"

    monkeypatch.setattr(production_runtime.metadata, "version", version)
    assert (
        production_runtime.dependency_lock_health(lock)["status"] == "runtime_verified"
    )


@pytest.mark.skipif(
    os.name != "nt", reason="Requires the Windows dependency installation"
)
def test_real_windows_dependency_graph_matches_production_pins():
    from api.production_runtime import dependency_lock_health

    assert dependency_lock_health()["status"] == "runtime_verified"


def test_pc_login_keys_are_separate_and_only_kite_credentials_are_loaded(isolated):
    private = isolated / "private"
    private.mkdir()
    (private / "kite.env").write_text(
        "KITE_API_KEY=\nTRENDFORGE_LIVE_TRADING_ENABLED=true\n", encoding="utf-8"
    )
    pc.configure(isolated, port=10000, session_id="first")
    assert (
        os.environ["TRENDFORGE_WEBAPP_ACCESS_KEY"]
        != os.environ["TRENDFORGE_ADMIN_API_KEY"]
    )
    assert os.environ["TRENDFORGE_LIVE_TRADING_ENABLED"] == "false"
    assert (private / "webapp-key.txt").is_file()
    assert (private / "admin-key.txt").is_file()
