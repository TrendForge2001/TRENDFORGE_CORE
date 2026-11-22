"""Explicit forward-paper admission; historical qualification stays unchanged."""

import hashlib
import json

from scanner.approved_strategies import VERSION as RULE_VERSION
from scanner.approved_strategies import active, exit_only
from scanner.strategy_registry import REGISTRY_VERSION, list_strategies
from scanner.strategy_scope import active_modes
from services.paper_admission_policy import capture, fingerprint

VERSION = "paper-research-admission-v1"
MINIMUM_COVERAGE = 0.90


def create(auto, validation, *, universe, symbols=None, strategy_ids=None, now):
    account_hash = fingerprint(capture(auto))
    request = validation.get("request") or {}
    if (
        validation.get("status") != "completed"
        or validation.get("registry_version") != REGISTRY_VERSION
        or not validation.get("run_id")
        or validation.get("admission_policy_hash") != account_hash
        or universe not in request.get("universes", [])
        or not set(request.get("modes", [])) >= set(active_modes())
        or request.get("source") != "all"
        or request.get("limit")
        or request.get("strategy_ids")
    ):
        raise ValueError("Current completed policy-aligned research evidence required")
    # Research currently preserves the saved BUY-only account policy. Short
    # availability is a different decision and cannot be inferred from this mode.
    if any("SELL" in value for value in auto.allowed_signals):
        raise ValueError("Research forward policy requires the saved BUY-only book")
    rows = {
        (row.get("strategy_id"), row.get("mode")): row
        for row in validation.get("strategy_validation", [])
    }
    pairs = []
    for definition in list_strategies():
        key = definition["strategy_id"]
        if (
            not active(key)
            or not definition["paper_eligible"]
            or definition.get("direction") != "LONG"
            or (strategy_ids is not None and key not in strategy_ids)
        ):
            continue
        for mode in definition["modes"]:
            if exit_only(key, mode):
                continue
            row = rows.get((key, mode))
            if (
                not row
                or not row.get("registry_paper_eligible")
                or not any(
                    gate.get("universe") == universe
                    for gate in row.get("universe_gates", [])
                )
            ):
                raise ValueError(
                    "Research evidence is missing an approved strategy pair"
                )
            pairs.append([key, mode])
    if not pairs:
        raise ValueError("No approved long strategy pairs in research scope")
    policy = {
        "version": VERSION,
        "registry_version": REGISTRY_VERSION,
        "rule_version": RULE_VERSION,
        "admission_policy_hash": account_hash,
        "validation_run_id": validation["run_id"],
        "authorized_at": now.isoformat(),
        "universe": universe,
        "symbols": sorted(symbols) if symbols is not None else None,
        "strategy_pairs": sorted(pairs),
        "minimum_scan_coverage": MINIMUM_COVERAGE,
        "historical_qualification_required": False,
        "paper_only": True,
        "broker_orders_allowed": False,
    }
    policy["policy_id"] = _digest(policy)
    return policy


def _digest(policy):
    return hashlib.sha256(
        json.dumps(
            {k: v for k, v in policy.items() if k != "policy_id"},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def current(policy, auto, validation):
    try:
        return bool(
            isinstance(policy, dict)
            and policy.get("version") == VERSION
            and policy.get("policy_id") == _digest(policy)
            and policy.get("registry_version") == REGISTRY_VERSION
            and policy.get("rule_version") == RULE_VERSION
            and policy.get("minimum_scan_coverage") == MINIMUM_COVERAGE
            and policy.get("historical_qualification_required") is False
            and policy.get("paper_only") is True
            and policy.get("broker_orders_allowed") is False
            and policy.get("admission_policy_hash") == fingerprint(capture(auto))
            and validation.get("status") == "completed"
            and validation.get("registry_version") == REGISTRY_VERSION
            and validation.get("run_id") == policy.get("validation_run_id")
            and validation.get("admission_policy_hash")
            == policy.get("admission_policy_hash")
        )
    except (TypeError, ValueError, AttributeError):
        return False


def admits(policy, *, strategy_id, mode, universe, symbol=None):
    return (
        policy.get("universe") == universe
        and [strategy_id, mode] in policy.get("strategy_pairs", [])
        and (
            symbol is None
            or policy.get("symbols") is None
            or symbol in policy["symbols"]
        )
    )


def scan_coverage(scan):
    requested, completed, errors = (
        scan.get(key)
        for key in ("requested_symbols", "completed_symbols", "error_symbols")
    )
    return bool(
        all(type(value) is int for value in (requested, completed, errors))
        and requested > 0
        and completed >= 0
        and errors >= 0
        and completed + errors == requested
        and completed / requested >= MINIMUM_COVERAGE
        and scan.get("status") in {"completed", "degraded"}
    )
