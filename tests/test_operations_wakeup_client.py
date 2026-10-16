from __future__ import annotations

import json

import pytest

from scripts.operations_wakeup import (
    HEADER,
    MissedWindowError,
    WakeupError,
    call_once,
    outcome,
    target_url,
    wake,
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
    status="satisfied",
    reason="successful_run_recorded",
    *,
    operation="morning",
):
    return {
        "status": status,
        "expected_operation": operation,
        "tick": {
            "status": "active_window",
        },
        "after": {
            "status": status,
            "reason": reason,
        },
    }


def test_target_url_requires_absolute_url_without_credentials():
    assert (
        target_url("https://trendforge.example/")
        == "https://trendforge.example/operations/external-tick"
    )

    for value in (
        "trendforge.example",
        "https://user:pass@trendforge.example",
        "https://trendforge.example?token=x",
    ):
        with pytest.raises(WakeupError):
            target_url(value)


def test_call_once_sends_only_scheduler_key_header():
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["key"] = next(
            value
            for name, value in request.header_items()
            if name.lower() == HEADER.lower()
        )
        captured["body"] = json.loads(
            request.data.decode("utf-8")
        )
        return Response(payload())

    result = call_once(
        url=(
            "https://trendforge.example"
            "/operations/external-tick"
        ),
        key="s" * 40,
        expected_operation="morning",
        timeout=25,
        opener=opener,
    )

    assert result["status"] == "satisfied"
    assert captured["key"] == "s" * 40
    assert captured["body"] == {
        "expected_operation": "morning"
    }
    assert captured["timeout"] == 25


def test_outcome_accepts_satisfied_and_not_required():
    assert outcome(
        payload(),
        expected_operation="morning",
    ) == (
        "satisfied",
        "successful_run_recorded",
    )
    assert outcome(
        payload(
            "not_required",
            "non_market_day",
        ),
        expected_operation="morning",
    ) == (
        "not_required",
        "non_market_day",
    )


def test_outcome_fails_loudly_for_missed_window():
    with pytest.raises(MissedWindowError):
        outcome(
            payload(
                "missed_window",
                "window_elapsed_without_success",
            ),
            expected_operation="morning",
        )


def test_wake_retries_pending_then_returns_satisfied():
    responses = [
        payload("pending", "before_window"),
        payload("satisfied"),
    ]
    sleeps = []

    def opener(request, timeout):
        return Response(responses.pop(0))

    result = wake(
        base_url="https://trendforge.example",
        key="s" * 40,
        expected_operation="morning",
        attempts=3,
        timeout=10,
        base_delay=2,
        opener=opener,
        sleeper=sleeps.append,
    )

    assert result["status"] == "satisfied"
    assert result["attempt"] == 2
    assert sleeps == [2.0]


def test_wake_rejects_short_secret_without_network_call():
    called = []

    with pytest.raises(WakeupError):
        wake(
            base_url="https://trendforge.example",
            key="short",
            expected_operation="morning",
            opener=lambda *args, **kwargs: called.append(1),
        )

    assert called == []
