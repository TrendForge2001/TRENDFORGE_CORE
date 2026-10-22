"""Shared opt-in boundary for live broker mutations and SDK access."""

from __future__ import annotations

import os
from collections.abc import Callable
from types import MethodType
from typing import Any

_DISABLED_MESSAGE = (
    "Live trading disabled: broker order operations require explicit opt-in"
)
_READ_AND_SESSION_METHODS = frozenset(
    {
        "profile",
        "margins",
        "holdings",
        "positions",
        "orders",
        "trades",
        "instruments",
        "quote",
        "ltp",
        "ohlc",
        "historical_data",
        "order_history",
        "order_trades",
        "get_gtts",
        "login_url",
        "generate_session",
        "set_access_token",
        "invalidate_access_token",
    }
)
_RETRYABLE_READ_METHODS = ("quote", "ltp", "historical_data")


class LiveTradingDisabled(RuntimeError):
    """The instance and current runtime have not both opted into live writes."""


def require_live_trading(instance_enabled: bool) -> None:
    """Require explicit instance consent and a current runtime opt-in."""
    runtime_enabled = os.getenv(
        "TRENDFORGE_LIVE_TRADING_ENABLED", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}
    if instance_enabled is not True or not runtime_enabled:
        raise LiveTradingDisabled(_DISABLED_MESSAGE)


class GuardedKiteClient:
    """Expose known SDK operations, checking every broker mutation invocation."""

    __slots__ = ("__client", "__require_live")

    def __init__(self, client: Any, require_live: Callable[[], None]) -> None:
        self.__client = client
        self.__require_live = require_live

    def __getattr__(self, name: str) -> Any:
        if name not in _READ_AND_SESSION_METHODS:
            raise AttributeError("Broker SDK attribute is not exposed")
        return getattr(self.__client, name)

    def place_order(self, *args: Any, **kwargs: Any) -> Any:
        self.__require_live()
        return self.__client.place_order(*args, **kwargs)

    def modify_order(self, *args: Any, **kwargs: Any) -> Any:
        self.__require_live()
        return self.__client.modify_order(*args, **kwargs)

    def cancel_order(self, *args: Any, **kwargs: Any) -> Any:
        self.__require_live()
        return self.__client.cancel_order(*args, **kwargs)

    def is_retryable_read(self, func: Any) -> bool:
        """Recognize this client's actual read callables without name matching."""
        if not callable(func):
            return False
        for name in _RETRYABLE_READ_METHODS:
            method = getattr(self.__client, name, None)
            if not callable(method):
                continue
            if func is method:
                return True
            # Python creates a fresh bound-method object on each lookup. Compare
            # its actual receiver/function, never a callable's overloaded __eq__.
            if (
                isinstance(func, MethodType)
                and isinstance(method, MethodType)
                and func.__self__ is method.__self__
                and func.__func__ is method.__func__
            ):
                return True
        return False


__all__ = ["GuardedKiteClient", "LiveTradingDisabled", "require_live_trading"]
