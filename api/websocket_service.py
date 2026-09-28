"""
TrendForge v2
api/websocket_service.py

Centralized Kite WebSocket service.

Responsibilities
----------------
• Live Market Feed
• Auto Reconnect
• Subscription Management
• Tick Cache
• Shared WebSocket
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Dict, Optional, Set
from dataclasses import dataclass
from datetime import datetime

from kiteconnect import KiteTicker

logger = logging.getLogger(__name__)


class WebSocketServiceError(Exception):
    """Base WebSocket exception."""


class WebSocketNotConnectedError(WebSocketServiceError):
    """Raised when websocket is disconnected."""


class WebSocketService:
    """
    Shared WebSocket service.

    This class maintains ONE websocket connection
    for the entire TrendForge application.

    Scanner
        ↓

    Dashboard
        ↓

    Auto Trader
        ↓

    Paper Trader

    All share the same websocket.
    """

    def __init__(
        self,
        api_key: str,
        access_token: str,
    ) -> None:

        self.api_key = api_key
        self.access_token = access_token

        self._ticker: Optional[KiteTicker] = None

        self._connected = False
        self._last_tick_time = None
        self._tick_count = 0
        self._reconnect_count = 0
        self._start_time = time.time()
        self._running = False

        self._lock = threading.RLock()

        # -----------------------------------
        # Subscriptions
        # -----------------------------------

        self._tokens: Set[int] = set()

        # -----------------------------------
        # Live Tick Cache
        # -----------------------------------

        self.tick_cache: Dict[int, "MarketTick"] = {}
        logger = logging.getLogger(__name__)
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

        # -----------------------------------
        # User callbacks
        # -----------------------------------

        self.callbacks: Set[
    Callable[[list], None]
] = set()

        logger.info(
            "WebSocketService initialized."
        )
        self._last_tick_time = datetime.now()

    # ---------------------------------------------------------
    # Connection
    # ---------------------------------------------------------

    @property
    def ticker(self) -> KiteTicker:

        if self._ticker is None:

            raise WebSocketNotConnectedError(
                "WebSocket not connected."
            )

        return self._ticker

    def connect(self) -> None:
        """
        Starts websocket.
        """

        with self._lock:

            if self._connected:
                return

            logger.info(
                "Connecting websocket..."
            )

            self._ticker = KiteTicker(
                self.api_key,
                self.access_token,
            )

            self._register_callbacks()

            self._running = True

            thread = threading.Thread(
                target=self._ticker.connect,
                kwargs={
                    "threaded": True
                },
                daemon=True,
                name="KiteWebSocket",
            )

            thread.start()

    def disconnect(self) -> None:
        """
        Disconnect websocket.
        """

        with self._lock:

            self._running = False

            if self._ticker:

                try:

                    self._ticker.close()

                except Exception:

                    logger.exception(
                        "WebSocket close failed."
                    )

            self._connected = False

            logger.info(
                "WebSocket disconnected."
            )

    # ---------------------------------------------------------
    # Status
    # ---------------------------------------------------------

    def is_connected(self) -> bool:
        """
        Returns websocket status.
        """

        return self._connected

    # ---------------------------------------------------------
    # Subscriptions
    # ---------------------------------------------------------

    def subscribe(
        self,
        instrument_tokens: List[int],
    ) -> None:
        """
        Subscribe to instrument tokens.
        """

        self._tokens.update(
            instrument_tokens
        )

        if self._connected:

            self.ticker.subscribe(
                instrument_tokens
            )

            self.ticker.set_mode(
                self.ticker.MODE_FULL,
                instrument_tokens,
            )

            logger.info(
                "Subscribed %d instruments.",
                len(instrument_tokens),
            )

    def unsubscribe(
        self,
        instrument_tokens: List[int],
    ) -> None:
        """
        Unsubscribe instruments.
        """

        for token in instrument_tokens:

            self._tokens.discard(token)

        if self._connected:

            self.ticker.unsubscribe(
                instrument_tokens
            )

            logger.info(
                "Unsubscribed %d instruments.",
                len(instrument_tokens),
            )

    # ---------------------------------------------------------
    # Callback Registration
    # ---------------------------------------------------------

    def unregister_callback(
    self,
    callback,
):

    self.callbacks.discard(callback)
    # ---------------------------------------------------------
    # Internal Callback Registration
    # ---------------------------------------------------------

    def _register_callbacks(self) -> None:

        self.ticker.on_connect = self._on_connect
        self.ticker.on_ticks = self._on_ticks
        self.ticker.on_close = self._on_close
        self.ticker.on_error = self._on_error
        self.ticker.on_reconnect = self._on_reconnect
        self.ticker.on_noreconnect = self._on_noreconnect

# ---------------------------------------------------------
# Tick Callback
# ---------------------------------------------------------

def _on_ticks(
    self,
    ws,
    ticks: list,
) -> None:
    """
    Internal Kite tick callback.
    Updates local cache and forwards ticks
    to all registered listeners.
    """

    if not ticks:
        return

    with self._lock:
        self._tick_count += len(ticks)
        self._last_tick_time = datetime.now()
        for tick in ticks:

            token = tick["instrument_token"]

            self.tick_cache[token] = MarketTick(
    instrument_token=token,
    ltp=tick.get("last_price", 0),
    open=tick.get("ohlc", {}).get("open", 0),
    high=tick.get("ohlc", {}).get("high", 0),
    low=tick.get("ohlc", {}).get("low", 0),
    close=tick.get("ohlc", {}).get("close", 0),
    volume=tick.get("volume_traded", 0),
    oi=tick.get("oi"),
    timestamp=tick.get("exchange_timestamp")
    or datetime.now(),
    raw=tick,
)
class MarketTick:
    instrument_token: int
    symbol: str
    ltp: float
    open: float
    high: float
    low: float
    close: float
    volume: int
    oi: int | None
    bid: list
    ask: list
    timestamp: datetime

    # Forward ticks to registered modules
    for callback in list(self.callbacks):

        try:

            callback(ticks)

        except Exception:

            logger.exception(
                "Tick callback failed."
            )


# ---------------------------------------------------------
# Connected
# ---------------------------------------------------------

def _on_connect(
    self,
    ws,
    response,
):
    """
    WebSocket connected.
    """

    self._connected = True

    logger.info(
        "WebSocket connected."
    )

    if self._tokens:

        ws.subscribe(
            list(self._tokens)
        )

        ws.set_mode(
            ws.MODE_FULL,
            list(self._tokens),
        )

        logger.info(
            "%d instruments subscribed.",
            len(self._tokens),
        )


# ---------------------------------------------------------
# Closed
# ---------------------------------------------------------

def _on_close(
    self,
    ws,
    code,
    reason,
):
    """
    Connection closed.
    """

    self._connected = False

    self._reconnect_count += 1

logger.warning(
    "Reconnect attempt %d",
    attempts,
)


# ---------------------------------------------------------
# Error
# ---------------------------------------------------------

def _on_error(
    self,
    ws,
    code,
    reason,
):
    """
    Error callback.
    """

    logger.error(
        "WebSocket Error %s | %s",
        code,
        reason,
    )


# ---------------------------------------------------------
# Reconnect
# ---------------------------------------------------------

def _on_reconnect(
    self,
    ws,
    attempts,
):
    """
    Automatic reconnect.
    """

    logger.warning(
        "Reconnect attempt %d",
        attempts,
    )


# ---------------------------------------------------------
# Reconnect Failed
# ---------------------------------------------------------

def _on_noreconnect(
    self,
    ws,
):
    """
    Kite stopped reconnecting.
    """

    self._connected = False

    logger.error(
        "WebSocket reconnection failed."
    )


# ---------------------------------------------------------
# Latest Tick
# ---------------------------------------------------------

def get_tick(
    self,
    instrument_token: int,
) -> dict:
    """
    Returns latest cached tick.
    """

    return self.tick_cache.get(
        instrument_token,
        {}
    )


# ---------------------------------------------------------
# LTP
# ---------------------------------------------------------

def get_ltp(
    self,
    instrument_token: int,
) -> float | None:
    """
    Returns latest LTP.
    """

    tick = self.get_tick(
        instrument_token
    )

    return tick.ltp if tick else None


# ---------------------------------------------------------
# OHLC
# ---------------------------------------------------------

def get_ohlc(
    self,
    instrument_token: int,
) -> dict:
    """
    Returns current OHLC.
    """

    tick = self.get_tick(
        instrument_token
    )

    if not tick:
    return {}

return {
    "open": tick.open,
    "high": tick.high,
    "low": tick.low,
    "close": tick.close,
}


# ---------------------------------------------------------
# Volume
# ---------------------------------------------------------

def get_volume(
    self,
    instrument_token: int,
) -> int:

    tick = self.get_tick(
        instrument_token
    )

    return tick.volume if tick else 0


# ---------------------------------------------------------
# Market Depth
# ---------------------------------------------------------

def get_market_depth(
    self,
    instrument_token: int,
) -> dict:

    tick = self.get_tick(
        instrument_token
    )

    return tick.get(
        "depth",
        {},
    )


# ---------------------------------------------------------
# Open Interest
# ---------------------------------------------------------

def get_oi(
    self,
    instrument_token: int,
) -> int | None:

    tick = self.get_tick(
        instrument_token
    )

    return tick.oi if tick else None


# ---------------------------------------------------------
# Cache Utilities
# ---------------------------------------------------------

def clear_cache(self) -> None:
    """
    Clears tick cache.
    """

    with self._lock:

        self.tick_cache.clear()

    logger.info(
        "Tick cache cleared."
    )


def cache_size(self) -> int:
    
    """
    Returns cached instruments.
    """

    return len(self.tick_cache)
def uptime(self):

    return round(
        time.time() - self._start_time,
        2,
    )
def last_tick_time(self):

    return self._last_tick_time 
def tick_count(self):

    return self._tick_count 
def reconnect_count(self):

    return self._reconnect_count

    def health(self):

    return {

        "connected": self.is_connected(),

        "uptime": self.uptime(),

        "tick_count": self.tick_count(),

        "reconnects": self.reconnect_count(),

        "last_tick": self.last_tick_time(),

        "cache_size": self.cache_size(),

        "subscriptions": len(self._tokens),

    }

    def shutdown(self):

    logger.info(
        "Stopping WebSocket..."
    )

    self.disconnect()

    self.callbacks.clear()

    self.tick_cache.clear()

    logger.info(
        "WebSocket stopped."
    )          