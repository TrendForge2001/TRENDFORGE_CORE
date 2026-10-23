"""Read-only explanation of the durable paper storage admission checks."""

from core.storage_config import storage_health

CHECKS = (
    ("database_path_configured", "Database location configured"),
    ("database_path_is_absolute", "Database uses an absolute path"),
    ("persistent_mount_configured", "Persistent disk mount configured"),
    ("persistent_mount_is_mountpoint", "Persistent disk is actually mounted"),
    ("database_within_persistent_mount", "Database is located on the disk"),
    ("restart_recovery_confirmed", "Database recovery after restart confirmed"),
)


def paper_storage_setup() -> dict:
    """Explain requirements without changing paths, flags or stored data."""
    try:
        report = storage_health()
    except Exception:
        return {"status": "unavailable", "checks": [], "verified": False}
    verified = report.get("verified_persistent") is True
    return {
        "status": "ready" if verified else "setup_required",
        "verified": verified,
        "database_path": report.get("database_path"),
        "persistent_mount": report.get("persistent_mount"),
        "checks": [
            {"label": label, "passed": report.get(key) is True} for key, label in CHECKS
        ],
    }
