"""Recorded strategy identity, without relabelling old evidence as current."""

import json

UNRECORDED = "unrecorded"


def text(value):
    return (
        value.strip()[:180] if isinstance(value, str) and value.strip() else UNRECORDED
    )


def plan_from(row):
    plan = row.get("paper_plan")
    if isinstance(plan, dict):
        return plan
    try:
        plan = json.loads(row.get("paper_plan_json") or "null")
        return plan if isinstance(plan, dict) else {}
    except (TypeError, ValueError):
        return {}


def identity(row, *, plan=None):
    plan = plan if isinstance(plan, dict) else plan_from(row)
    saved = plan.get("strategy_provenance") or {}
    saved = saved if isinstance(saved, dict) else {}
    parameters = row.get("parameters") or {}
    parameters = parameters if isinstance(parameters, dict) else {}
    return {
        "strategy_id": text(row.get("strategy_id") or plan.get("strategy_id")),
        "registry_version": text(
            row.get("registry_version") or saved.get("registry_version")
        ),
        "policy_version": text(
            plan.get("policy_version")
            or row.get("exit_policy_version")
            or parameters.get("exit_policy_version")
            or saved.get("policy_version")
        ),
        "cost_model_version": text(row.get("cost_model_version")),
    }


def new_plan_identity(strategy_id, plan):
    from scanner.strategy_registry import REGISTRY_VERSION

    return identity(
        {"strategy_id": strategy_id, "registry_version": REGISTRY_VERSION}, plan=plan
    )
