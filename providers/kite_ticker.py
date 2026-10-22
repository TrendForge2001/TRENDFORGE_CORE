"""Bounded Kite market-data streaming without the vendor's reactor dependencies.

The wire layout follows Kite Connect v3 and is compatible with KiteConnect 5.2.2.
See THIRD_PARTY_NOTICES.md for the upstream compatibility reference and license.
"""

from __future__ import annotations

import json
import logging
import socket
import struct
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager, suppress
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from websockets.sync.client import reconnect

_ENDPOINT = "wss://ws.kite.trade"
_MAX_FRAME_BYTES = 1_048_576
_WRITE_TIMEOUT = 2.0
_LOGGER = logging.getLogger(__name__)
_SOCKET_LOGGER = logging.Logger("trendforge.kite.socket")
_SOCKET_LOGGER.disabled = True


class KiteTickerError(RuntimeError):
    """A fixed streaming failure that does not contain broker credentials."""


class _NoRedirectConnection(reconnect):
    def process_redirect(self, exc: Exception) -> Exception:
        return exc


def _connect_socket(uri: str, **kwargs: Any) -> Any:
    return _NoRedirectConnection(uri, **kwargs).connect()


def _timestamp(value: int) -> datetime | None:
    try:
        return datetime.fromtimestamp(value)
    except (OSError, OverflowError, ValueError):
        return None


def validate_tokens(tokens: list[int]) -> list[int]:
    if not isinstance(tokens, list) or any(
        isinstance(token, bool) or not isinstance(token, int) or not 0 < token < 2**32
        for token in tokens
    ):
        raise ValueError("Invalid Kite instrument tokens")
    return list(dict.fromkeys(tokens))


