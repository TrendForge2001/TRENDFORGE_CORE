"""Read-only authentication evidence and PC-only paper execution placement."""

import asyncio
import secrets
from types import SimpleNamespace

import pytest

from providers.kite_errors import TokenException
from services.kite_session_probe import start_session_probe, stop_session_probe
from services.paper_trading_service import (
    PaperTradingDisabledError,
    PaperTradingService,
)
from services.strategy_paper_automation import StrategyPaperAutomation
from webapp.paper_policy import paper_policy_notice


def test_startup_probe_is_off_without_explicit_configuration(monkeypatch):
    monkeypatch.delenv("TRENDFORGE_KITE_SESSION_PROBE_ON_START", raising=False)

    def forbidden():
        pytest.fail("Disabled startup probe must not construct a broker")

    assert start_session_probe(SimpleNamespace(), forbidden) is None


@pytest.mark.parametrize("outcome", ["authenticated", "rejected", "invalid_health"])
def test_startup_probe_records_safe_auth_evidence_without_orders(
    monkeypatch, caplog, outcome
):
    monkeypatch.setenv("TRENDFORGE_KITE_SESSION_PROBE_ON_START", "true")
    private = secrets.token_hex(16)
    calls = []

    class Broker:
        def health(self):
            calls.append("profile")
            if outcome == "rejected":
                raise TokenException(private, code=403)
            if outcome == "invalid_health":
                return {"authenticated": False, "auth_error_code": private}
            return {"authenticated": True, "private": private}

        def place_order(self, **kwargs):
            pytest.fail("Startup probe must never submit an order")

    app = SimpleNamespace(state=SimpleNamespace())

    async def run():
        task = start_session_probe(app, Broker)
        await task
        await stop_session_probe(task)

    asyncio.run(run())
    assert calls == ["profile"]
    assert app.state.kite_session_probe == {
        "authenticated": outcome == "authenticated",
        "code": {
            "authenticated": "ok",
            "rejected": "token_rejected",
            "invalid_health": "probe_failed",
        }[outcome],
    }
    assert private not in caplog.text
    assert private not in str(app.state.kite_session_probe)


def test_cloud_role_blocks_entries_even_with_instance_opt_in(monkeypatch):
    monkeypatch.setenv("TRENDFORGE_CLOUD_READ_ONLY", "true")
    runtime = SimpleNamespace(open=lambda *args, **kwargs: pytest.fail("No cloud fill"))
    paper = PaperTradingService(
        runtime=runtime, enabled=True, environment_kill_switch=False
    )
    assert not paper.can_open_new_positions
    assert paper.entry_storage_policy()["reason"] == "cloud_read_only"
    with pytest.raises(PaperTradingDisabledError, match="PC"):
        paper.open(SimpleNamespace(symbol="TCS"))


def test_cloud_notice_does_not_request_a_paid_disk():
    policy = {
        "mode": "blocked",
        "reason": "cloud_read_only",
        "production": True,
        "entry_allowed": False,
        "verified_persistent": False,
        "ephemeral_simulation": False,
    }
    level, message = paper_policy_notice({"entry_storage_policy": policy})
    assert level == "info"
    assert "PC" in message and "cloud" in message
    assert "storage is verified" not in message


def test_cloud_cannot_start_automation_before_scanning_or_saving(monkeypatch):
    monkeypatch.setenv("TRENDFORGE_CLOUD_READ_ONLY", "true")
    automation = object.__new__(StrategyPaperAutomation)
    with pytest.raises(ValueError, match="read-only.*PC"):
        automation.configure(True)
