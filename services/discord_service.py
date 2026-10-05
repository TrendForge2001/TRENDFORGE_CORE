"""Discord alert service for TrendForge."""

from __future__ import annotations

from datetime import datetime
import logging

import requests

from services.config_service import ConfigService

logger = logging.getLogger(__name__)


class DiscordService:
    """Send scanner/trading alerts to Discord."""

    def __init__(self):
        self.config = ConfigService.load("alerts.json")
        self.discord = self.config.get("discord", {})

    def enabled(self):
        return bool(
            self.config.get("enabled", False)
            and self.discord.get("enabled", False)
            and self.discord.get("webhook_url", "")
        )

    def color(self, signal):
        colors = {
            "STRONG BUY": 0x00FF00,
            "BUY": 0x0099FF,
            "WATCH": 0xFFD700,
            "SELL": 0xFF0000,
            "IGNORE": 0x808080,
        }
        return colors.get(signal, 0x0099FF)

    def create_embed(self, symbol, result, price, target=None, stoploss=None, timeframe="Daily", scanner="TrendForge"):
        fields = [
            {"name": "Signal", "value": result.signal, "inline": True},
            {"name": "Score", "value": f"{result.score}/100", "inline": True},
            {"name": "Price", "value": f"₹ {price:.2f}", "inline": True},
            {"name": "Scanner", "value": scanner, "inline": True},
            {"name": "Timeframe", "value": timeframe, "inline": True},
        ]
        if target is not None:
            fields.append({"name": "Target", "value": f"₹ {target:.2f}", "inline": True})
        if stoploss is not None:
            fields.append({"name": "Stop Loss", "value": f"₹ {stoploss:.2f}", "inline": True})
        if result.reasons:
            fields.append({"name": "Reasons", "value": "\n".join(f"• {reason}" for reason in result.reasons), "inline": False})
        return {
            "title": f"📈 {symbol}",
            "description": "TrendForge Trading Signal",
            "color": self.color(result.signal),
            "fields": fields,
            "footer": {"text": datetime.now().strftime("%d-%b-%Y %H:%M:%S")},
        }

    def send(self, symbol, result, price, target=None, stoploss=None, timeframe="Daily", scanner="TrendForge"):
        if not self.enabled():
            logger.warning("Discord alerts disabled.")
            return False
        payload = {
            "username": self.discord.get("username", "TrendForge"),
            "avatar_url": self.discord.get("avatar_url", ""),
            "embeds": [self.create_embed(symbol, result, price, target, stoploss, timeframe, scanner)],
        }
        try:
            response = requests.post(
                self.discord["webhook_url"],
                json=payload,
                timeout=self.discord.get("timeout", 10),
            )
            response.raise_for_status()
            logger.info("Discord alert sent.")
            return True
        except Exception as exc:
            logger.exception("Discord alert failed: %s", exc)
            return False

    def send_test(self):
        class Dummy:
            signal = "BUY"
            score = 95
            reasons = ["EMA Alignment", "20-Day Breakout", "MACD Bullish", "High RVOL"]

        return self.send("TRENDFORGE", Dummy(), 1000, 1080, 970, "Daily", "System Test")

    def health(self):
        """Report local configuration without sending a webhook request."""
        webhook_configured = bool(self.discord.get("webhook_url", ""))
        return {
            "status": "configured" if webhook_configured else "degraded",
            "enabled": self.enabled(),
            "provider": "Discord",
            "configured": webhook_configured,
            "network_probe": False,
        }
