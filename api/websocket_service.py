"""Centralized Kite WebSocket service for TrendForge."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional, Set

from kiteconnect import KiteTicker

logger = logging.getLogger(__name__)


class WebSocketServiceError(Exception):
    """Base WebSocket exception."""


class WebSocketNotConnectedError(WebSocketServiceError):
    """Raised when websocket is disconnected."""


@dataclass(slots=True)
class MarketTick:
    instrument_token: int
    ltp: float
    open: float
    high: float
    low: float
    close: float
    volume: int
    oi: int | None
    timestamp: datetime
    raw: dict


class WebSocketService:
    """Shared, thread-safe Kite WebSocket service."""

    def __init__(self, api_key: str, access_token: str) -> None:
        self.api_key = api_key
        self.access_token = access_token
        self._ticker: Optional[KiteTicker] = None
        self._connected = False
        self._last_tick_time: datetime | None = None
        self._tick_count = 0
        self._reconnect_count = 0
        self._start_time = time.time()
        self._running = False
        self._lock = threading.RLock()
        self._tokens: Set[int] = set()
        self.tick_cache: dict[int, MarketTick] = {}
        self.callbacks: Set[Callable[[list], None]] = set()

    @property
    def ticker(self) -> KiteTicker:
        if self._ticker is None:
            raise WebSocketNotConnectedError("WebSocket not connected.")
        return self._ticker

    def connect(self) -> None:
        with self._lock:
            if self._connected or self._running:
                return
            self._ticker = KiteTicker(self.api_key, self.access_token)
            self._register_callbacks()
            self._running = True
            thread = threading.Thread(
                target=self._ticker.connect,
                kwargs={"threaded": True},
                daemon=True,
                name="KiteWebSocket",
            )
            thread.start()

    def disconnect(self) -> None:
        with self._lock:
            self._running = False
            if self._ticker is not None:
                try:
                    self._ticker.close()
                except Exception:
                    logger.exception("WebSocket close failed.")
            self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def subscribe(self, instrument_tokens: list[int]) -> None:
        tokens = [int(token) for token in instrument_tokens]
        self._tokens.update(tokens)
        if self._connected:
            self.ticker.subscribe(tokens)
            self.ticker.set_mode(self.ticker.MODE_FULL, tokens)

    def unsubscribe(self, instrument_tokens: list[int]) -> None:
        tokens = [int(token) for token in instrument_tokens]
        for token in tokens:
            self._tokens.discard(token)
        if self._connected:
            self.ticker.unsubscribe(tokens)

    def register_callback(self, callback: Callable[[list], None]) -> None:
        self.callbacks.add(callback)

    def unregister_callback(self, callback: Callable[[list], None]) -> None:
        self.callbacks.discard(callback)

    def _register_callbacks(self) -> None:
        self.ticker.on_connect = self._on_connect
        self.ticker.on_ticks = self._on_ticks
        self.ticker.on_close = self._on_close
        self.ticker.on_error = self._on_error
        self.ticker.on_reconnect = self._on_reconnect
        self.ticker.on_noreconnect = self._on_noreconnect

    def _on_ticks(self, ws, ticks: list) -> None:
        if not ticks:
            return
        with self._lock:
            self._tick_count += len(ticks)
            self._last_tick_time = datetime.now()
            for tick in ticks:
                token = int(tick["instrument_token"])
                ohlc = tick.get("ohlc") or {}
                self.tick_cache[token] = MarketTick(
                    instrument_token=token,
                    ltp=float(tick.get("last_price") or 0),
                    open=float(ohlc.get("open") or 0),
                    high=float(ohlc.get("high") or 0),
                    low=float(ohlc.get("low") or 0),
                    close=float(ohlc.get("close") or 0),
                    volume=int(tick.get("volume_traded") or 0),
                    oi=tick.get("oi"),
                    timestamp=tick.get("exchange_timestamp") or datetime.now(),
                    raw=tick,
                )
        for callback in list(self.callbacks):
            try:
                callback(ticks)
            except Exception:
                logger.exception("Tick callback failed.")

    def _on_connect(self, ws, response) -> None:
        self._connected = True
        if self._tokens:
            tokens = list(self._tokens)
            ws.subscribe(tokens)
            ws.set_mode(ws.MODE_FULL, tokens)

    def _on_close(self, ws, code, reason) -> None:
        self._connected = False
        self._reconnect_count += 1
        logger.warning("WebSocket closed: %s %s", code, reason)

    def _on_error(self, ws, code, reason) -> None:
        logger.error("WebSocket error %s | %s", code, reason)

    def _on_reconnect(self, ws, attempts) -> None:
        logger.warning("Reconnect attempt %d", attempts)

    def _on_noreconnect(self, ws) -> None:
        self._connected = False
        logger.error("WebSocket reconnection failed.")

    def get_tick(self, instrument_token: int):
        return self.tick_cache.get(int(instrument_token))

    def get_ltp(self, instrument_token: int) -> float | None:
        tick = self.get_tick(instrument_token)
        return tick.ltp if tick else None

    def get_ohlc(self, instrument_token: int) -> dict:
        tick = self.get_tick(instrument_token)
        if tick is None:
            return {}
        return {"open": tick.open, "high": tick.high, "low": tick.low, "close": tick.close}

    def get_volume(self, instrument_token: int) -> int:
        tick = self.get_tick(instrument_token)
        return tick.volume if tick else 0

    def get_market_depth(self, instrument_token: int) -> dict:
        tick = self.get_tick(instrument_token)
        return tick.raw.get("depth", {}) if tick else {}

    def get_oi(self, instrument_token: int) -> int | None:
        tick = self.get_tick(instrument_token)
        return tick.oi if tick else None

    def clear_cache(self) -> None:
        with self._lock:
            self.tick_cache.clear()

    def cache_size(self) -> int:
        return len(self.tick_cache)

    def uptime(self) -> float:
        return round(time.time() - self._start_time, 2)

    def last_tick_time(self):
        return self._last_tick_time

    def tick_count(self) -> int:
        return self._tick_count

    def reconnect_count(self) -> int:
        return self._reconnect_count

    def health(self) -> dict:
        return {
            "status": "healthy" if self._connected else "disconnected",
            "connected": self.is_connected(),
            "uptime": self.uptime(),
            "tick_count": self.tick_count(),
            "reconnects": self.reconnect_count(),
            "last_tick": self.last_tick_time(),
            "cache_size": self.cache_size(),
            "subscriptions": len(self._tokens),
        }

    def shutdown(self) -> None:
        self.disconnect()
        self.callbacks.clear()
        self.clear_cache()


__all__ = [
    "MarketTick",
    "WebSocketService",
    "WebSocketServiceError",
    "WebSocketNotConnectedError",
]
