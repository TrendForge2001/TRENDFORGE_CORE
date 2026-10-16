from __future__ import annotations

from services.notification_producer_service import (
    NotificationProducerService,
)


class FakeCenter:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = []

    def route_event(self, **kwargs):
        if self.fail:
            raise RuntimeError("notification store unavailable")
        self.calls.append(dict(kwargs))
        return {
            "event_id": f"evt-{len(self.calls)}",
            "status": (
                "sent"
                if kwargs.get("deliver")
                else "recorded"
            ),
            **kwargs,
        }


def pick(symbol="TCS", signal="BUY", score=94, confidence=82):
    return {
        "symbol": symbol,
        "signal": {
            "signal": signal,
            "overall_score": score,
            "confidence": confidence,
        },
        "ranking_score": score,
        "confidence": confidence,
        "execution_eligible": True,
    }


def test_completed_scan_records_summary_and_delivers_capped_picks():
    center = FakeCenter()
    producer = NotificationProducerService(
        center,
        max_scan_picks=2,
    )

    result = producer.scan_completed(
        {
            "outcome": "completed",
            "execution_top_picks": [
                pick("TCS"),
                pick("INFY", score=91),
                pick("LUPIN", score=90),
            ],
            "analysis_count": 3,
            "execution_count": 3,
            "scale_gate": {
                "requested_symbols": 100,
                "completed_symbols": 100,
                "error_symbols": 0,
            },
        },
        run_id="scan-1",
    )

    assert result["pick_event_count"] == 2
    assert len(center.calls) == 3
    assert center.calls[0]["event_type"] == "scanner_completed"
    assert center.calls[0]["deliver"] is False
    assert center.calls[1]["event_type"] == "scanner_pick"
    assert center.calls[1]["symbol"] == "TCS"
    assert center.calls[1]["deliver"] is True
    assert center.calls[2]["symbol"] == "INFY"


def test_partial_scan_never_delivers_pick_alerts():
    center = FakeCenter()
    producer = NotificationProducerService(
        center,
        max_scan_picks=3,
    )

    result = producer.scan_completed(
        {
            "outcome": "partial",
            "execution_top_picks": [pick("TCS")],
            "scale_gate": {
                "requested_symbols": 100,
                "completed_symbols": 50,
                "deferred_symbol_count": 50,
            },
        },
        run_id="partial-1",
    )

    assert result["pick_event_count"] == 0
    assert len(center.calls) == 1
    assert center.calls[0]["event_type"] == "scanner_partial"
    assert center.calls[0]["deliver"] is False


def test_producer_failure_is_captured_not_raised():
    producer = NotificationProducerService(
        FakeCenter(fail=True),
    )

    result = producer.scan_failed(
        run_id="bad-scan",
        failure_stage="scan_execution",
        message="provider failed",
        http_status=503,
    )

    assert result["status"] == "producer_error"
    health = producer.health()
    assert health["failures"] == 1
    assert health["best_effort"] is True
    assert (
        health["primary_operations_fail_closed_on_notification_error"]
        is False
    )


def test_paper_open_and_close_are_delivered():
    center = FakeCenter()
    producer = NotificationProducerService(center)

    opened = producer.paper_opened(
        trade_id=7,
        symbol="tcs",
        side="BUY",
        quantity=5,
        entry_price=3000,
        stoploss=2950,
        target=3100,
    )
    closed = producer.paper_closed(
        {
            "trade_id": 7,
            "symbol": "TCS",
            "exit_price": 3100,
            "pnl": 500,
            "reason": "TARGET",
        }
    )

    assert opened["status"] == "sent"
    assert closed["status"] == "sent"
    assert center.calls[0]["dedupe_key"] == "paper-open:7"
    assert center.calls[1]["dedupe_key"] == "paper-close:7"


def test_auto_entry_emits_only_high_value_risk_blocks():
    center = FakeCenter()
    producer = NotificationProducerService(center)

    result = producer.auto_entry_result(
        {
            "status": "no_entries",
            "run_id": "run-risk",
            "opened_count": 0,
            "evaluations": [
                {
                    "symbol": "TCS",
                    "reasons": [
                        "maximum_daily_loss_reached",
                        "reward_risk_below_minimum",
                    ],
                    "daily_loss": 3000,
                    "daily_loss_limit": 3000,
                },
                {
                    "symbol": "INFY",
                    "reasons": [
                        "maximum_daily_loss_reached",
                        "maximum_open_positions_reached",
                    ],
                    "open_positions": 5,
                    "max_open_positions": 5,
                },
            ],
        }
    )

    assert result["risk_event_count"] == 2
    event_types = [
        call["event_type"]
        for call in center.calls
    ]
    assert event_types == [
        "paper_auto_entry_evaluated",
        "paper_risk_block",
        "paper_risk_block",
    ]
    assert center.calls[0]["deliver"] is False
    assert center.calls[1]["severity"] == "CRITICAL"
    assert center.calls[2]["severity"] == "WARNING"


def test_kill_switch_events_only_encode_paper_runtime_state():
    center = FakeCenter()
    producer = NotificationProducerService(center)

    enabled = producer.kill_switch_changed(enabled=True)
    disabled = producer.kill_switch_changed(enabled=False)

    assert enabled["status"] == "sent"
    assert disabled["status"] == "sent"
    assert center.calls[0]["category"] == "risk"
    assert center.calls[0]["payload"]["paper_only"] is True
    assert center.calls[1]["severity"] == "SUCCESS"
