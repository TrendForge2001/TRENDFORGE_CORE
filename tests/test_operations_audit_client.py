from __future__ import annotations

import json

import pytest

from scripts.operations_audit import (
    HEADER,
    AuditClientError,
    audit,
    call_once,
    target_url,
    validate_result,
)


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(
            self.payload
        ).encode("utf-8")


def payload(
    status="healthy",
    reason="successful_run_recorded",
    *,
    operation="morning",
):
    return {
        "status": status,
        "operation": operation,
        "auth_scope": "operations_external_tick_only",
        "broker_orders_allowed": False,
        "audit": {
            "audit_id": "audit-1",
            "reason": reason,
        },
        "alert": None,
    }


def test_target_url_requires_https_outside_localhost():
    assert (
        target_url("https://trendforge.example/")
        == "https://trendforge.example/operations/external-audit"
    )
    assert (
        target_url("http://localhost:8000")
        == "http://localhost:8000/operations/external-audit"
    )

    for value in (
        "trendforge.example",
        "http://trendforge.example",
        "https://user:pass@trendforge.example",
        "https://trendforge.example?key=x",
    ):
        with pytest.raises(AuditClientError):
            target_url(value)


def test_call_once_uses_scheduler_key_not_admin_key():
    captured = {}

    def opener(request, timeout):
        captured["headers"] = {
            name.lower(): value
            for name, value in request.header_items()
        }
        captured["body"] = json.loads(
            request.data.decode("utf-8")
        )
        captured["timeout"] = timeout
        return Response(payload())

    result = call_once(
        url=(
            "https://trendforge.example"
            "/operations/external-audit"
        ),
        key="s" * 40,
        expected_operation="morning",
        timeout=30,
        opener=opener,
    )

    assert result["status"] == "healthy"
    assert (
        captured["headers"][HEADER.lower()]
        == "s" * 40
    )
    assert "x-trendforge-admin-key" not in captured["headers"]
    assert captured["body"] == {
        "expected_operation": "morning"
    }


def test_validate_result_accepts_healthy_and_non_market_day():
    assert validate_result(
        payload(),
        expected_operation="morning",
    ) == (
        "healthy",
        "successful_run_recorded",
    )
    assert validate_result(
        payload(
            "not_required",
            "non_market_day",
        ),
        expected_operation="morning",
    ) == (
        "not_required",
        "non_market_day",
    )


@pytest.mark.parametrize(
    "status",
    [
        "missed",
        "degraded",
        "configuration_error",
    ],
)
def test_validate_result_fails_reliability_states(status):
    with pytest.raises(AuditClientError):
        validate_result(
            payload(status, f"{status}_reason"),
            expected_operation="morning",
        )


def test_validate_result_rejects_scope_or_broker_safety_drift():
    wrong_scope = payload()
    wrong_scope["auth_scope"] = "admin"
    with pytest.raises(AuditClientError):
        validate_result(
            wrong_scope,
            expected_operation="morning",
        )

    unsafe = payload()
    unsafe["broker_orders_allowed"] = True
    with pytest.raises(AuditClientError):
        validate_result(
            unsafe,
            expected_operation="morning",
        )


def test_audit_returns_healthy_without_retry():
    calls = []

    def opener(request, timeout):
        calls.append(1)
        return Response(payload())

    result = audit(
        base_url="https://trendforge.example",
        key="s" * 40,
        expected_operation="morning",
        attempts=2,
        opener=opener,
        sleeper=lambda _: None,
    )

    assert result["status"] == "healthy"
    assert result["attempt"] == 1
    assert calls == [1]


def test_audit_rejects_short_secret_before_network_call():
    calls = []

    with pytest.raises(AuditClientError):
        audit(
            base_url="https://trendforge.example",
            key="short",
            expected_operation="eod",
            opener=lambda *args, **kwargs: calls.append(1),
        )

    assert calls == []