def parse_ticks(message: bytes) -> list[dict[str, Any]]:
    """Decode a complete binary frame, rejecting partial or unsupported packets."""
    if len(message) < 2:
        return []  # Kite's one-byte heartbeat.
    if len(message) > _MAX_FRAME_BYTES:
        raise KiteTickerError("Kite websocket frame is invalid")
    count = struct.unpack_from(">H", message)[0]
    cursor = 2
    packets = []
    for _ in range(count):
        if cursor + 2 > len(message):
            raise KiteTickerError("Kite websocket frame is invalid")
        size = struct.unpack_from(">H", message, cursor)[0]
        cursor += 2
        if size not in {8, 28, 32, 44, 184} or cursor + size > len(message):
            raise KiteTickerError("Kite websocket frame is invalid")
        packets.append(message[cursor : cursor + size])
        cursor += size
    if cursor != len(message):
        raise KiteTickerError("Kite websocket frame is invalid")

    ticks = []
    for packet in packets:
        values = struct.unpack_from(">" + "I" * (len(packet) // 4), packet)
        token, price = values[:2]
        segment = token & 255
        divisor = 10_000_000 if segment == 3 else 10_000 if segment in {6, 12} else 100
        tick: dict[str, Any] = {
            "instrument_token": token,
            "tradable": segment != 9,
            "mode": "ltp" if len(packet) == 8 else "quote",
            "last_price": price / divisor,
        }
        if len(packet) == 8:
            ticks.append(tick)
            continue
        if len(packet) in {28, 32}:
            tick["ohlc"] = dict(
                zip(
                    ("high", "low", "open", "close"),
                    (v / divisor for v in values[2:6]),
                    strict=True,
                )
            )
            if len(packet) == 32:
                tick["mode"] = "full"
                tick["exchange_timestamp"] = _timestamp(values[7])
        else:
            for key, index in (
                ("last_traded_quantity", 2),
                ("volume_traded", 4),
                ("total_buy_quantity", 5),
                ("total_sell_quantity", 6),
            ):
                tick[key] = values[index]
            tick["average_traded_price"] = values[3] / divisor
            tick["ohlc"] = dict(
                zip(
                    ("open", "high", "low", "close"),
                    (v / divisor for v in values[7:11]),
                    strict=True,
                )
            )
            if len(packet) == 184:
                tick.update(
                    mode="full",
                    last_trade_time=_timestamp(values[11]),
                    oi=values[12],
                    oi_day_high=values[13],
                    oi_day_low=values[14],
                    exchange_timestamp=_timestamp(values[15]),
                )
                depth: dict[str, list[dict[str, Any]]] = {"buy": [], "sell": []}
                for index in range(10):
                    quantity, price, orders = struct.unpack_from(
                        ">IIH", packet, 64 + index * 12
                    )
                    depth["buy" if index < 5 else "sell"].append(
                        {
                            "quantity": quantity,
                            "price": price / divisor,
                            "orders": orders,
                        }
                    )
                tick["depth"] = depth
        close = tick["ohlc"]["close"]
        tick["change"] = (tick["last_price"] - close) * 100 / close if close else 0
        ticks.append(tick)
    return ticks


class KiteTicker:
    """The streaming subset used by TrendForge's legacy WebSocketService.

    Instances make no connection until ``connect``. Reconnection is capped per
    run and ``close`` interrupts backoff. TCP/TLS/HTTP opening has a timeout;
    system DNS resolution may outlast it. Shutdown joins are bounded regardless.
    Credentials are used only for the fixed TLS origin.
    """

    MODE_FULL = "full"
    MODE_QUOTE = "quote"
    MODE_LTP = "ltp"

    def __init__(
        self,
        api_key: str,
        access_token: str,
        *,
        reconnect_max_tries: int = 50,
        reconnect_max_delay: float = 60,
        connect_timeout: float = 10,
        _connector: Callable[..., Any] | None = None,
    ) -> None:
        self._uri = (
            _ENDPOINT
            + "?"
            + urlencode({"api_key": str(api_key), "access_token": str(access_token)})
        )
        self._configured = bool(api_key and access_token)
        self._connector = _connector or _connect_socket
        self._max_tries = min(50, max(0, int(reconnect_max_tries)))
        self._max_delay = min(60.0, max(0.1, float(reconnect_max_delay)))
        self._timeout = min(30.0, max(1.0, float(connect_timeout)))
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._subscription_lock = threading.Lock()
        self._io_threads: set[threading.Thread] = set()
        self._thread: threading.Thread | None = None
        self._connection: Any = None
        self._running = False
        self._subscriptions: dict[int, str] = {}
        self.on_connect: Callable[..., None] | None = None
        self.on_ticks: Callable[..., None] | None = None
        self.on_close: Callable[..., None] | None = None
        self.on_error: Callable[..., None] | None = None
        self.on_reconnect: Callable[..., None] | None = None
        self.on_noreconnect: Callable[..., None] | None = None

    def _emit(self, name: str, *args: Any) -> None:
        callback = getattr(self, name)
        if callback is not None and not self._stop.is_set():
            try:
                callback(self, *args)
            except Exception:
                _LOGGER.warning("Kite websocket callback failed")

    def is_connected(self) -> bool:
        with self._lock:
            return self._connection is not None and not self._stop.is_set()

    def connect(self, threaded: bool = False) -> None:
        if not self._configured:
            raise KiteTickerError("Kite websocket is not configured")
        with self._lock:
            if self._running:
                return
            self._stop.clear()
            self._running = True
            if threaded:
                self._thread = threading.Thread(
                    target=self._run, name="KiteMarketData", daemon=True
                )
                self._thread.start()
                return
        self._run()

    def _io_worker(self, action: Callable[[], None]) -> threading.Thread:
        def run() -> None:
            try:
                action()
            finally:
                with self._lock:
                    self._io_threads.discard(threading.current_thread())

        with self._lock:
            worker = threading.Thread(target=run, name="KiteSocketIO", daemon=True)
            self._io_threads.add(worker)
            try:
                worker.start()
            except Exception:
                self._io_threads.discard(worker)
                raise KiteTickerError("Kite websocket unavailable") from None
            return worker

    def _abort(self, connection: Any) -> None:
        # websockets' graceful close takes the same internal protocol mutex as
        # sendall. Abort its OS socket first, independently of that mutex, so a
        # stalled write cannot trap shutdown before close_timeout starts.
        with self._lock:
            if self._connection is connection:
                self._connection = None
        transport = getattr(connection, "socket", None)
        if transport is not None:
            with suppress(Exception):
                transport.shutdown(socket.SHUT_RDWR)
            with suppress(Exception):
                transport.close()

        def finish() -> None:
            with suppress(Exception):
                connection.close()

        self._io_worker(finish)

    def _send(self, payload: dict[str, Any]) -> None:
        # Subscription intent and IO are serialized by _subscription_lock.
        # Shutdown uses only _lock; no caller may hold it during socket IO.
        done = threading.Event()
        failed = threading.Event()
        with self._lock:
            connection = self._connection
            if connection is None or self._stop.is_set():
                return

            def transmit() -> None:
                try:
                    connection.send(json.dumps(payload))
                except Exception:
                    failed.set()
                finally:
                    done.set()

            self._io_worker(transmit)
        if not done.wait(_WRITE_TIMEOUT) or failed.is_set():
            self._abort(connection)
            raise KiteTickerError("Kite websocket subscription unavailable") from None

    @contextmanager
    def _subscription_change(self):
        if not self._subscription_lock.acquire(timeout=_WRITE_TIMEOUT):
            raise KiteTickerError("Kite websocket subscription unavailable")
        try:
            yield
        finally:
            self._subscription_lock.release()

    @property
    def subscribed_tokens(self) -> dict[int, str]:
        with self._lock:
            return dict(self._subscriptions)

    def subscribe(
        self, instrument_tokens: list[int], *, mode: str | None = None
    ) -> bool:
        if mode is not None and mode not in {
            self.MODE_FULL,
            self.MODE_QUOTE,
            self.MODE_LTP,
        }:
            raise ValueError("Invalid Kite streaming mode")
        tokens = validate_tokens(instrument_tokens)
        with self._subscription_change():
            with self._lock:
                if len(set(self._subscriptions) | set(tokens)) > 3000:
                    raise ValueError("Kite subscription limit exceeded")
                for token in tokens:
                    if mode is None:
                        self._subscriptions.setdefault(token, self.MODE_QUOTE)
                    else:
                        self._subscriptions[token] = mode
            if tokens:
                self._send({"a": "subscribe", "v": tokens})
                if mode is not None:
                    self._send({"a": "mode", "v": [mode, tokens]})
        return True

    def unsubscribe(self, instrument_tokens: list[int]) -> bool:
        tokens = validate_tokens(instrument_tokens)
        with self._subscription_change():
            with self._lock:
                for token in tokens:
                    self._subscriptions.pop(token, None)
            if tokens:
                self._send({"a": "unsubscribe", "v": tokens})
        return True

    def set_mode(self, mode: str, instrument_tokens: list[int]) -> bool:
        if mode not in {self.MODE_FULL, self.MODE_QUOTE, self.MODE_LTP}:
            raise ValueError("Invalid Kite streaming mode")
        tokens = validate_tokens(instrument_tokens)
        with self._subscription_change():
            with self._lock:
                if any(token not in self._subscriptions for token in tokens):
                    raise ValueError("Kite mode requires a subscribed instrument")
                for token in tokens:
                    self._subscriptions[token] = mode
            if tokens:
                self._send({"a": "mode", "v": [mode, tokens]})
        return True

    def _restore(self) -> None:
        with self._subscription_change():
            with self._lock:
                groups: dict[str, list[int]] = {}
                for token, mode in self._subscriptions.items():
                    groups.setdefault(mode, []).append(token)
            for mode, tokens in groups.items():
                self._send({"a": "subscribe", "v": tokens})
                self._send({"a": "mode", "v": [mode, tokens]})

    def _message(self, message: object) -> None:
        if isinstance(message, bytes):
            ticks = parse_ticks(message)
            if ticks:
                self._emit("on_ticks", ticks)
        elif isinstance(message, str):
            if len(message.encode("utf-8")) > _MAX_FRAME_BYTES:
                raise KiteTickerError("Kite websocket frame is invalid")
            try:
                payload = json.loads(message)
            except ValueError:
                raise KiteTickerError("Kite websocket frame is invalid") from None
            if not isinstance(payload, dict):
                raise KiteTickerError("Kite websocket frame is invalid")
            if payload.get("type") == "error":
                self._emit("on_error", 0, "Kite websocket server rejected a request")
        else:
            raise KiteTickerError("Kite websocket frame is invalid")

    def _run(self) -> None:
        reconnects = 0
        try:
            while not self._stop.is_set():
                try:
                    with self._connector(
                        self._uri,
                        additional_headers={"X-Kite-Version": "3"},
                        proxy=None,
                        compression=None,
                        open_timeout=self._timeout,
                        close_timeout=2,
                        ping_interval=20,
                        ping_timeout=20,
                        max_size=_MAX_FRAME_BYTES,
                        max_queue=16,
                        logger=_SOCKET_LOGGER,
                    ) as connection:
                        if self._stop.is_set():
                            break
                        with self._lock:
                            self._connection = connection
                        self._restore()
                        self._emit("on_connect", None)
                        while not self._stop.is_set():
                            try:
                                message = connection.recv(timeout=1)
                            except TimeoutError:
                                continue
                            self._message(message)
                except Exception:
                    if not self._stop.is_set():
                        self._emit("on_error", 0, "Kite websocket unavailable")
                finally:
                    with self._lock:
                        self._connection = None
                if self._stop.is_set():
                    break
                self._emit("on_close", 1006, "Kite websocket disconnected")
                if reconnects >= self._max_tries:
                    self._emit("on_noreconnect")
                    break
                reconnects += 1
                self._emit("on_reconnect", reconnects)
                if self._stop.wait(min(2 ** min(reconnects, 6), self._max_delay)):
                    break
        finally:
            with self._lock:
                self._running = False
                self._connection = None

    def close(self, code: int | None = None, reason: str | None = None) -> None:
        self._stop.set()
        with self._lock:
            connection, thread = self._connection, self._thread
            self._connection = None
        if connection is not None:
            self._abort(connection)
        deadline = time.monotonic() + self._timeout + 3
        with self._lock:
            workers = list(self._io_threads)
        for worker in [*workers, thread]:
            if worker is not None and worker is not threading.current_thread():
                worker.join(timeout=max(0.0, deadline - time.monotonic()))
