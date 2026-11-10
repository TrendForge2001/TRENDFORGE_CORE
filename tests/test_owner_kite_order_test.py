"""Exact owner instruction, durable claim, transport ambiguity and disabled default."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta
from threading import Barrier
from zoneinfo import ZoneInfo

import pytest

from core.database import initialize_database
from providers.kite_errors import NetworkException, OrderException, TokenException
from services.owner_kite_order_test import ENV, run_configured_order_test, submit_once

NOW = datetime(2026, 11, 10, 8, 40, tzinfo=ZoneInfo("Asia/Kolkata"))


def intent(**changes):
    return {
        "intent_id": "test-sbin-once-20261110",
        "symbol": "SBIN",
        "quantity": 5,
        "accept_execution": True,
        "expires_at": NOW + timedelta(minutes=20),
        **changes,
    }


@pytest.fixture
def book(tmp_path):
    path = tmp_path / "book.db"
    initialize_database(str(path))
    return path


class Broker:
    def __init__(self, guard, calls, outcome=None):
        self.guard, self.calls, self.outcome = guard, calls, outcome

    def profile(self):
        if self.outcome == "auth":
            raise TokenException("private response")
        return {"authenticated": True}

    def instruments(self, exchange):
        assert exchange == "NSE"
        return [
            {
                "exchange": "NSE",
                "instrument_type": "EQ",
                "tradingsymbol": "SBIN",
                "lot_size": 1,
            }
        ]

    def place_order(self, **kwargs):
        self.guard()
        self.calls.append(kwargs)
        if self.outcome == "reject":
            raise OrderException("Market is closed; private data", 400)
        if self.outcome == "timeout":
            raise NetworkException("private transport response")
        return "order-123"

    def order_history(self, order_id):
        assert order_id == "order-123"
        return [
            {
                "status": "OPEN",
                "filled_quantity": 0,
                "pending_quantity": 5,
                "account_secret": "private",
            }
        ]

    def orders(self):
        return []


def test_exact_order_is_once_only_across_restarts_with_general_live_guard_off(
    book, monkeypatch
):
    monkeypatch.setenv("TRENDFORGE_LIVE_TRADING_ENABLED", "false")
    calls = []

    def factory(guard):
        return Broker(guard, calls)

    receipt = submit_once(intent(), database=book, factory=factory, clock=lambda: NOW)
    assert receipt["status"] == "accepted" and receipt["broker_status"] == "OPEN"
    assert receipt["filled_quantity"] == 0 and receipt["pending_quantity"] == 5
    assert calls == [
        dict(
            variety="regular",
            exchange="NSE",
            tradingsymbol="SBIN",
            transaction_type="BUY",
            quantity=5,
            product="CNC",
            order_type="MARKET",
            validity="DAY",
            tag=receipt["tag"],
        )
    ]
    again = submit_once(intent(), database=book, factory=factory, clock=lambda: NOW)
    assert again["duplicate_blocked"] and len(calls) == 1
    assert "private" not in str(receipt)
    import os

    assert os.environ["TRENDFORGE_LIVE_TRADING_ENABLED"] == "false"


@pytest.mark.parametrize(
    "outcome,status,attempts",
    [
        ("auth", "preflight_blocked", 0),
        ("reject", "broker_rejected", 1),
        ("timeout", "unknown", 1),
    ],
)
def test_auth_rejection_and_timeout_do_not_retry_or_leak_details(
    book, outcome, status, attempts
):
    calls = []

    def factory(guard):
        return Broker(guard, calls, outcome)

    receipt = submit_once(intent(), database=book, factory=factory, clock=lambda: NOW)
    assert receipt["status"] == status and receipt["submit_attempts"] == attempts
    assert len(calls) == attempts and "private" not in str(receipt)
    submit_once(intent(), database=book, factory=factory, clock=lambda: NOW)
    assert len(calls) == attempts
    if outcome == "reject":
        assert receipt["reason"] == "MARKET_CLOSED" and receipt["http_status"] == 400


def test_concurrent_workers_cannot_submit_twice(book):
    calls = []
    barrier = Barrier(2)

    def execute():
        barrier.wait(5)
        return submit_once(
            intent(),
            database=book,
            factory=lambda guard: Broker(guard, calls),
            clock=lambda: NOW,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: execute(), range(2)))
    assert (
        len(calls) == 1
        and sum(row.get("duplicate_blocked", False) for row in results) == 1
    )


@pytest.mark.parametrize(
    "change",
    [
        {"symbol": "TCS"},
        {"quantity": 6},
        {"quantity": True},
        {"accept_execution": False},
        {"product": "MIS"},
        {"expires_at": NOW.replace(tzinfo=None)},
        {"expires_at": NOW.replace(hour=10)},
    ],
)
def test_instruction_cannot_expand_or_be_ambiguous(book, change):
    calls = []
    with pytest.raises(ValueError):
        submit_once(
            intent(**change),
            database=book,
            factory=lambda guard: Broker(guard, calls),
            clock=lambda: NOW,
        )
    assert calls == []


def test_expiry_and_missing_book_cannot_send_or_create_replacement(book, tmp_path):
    calls = []
    result = submit_once(
        intent(),
        database=book,
        factory=lambda guard: Broker(guard, calls),
        clock=lambda: NOW + timedelta(minutes=30),
    )
    assert result["status"] == "expired" and calls == []
    missing = tmp_path / "missing.db"
    with pytest.raises(sqlite3.Error):
        submit_once(
            intent(),
            database=missing,
            factory=lambda guard: Broker(guard, calls),
            clock=lambda: NOW,
        )
    assert not missing.exists()


def test_duplicate_intent_id_with_new_payload_is_rejected(book):
    submit_once(
        intent(),
        database=book,
        factory=lambda guard: Broker(guard, []),
        clock=lambda: NOW,
    )
    with pytest.raises(ValueError, match="another request"):
        submit_once(
            intent(expires_at=NOW + timedelta(minutes=21)),
            database=book,
            factory=lambda guard: pytest.fail("No broker access"),
            clock=lambda: NOW,
        )
    with closing(sqlite3.connect(book)) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM settings "
            "WHERE key LIKE 'kite.owner_order_test.once.%'"
        ).fetchone() == (1,)


def test_unconfigured_hook_has_no_storage_or_network_activity(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    assert run_configured_order_test() is None
