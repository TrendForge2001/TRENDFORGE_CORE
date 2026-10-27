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
        st.write(
            "To use the hosted webapp, paper entries require a real persistent disk and confirmed restart recovery. "
            "On Render, attach a disk to an always-on service; a free service cannot "
            "provide this storage. Paid compute and disk charges apply."
        )
        st.write("First preserve the existing trading database and keep a verified backup outside the service. Attach a 1 GB disk at /var/data to the existing service, then restore the book to /var/data/trendforge.db. Do not replace an existing book with an empty database.")
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
            "TRENDFORGE_STORAGE_RECOVERY_VERIFIED=false\n"
            "TRENDFORGE_PAPER_ALLOW_EPHEMERAL_SIMULATION=false\n"
            "TRENDFORGE_ALLOW_EPHEMERAL_ADMIN_WRITES=false\n"
            "WEB_CONCURRENCY=1",
            language="text",
        )
        st.write(
            "After restoring the initialized book, change the start command to "
            "python -m scripts.render_paper_runtime. The first launch records matching "
            "database/file evidence and keeps entries blocked. Restart the service; "
            "a new process verifies the mount, integrity and saved evidence. "
            "Confirm known ledger records and successful position restoration, then "
            "review readiness and press Start. Automation stays OFF after restart."
        )
        st.caption(
            "Check the running server's storage booleans at /production/health and "
            "protected paper readiness. A separate shell does not inherit the "
            "launcher's process-local recovery flag. Changing a flag alone cannot attach storage."
        )
        st.markdown("[Detailed storage activation and backup instructions](https://github.com/TrendForge2001/TRENDFORGE_CORE/blob/main/docs/M02_M03_OPERATIONS.md#m02-activation-on-the-existing-render-service)")
        st.write("PC-only alternative: run both the webapp and engine on the PC. Render cannot mount your PC drive.")
        st.code(
            "powershell -NoProfile -ExecutionPolicy Bypass -File "
            ".\\scripts\\windows\\Start-TrendForgePaper.ps1",
            language="powershell",
        )
