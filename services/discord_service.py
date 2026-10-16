"""Discord-only notification transport for TrendForge."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

import requests

from services.config_service import ConfigService

logger = logging.getLogger(__name__)


class DiscordService:
    """Send TrendForge notifications through a Discord webhook.

    Runtime secrets take precedence over the legacy alerts.json placeholder.
    The webhook value is never returned by health/reporting methods.
    """

    COLORS = {
        "SUCCESS": 0x57F287,
        "INFO": 0x3498DB,
        "WARNING": 0xFEE75C,
        "ERROR": 0xED4245,
        "CRITICAL": 0x992D22,
        "STRONG BUY": 0x57F287,
        "BUY": 0x3498DB,
        "WATCH": 0xFEE75C,
        "SELL": 0xED4245,
        "IGNORE": 0x808080,
    }

    def __init__(
        self,
        webhook_url: str | None = None,
        *,
        username: str | None = None,
        timeout: float | None = None,
        session: Any | None = None,
    ) -> None:
        try:
            config = ConfigService.load("alerts.json") or {}
        except Exception:
            config = {}
        discord = (
            dict(config.get("discord") or {})
            if isinstance(config, dict)
            else {}
        )

        runtime_webhook = None
        try:
            from config import settings

            runtime_webhook = getattr(
                settings,
                "DISCORD_WEBHOOK",
                None,
            )
        except Exception:
            runtime_webhook = None

        self.webhook_url = str(
            webhook_url
            or runtime_webhook
            or discord.get("webhook_url")
            or ""
        ).strip()
        self.username = str(
            username
            or discord.get("username")
            or "TrendForge"
        ).strip()
        self.timeout = float(
            timeout
            if timeout is not None
            else discord.get("timeout", 10)
        )
        self.config_enabled = bool(
            config.get("enabled", True)
            if isinstance(config, dict)
            else True
        )
        self.discord_enabled = bool(
            discord.get("enabled", True)
        )
        self.session = session or requests

    @property
    def configured(self) -> bool:
        return bool(self.webhook_url)

    def enabled(self) -> bool:
        return bool(
            self.config_enabled
            and self.discord_enabled
            and self.configured
        )

    @classmethod
    def color(cls, signal_or_level: str) -> int:
        return cls.COLORS.get(
            str(signal_or_level or "INFO").upper(),
            cls.COLORS["INFO"],
        )

    def create_notification_embed(
        self,
        *,
        title: str,
        message: str,
        severity: str = "INFO",
        fields: list[dict[str, Any]] | None = None,
        footer: str | None = None,
    ) -> dict[str, Any]:
        embed: dict[str, Any] = {
            "title": str(title),
            "description": str(message),
            "color": self.color(severity),
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
        }
        if fields:
            embed["fields"] = [
                dict(item)
                for item in fields
                if isinstance(item, dict)
            ][:25]
        if footer:
            embed["footer"] = {"text": str(footer)}
        return embed

    def send_notification(
        self,
        *,
        title: str,
        message: str,
        severity: str = "INFO",
        fields: list[dict[str, Any]] | None = None,
        footer: str | None = "TrendForge",
    ) -> dict[str, Any]:
        if not self.configured:
            return {
                "ok": False,
                "status": "not_configured",
                "provider": "Discord",
            }
        if not self.enabled():
            return {
                "ok": False,
                "status": "disabled",
                "provider": "Discord",
            }

        payload = {
            "username": self.username,
            "embeds": [
                self.create_notification_embed(
                    title=title,
                    message=message,
                    severity=severity,
                    fields=fields,
                    footer=footer,
                )
            ],
        }

        try:
            response = self.session.post(
                self.webhook_url,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return {
                "ok": True,
                "status": "sent",
                "provider": "Discord",
                "http_status": getattr(
                    response,
                    "status_code",
                    None,
                ),
            }
        except Exception as exc:
            logger.exception(
                "Discord notification failed: %s",
                exc,
            )
            return {
                "ok": False,
                "status": "failed",
                "provider": "Discord",
                "error": f"{type(exc).__name__}: {exc}",
            }

    def create_embed(
        self,
        symbol,
        result,
        price,
        target=None,
        stoploss=None,
        timeframe="Daily",
        scanner="TrendForge",
    ):
        fields = [
            {
                "name": "Signal",
                "value": result.signal,
                "inline": True,
            },
            {
                "name": "Score",
                "value": f"{result.score}/100",
                "inline": True,
            },
            {
                "name": "Price",
                "value": f"₹ {price:.2f}",
                "inline": True,
            },
            {
                "name": "Scanner",
                "value": scanner,
                "inline": True,
            },
            {
                "name": "Timeframe",
                "value": timeframe,
                "inline": True,
            },
        ]
        if target is not None:
            fields.append(
                {
                    "name": "Target",
                    "value": f"₹ {target:.2f}",
                    "inline": True,
                }
            )
        if stoploss is not None:
            fields.append(
                {
                    "name": "Stop Loss",
                    "value": f"₹ {stoploss:.2f}",
                    "inline": True,
                }
            )
        if getattr(result, "reasons", None):
            fields.append(
                {
                    "name": "Reasons",
                    "value": "\n".join(
                        f"• {reason}"
                        for reason in result.reasons
                    ),
                    "inline": False,
                }
            )
        return self.create_notification_embed(
            title=f"📈 {symbol}",
            message="TrendForge Trading Signal",
            severity=getattr(result, "signal", "INFO"),
            fields=fields,
            footer="TrendForge",
        )

    def send(
        self,
        symbol,
        result,
        price,
        target=None,
        stoploss=None,
        timeframe="Daily",
        scanner="TrendForge",
    ):
        if not self.configured:
            logger.warning("Discord alerts are not configured.")
            return False
        payload = {
            "username": self.username,
            "embeds": [
                self.create_embed(
                    symbol,
                    result,
                    price,
                    target,
                    stoploss,
                    timeframe,
                    scanner,
                )
            ],
        }
        try:
            response = self.session.post(
                self.webhook_url,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            logger.info("Discord alert sent.")
            return True
        except Exception as exc:
            logger.exception(
                "Discord alert failed: %s",
                exc,
            )
            return False

    def send_test(self) -> bool:
        result = self.send_notification(
            title="TrendForge Discord Test",
            message=(
                "Discord delivery is configured and the "
                "notification transport is reachable."
            ),
            severity="SUCCESS",
            footer="TrendForge · System Test",
        )
        return bool(result.get("ok"))

    def health(self) -> dict[str, Any]:
        return {
            "status": (
                "ready"
                if self.enabled()
                else "not_configured"
                if not self.configured
                else "disabled"
            ),
            "enabled": self.enabled(),
            "provider": "Discord",
            "configured": self.configured,
            "network_probe": False,
            "webhook_secret_exposed": False,
        }


__all__ = ["DiscordService"]
