from __future__ import annotations

from services.discord_service import DiscordService


class FakeResponse:
    status_code = 204

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "json": json,
                "timeout": timeout,
            }
        )
        return FakeResponse()


def test_discord_service_uses_explicit_runtime_webhook():
    session = FakeSession()
    service = DiscordService(
        webhook_url="https://discord.test/hook",
        session=session,
    )

    result = service.send_notification(
        title="Alert",
        message="Message",
        severity="WARNING",
    )

    assert result["ok"] is True
    assert result["status"] == "sent"
    assert session.calls[0]["url"] == "https://discord.test/hook"
    assert "webhook_url" not in service.health()
    assert service.health()["webhook_secret_exposed"] is False


def test_discord_service_blocks_without_webhook(monkeypatch):
    monkeypatch.setattr(
        "config.settings.DISCORD_WEBHOOK",
        None,
    )
    service = DiscordService(webhook_url="")

    result = service.send_notification(
        title="Alert",
        message="Message",
    )

    assert result["ok"] is False
    assert result["status"] == "not_configured"
    assert service.health()["configured"] is False
