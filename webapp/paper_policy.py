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
