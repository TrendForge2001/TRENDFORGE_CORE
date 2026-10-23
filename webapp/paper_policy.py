"""Presentation and fail-closed controls for the backend paper-entry policy."""

from __future__ import annotations

from typing import Any


def _policy(readiness: Any) -> dict[str, Any] | None:
    if not isinstance(readiness, dict):
        return None
    policy = readiness.get("entry_storage_policy")
    if not isinstance(policy, dict):
        return None
    if any(
        type(policy.get(key)) is not bool
        for key in (
            "entry_allowed",
            "production",
            "verified_persistent",
            "ephemeral_simulation",
        )
    ):
        return None
    mode = policy.get("mode")
    if not isinstance(mode, str) or mode not in {
        "durable",
        "ephemeral_simulation",
        "local_simulation",
        "blocked",
    }:
        return None
    if mode == "durable" and not policy["verified_persistent"]:
        return None
    if mode == "ephemeral_simulation" and not policy["ephemeral_simulation"]:
        return None
    if mode == "local_simulation" and policy["production"]:
        return None
    return policy


def paper_entry_allowed(readiness: Any) -> bool:
    """Missing readiness or runtime/kill/storage blocks disable entry widgets."""
    policy = _policy(readiness)
    kill_storage = (
        readiness.get("kill_switch_storage") if isinstance(readiness, dict) else None
    )
    if isinstance(kill_storage, dict) and kill_storage.get("status") == "unavailable":
        return False
    return bool(
        policy is not None
        and policy["mode"] != "blocked"
        and policy["entry_allowed"]
        and readiness.get("can_open_new_positions") is True
    )


def paper_execution_requested(requested: Any, readiness: Any) -> bool:
    """Ignore stale enabled widget values after the backend policy changes."""
    return requested is True and paper_entry_allowed(readiness)


def paper_policy_notice(readiness: Any) -> tuple[str, str]:
    """Use fixed product text rather than displaying arbitrary backend messages."""
    policy = _policy(readiness)
    controls = "Existing positions can still be monitored and exited; kill controls remain available."
    if policy is None:
        return (
            "warning",
            "Paper-entry readiness is unavailable. New entries are disabled. "
            + controls,
        )
    if policy["mode"] == "blocked" or not policy["entry_allowed"]:
        return (
            "warning",
            "New paper entries are blocked until storage is verified. " + controls,
        )
    if policy["mode"] == "ephemeral_simulation":
        return "warning", (
            "Ephemeral simulation: positions, history and risk state may be lost when the service restarts. "
            "Normal risk and kill-switch gates still apply."
        )
    if policy["mode"] == "local_simulation":
        return (
            "info",
            "Local paper simulation: recovery across deployments has not been verified. Normal risk and kill-switch gates still apply.",
        )
    return (
        "info",
        "Paper entries use verified storage. Normal risk and kill-switch gates still apply.",
    )


def render_paper_entry_policy(readiness: Any) -> None:
    import streamlit as st

    level, message = paper_policy_notice(readiness)
    getattr(st, level)(message)
    kill_storage = (
        readiness.get("kill_switch_storage") if isinstance(readiness, dict) else None
    )
    if isinstance(kill_storage, dict) and kill_storage.get("status") == "unavailable":
        st.warning(
            "Saved kill-switch state is unavailable. New paper entries are disabled; "
            "monitoring, exits and emergency kill controls remain available."
        )


__all__ = [
    "paper_entry_allowed",
    "paper_execution_requested",
    "paper_policy_notice",
    "render_paper_entry_policy",
]


def render_paper_storage_setup(report: Any) -> None:
    """Show actionable storage setup within the existing paper tab."""
    import streamlit as st

    if not isinstance(report, dict) or report.get("verified") is True:
        return
    with st.expander("Resolve persistent storage requirement", expanded=True):
        st.write("Use PC storage by running both this webapp and the paper engine on your Windows PC. Render cannot mount your PC drive.")
        st.code(
            "powershell -NoProfile -ExecutionPolicy Bypass -File "
            ".\\scripts\\windows\\Start-TrendForgePaper.ps1",
            language="powershell",
        )
        st.write("Run the launcher twice: first record the storage check, then stop with Ctrl+C and restart to verify recovery. Open http://127.0.0.1:10000/app/ on that PC. Keep the PC awake and the launcher running during market hours.")
        st.write(
            "For a cloud backend instead, paper entries require a real persistent disk and a confirmed restart recovery. "
            "On Render, attach a disk to an always-on service; a free service cannot "
            "provide this storage. Paid compute and disk charges apply."
        )
        checks = report.get("checks")
        if isinstance(checks, list):
            for item in checks:
                if isinstance(item, dict):
                    st.write(f"{'✓' if item.get('passed') is True else '○'} {item.get('label', 'Storage check')}")
        st.write("For a disk mounted at /var/data, configure these server environment settings:")
        st.code(
            "DATABASE_PATH=/var/data/trendforge.db\n"
            "TRENDFORGE_DATA_DIR=/var/data\n"
            "TRENDFORGE_PERSISTENT_MOUNT=/var/data\n"
            "TRENDFORGE_PAPER_ALLOW_EPHEMERAL_SIMULATION=false\n"
            "WEB_CONCURRENCY=1",
            language="text",
        )
        st.write(
            "Back up and preserve the existing database before changing the service or "
            "database location. After a controlled restart, confirm the saved ledger, "
            "positions and settings recover from the disk. Only then set "
            "TRENDFORGE_STORAGE_RECOVERY_VERIFIED=true."
        )
        st.caption(
            "Run python -m scripts.check_paper_storage in the Render service shell "
            "to identify remaining checks. Changing an environment flag alone "
            "does not attach a disk."
        )
