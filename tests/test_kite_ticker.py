"""Exercise streaming wire packets and lifecycle with fake sockets only."""

from __future__ import annotations

import json
import logging
import secrets
import struct
import threading
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

import pytest
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response

import api.websocket_service as service_module
from providers import kite_ticker
from providers.kite_ticker import KiteTicker, KiteTickerError, parse_ticks


def frame(*packets):
    return struct.pack(">H", len(packets)) + b"".join(
        struct.pack(">H", len(packet)) + packet for packet in packets
    )


def quote_packet(size, segment=1):
    values = [
        256 + segment,
        12_345,
        2,
        12_300,
        101,
        102,
        103,
        12_000,
        13_000,
        11_000,
        12_100,
    ]
    if size in {28, 32}:
        values = [256 + segment, 12_345, 13_000, 11_000, 12_000, 12_100, 245]
        if size == 32:
            values.append(1_700_000_000)
    elif size == 184:
        values.extend([1_700_000_001, 91, 92, 90, 1_700_000_002])
    packet = struct.pack(">" + "I" * len(values), *values)
    if size == 184:
        packet += b"".join(
            struct.pack(">IIH2x", index + 1, 12_000 + index, 10 + index)
            for index in range(10)
        )
    return packet


@pytest.mark.parametrize(
    "segment,divisor", [(1, 100), (3, 10_000_000), (6, 10_000), (12, 10_000), (9, 100)]
)
def test_ltp_precision_and_index_tradability(segment, divisor):
    token, price = 256 + segment, 123_456_789
    ticks = parse_ticks(frame(struct.pack(">II", token, price)))
    assert ticks == [
        {
            "instrument_token": token,
            "last_price": price / divisor,
            "tradable": segment != 9,
            "mode": "ltp",
        }
    ]


@pytest.mark.parametrize("size", [28, 32, 44, 184])
def test_quote_and_full_packets_preserve_market_fields(size):
    tick = parse_ticks(frame(quote_packet(size, 9 if size in {28, 32} else 1)))[0]
    assert tick["last_price"] == 123.45
    assert tick["ohlc"] == {"open": 120, "high": 130, "low": 110, "close": 121}
    assert tick["change"] == pytest.approx((123.45 - 121) * 100 / 121)
    assert tick["mode"] == ("full" if size in {32, 184} else "quote")
    if size in {44, 184}:
        assert tick["volume_traded"] == 101
        assert tick["last_traded_quantity"] == 2
        assert tick["average_traded_price"] == 123
        assert tick["total_buy_quantity"] == 102
        assert tick["total_sell_quantity"] == 103
    if size == 32:
        assert tick["exchange_timestamp"] == datetime.fromtimestamp(1_700_000_000)
    if size == 184:
        assert (tick["oi"], tick["oi_day_high"], tick["oi_day_low"]) == (91, 92, 90)
        assert tick["last_trade_time"] == datetime.fromtimestamp(1_700_000_001)
        assert tick["exchange_timestamp"] == datetime.fromtimestamp(1_700_000_002)
        assert tick["depth"]["buy"][0] == {"quantity": 1, "price": 120, "orders": 10}
        assert tick["depth"]["sell"][-1] == {
            "quantity": 10,
            "price": 120.09,
            "orders": 19,
        }
        assert len(tick["depth"]["buy"]) == len(tick["depth"]["sell"]) == 5


def test_heartbeat_and_multiple_packets():
    assert parse_ticks(b"\x00") == []
    assert parse_ticks(b"\x00\x00") == []
    data = frame(struct.pack(">II", 257, 100), quote_packet(184))
    assert len(parse_ticks(data)) == 2


@pytest.mark.parametrize(
    "message",
    [
        b"\x00\x01",
        b"\x00\x01\x00",
        b"\x00\x01\x00\x08\x00",
        frame(b"unsupported"),
        frame(struct.pack(">II", 257, 100)) + b"extra",
        frame(struct.pack(">II", 257, 100), b"broken"),
        b"x" * 1_048_577,
    ],
)
def test_invalid_frames_fail_before_emitting_partial_ticks(message):
    with pytest.raises(KiteTickerError, match="frame is invalid"):
        parse_ticks(message)


class FakeSocket:
    def __init__(self, messages=()):
        self.messages = list(messages)
        self.sent = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def send(self, value):
        self.sent.append(json.loads(value))

    def recv(self, *, timeout):
        assert timeout == 1
        message = self.messages.pop(0)
        if isinstance(message, Exception):
            raise message
        return message

    def close(self):
        self.closed = True


def ticker(connector, **kwargs):
    return KiteTicker(
        secrets.token_hex(12), secrets.token_hex(16), _connector=connector, **kwargs
    )


def test_subscription_restore_callback_contract_and_secure_connector_options():
    calls = []
    socket = FakeSocket([frame(quote_packet(184))])

    def connector(uri, **kwargs):
        calls.append((uri, kwargs))
        return socket

    client = ticker(connector)
    client.subscribe([257])
    client.set_mode(client.MODE_FULL, [257])
    events = []
    client.on_connect = lambda ws, response: events.append((ws, response))

    def ticks(ws, values):
        assert ws is client and values[0]["oi"] == 91
        events.append("ticks")
        ws.close()

    client.on_ticks = ticks
    client.connect()
    assert events == [(client, None), "ticks"]
    assert socket.sent == [
        {"a": "subscribe", "v": [257]},
        {"a": "mode", "v": ["full", [257]]},
    ]
    target, options = calls[0]
    parsed = urlsplit(target)
    assert (parsed.scheme, parsed.netloc, parsed.path) == ("wss", "ws.kite.trade", "")
    assert set(parse_qs(parsed.query)) == {"api_key", "access_token"}
    assert options["additional_headers"] == {"X-Kite-Version": "3"}
    assert options["proxy"] is options["compression"] is None
    assert options["logger"].disabled
    assert options["open_timeout"] <= 30 and options["close_timeout"] == 2
    assert options["max_size"] == 1_048_576
    assert socket.closed and not client.is_connected()


def test_reconnect_restores_desired_modes_and_disconnected_unsubscribe():
    first = FakeSocket([OSError("Network failed")])
    second = FakeSocket([frame(struct.pack(">II", 257, 100))])
    sockets = iter([first, second])
    client = ticker(lambda *args, **kwargs: next(sockets), reconnect_max_delay=0.1)
    client.subscribe([257, 258])
    client.set_mode(client.MODE_FULL, [257])
    client.unsubscribe([258])
    attempts = []
    client.on_reconnect = lambda ws, attempt: attempts.append(attempt)
    client.on_ticks = lambda ws, ticks: ws.close()
    client.connect()
    expected = [{"a": "subscribe", "v": [257]}, {"a": "mode", "v": ["full", [257]]}]
    assert first.sent == second.sent == expected
    assert attempts == [1]
    assert first.closed and second.closed


def test_retry_budget_and_stop_during_backoff_are_bounded_and_redacted(caplog):
    calls = []
    client = None

    def failure(uri, **kwargs):
        calls.append(uri)
        raise OSError(uri)

    client = ticker(failure, reconnect_max_tries=1, reconnect_max_delay=0.1)
    errors, exhausted = [], []
    client.on_error = lambda ws, code, reason: errors.append((code, reason))
    client.on_noreconnect = lambda ws: exhausted.append(ws)
    with caplog.at_level(logging.DEBUG):
        client.connect()
    assert len(calls) == 2 and exhausted == [client]
    assert errors == [(0, "Kite websocket unavailable")] * 2
    assert client._uri not in caplog.text

    calls.clear()
    client = ticker(failure, reconnect_max_tries=50)
    client.on_reconnect = lambda ws, attempt: ws.close()
    client.connect()
    assert len(calls) == 1


def test_duplicate_connect_and_close_during_pending_handshake_do_not_rearm_callbacks():
    entered, release = threading.Event(), threading.Event()
    socket = FakeSocket()
    calls = []

    def connector(*args, **kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(2)
        return socket

    client = ticker(connector, connect_timeout=1)
    connected = []
    client.on_connect = lambda *args: connected.append(1)
    client.connect(threaded=True)
    assert entered.wait(1)
    client.connect(threaded=True)
    releaser = threading.Thread(target=lambda: (client._stop.wait(1), release.set()))
    releaser.start()
    client.close()
    releaser.join(1)
    assert len(calls) == 1 and connected == [] and socket.closed
    assert client._thread is not None and not client._thread.is_alive()


@pytest.mark.parametrize("wrapper", ["ticker", "service"])
def test_shutdown_aborts_a_stalled_send_without_waiting_for_protocol_mutex(wrapper):
    entered, release, aborted = threading.Event(), threading.Event(), threading.Event()
    protocol = threading.Lock()

    class RawTransport:
        def shutdown(self, how):
            aborted.set()
            release.set()

        def close(self):
            release.set()

    class BlockedSocket(FakeSocket):
        socket = RawTransport()

        def send(self, value):
            with protocol:
                entered.set()
                assert release.wait(3)
                raise OSError("Connection aborted")

        def close(self):
            # Model websockets 17.2: graceful close first needs the very mutex
            # held by sendall; only the independent OS abort can free it.
            with protocol:
                self.closed = True

    socket = BlockedSocket()
    client = ticker(lambda *args, **kwargs: socket, connect_timeout=1)
    client._connection = socket
    target = client
    if wrapper == "service":
        target = service_module.WebSocketService(
            secrets.token_hex(12), secrets.token_hex(16)
        )
        target._ticker = client
        target._running = target._connected = True
    failures = []

    def send():
        try:
            target.subscribe([257])
        except KiteTickerError as exc:
            failures.append(str(exc))

    sender = threading.Thread(target=send)
    sender.start()
    assert entered.wait(1)
    stopped = threading.Event()

    def close():
        if wrapper == "service":
            target.disconnect()
        else:
            target.close()
        stopped.set()

    closer = threading.Thread(target=close)
    closer.start()
    try:
        assert stopped.wait(1), "Shutdown waited for the stalled write"
        assert aborted.is_set()
    finally:
        release.set()
        sender.join(2)
        closer.join(2)
    assert not sender.is_alive() and not closer.is_alive()
    assert failures == ["Kite websocket subscription unavailable"]
    assert socket.closed and not client.is_connected()


def test_subscription_intent_and_wire_commands_keep_the_same_order(monkeypatch):
    entered, release, removing_started, removed = (threading.Event() for _ in range(4))
    socket = FakeSocket()
    client = ticker(lambda *args, **kwargs: socket)
    client._connection = socket
    send = client._send

    def pause_before_write(payload):
        # Pause after desired-state admission but BEFORE entering transport
        # serialization. A lock protecting only socket.send cannot stop the
        # opposite mutation from overtaking this command here.
        if payload["a"] == "subscribe":
            entered.set()
            assert release.wait(2)
        send(payload)

    monkeypatch.setattr(client, "_send", pause_before_write)

    def remove():
        removing_started.set()
        client.unsubscribe([257])
        removed.set()

    adding = threading.Thread(target=lambda: client.subscribe([257]))
    removing = threading.Thread(target=remove)
    adding.start()
    assert entered.wait(1)
    removing.start()
    assert removing_started.wait(1)
    try:
        assert not removed.wait(0.1), "Unsubscribe overtook an admitted subscribe"
    finally:
        release.set()
        adding.join(1)
        removing.join(1)
    assert not adding.is_alive() and not removing.is_alive()
    assert socket.sent == [
        {"a": "subscribe", "v": [257]},
        {"a": "unsubscribe", "v": [257]},
    ]
    assert client.subscribed_tokens == {}
    client.close()


def test_failed_service_subscribe_retains_full_mode_for_reconnection(monkeypatch):
    connected, tick_received = threading.Event(), threading.Event()

    class LiveSocket(FakeSocket):
        def __init__(self, *, fail_send=False, packets=()):
            super().__init__(packets)
            self.fail_send = fail_send
            self.closed_event = threading.Event()

        def send(self, value):
            if self.fail_send:
                raise OSError("Subscription delivery failed")
            super().send(value)

        def recv(self, *, timeout):
            if self.messages:
                return self.messages.pop(0)
            if not self.closed_event.wait(timeout):
                raise TimeoutError
            raise OSError("Connection closed")

        def close(self):
            self.closed = True
            self.closed_event.set()

    first = LiveSocket(fail_send=True)
    second = LiveSocket(packets=[frame(quote_packet(184))])
    sockets = iter([first, second])
    client = ticker(lambda *args, **kwargs: next(sockets), reconnect_max_delay=0.1)
    monkeypatch.setattr(service_module, "KiteTicker", lambda *args: client)
    service = service_module.WebSocketService(
        secrets.token_hex(12), secrets.token_hex(16)
    )
    service.register_callback(lambda ticks: tick_received.set())
    original_connect = service._on_connect

    def mark_connected(ws, response):
        original_connect(ws, response)
        connected.set()

    service._on_connect = mark_connected
    service.connect()
    assert connected.wait(1)
    try:
        with pytest.raises(KiteTickerError):
            service.subscribe([257])
        assert service.health()["subscriptions"] == 1
        assert client.subscribed_tokens == {257: "full"}
        assert tick_received.wait(1)
        assert second.sent == [
            {"a": "subscribe", "v": [257]},
            {"a": "mode", "v": ["full", [257]]},
        ]
        assert service.get_oi(257) == 91
    finally:
        service.disconnect()


def test_redirects_are_rejected_without_following_new_location():
    error = InvalidStatus(
        Response(302, "Found", Headers({"Location": "wss://other.invalid/"}))
    )
    connector = kite_ticker._NoRedirectConnection("wss://ws.kite.trade")
    assert connector.process_redirect(error) is error


@pytest.mark.parametrize("tokens", [[True], [0], [-1], [2**32], ["257"], (257,)])
def test_invalid_tokens_cannot_poison_disconnected_subscription_state(tokens):
    client = ticker(lambda *args, **kwargs: None)
    service = service_module.WebSocketService(
        secrets.token_hex(12), secrets.token_hex(16)
    )
    for wrapper in (client, service):
        with pytest.raises(ValueError, match="Invalid Kite instrument tokens"):
            wrapper.subscribe(tokens)
    assert client._subscriptions == {}
    assert service._tokens == set()


def test_send_and_callback_failures_do_not_reveal_credentials(caplog):
    socket = FakeSocket([frame(struct.pack(">II", 257, 100))])
    client = ticker(lambda *args, **kwargs: socket)

    def broken_callback(*args):
        raise OSError(client._uri)

    client.on_connect = broken_callback
    client.on_ticks = lambda ws, values: ws.close()
    with caplog.at_level(logging.DEBUG):
        client.connect()
    assert "callback failed" in caplog.text and client._uri not in caplog.text

    class BrokenSend(FakeSocket):
        def send(self, value):
            raise OSError(client._uri)

    client = ticker(lambda *args, **kwargs: BrokenSend())
    errors = []

    def subscribe(ws, response):
        with pytest.raises(KiteTickerError) as raised:
            ws.subscribe([257])
        assert raised.value.__suppress_context__
        errors.append(str(raised.value))
        ws.close()

    client.on_connect = subscribe
    client.connect()
    assert errors == ["Kite websocket subscription unavailable"]
    assert client._uri not in caplog.text + json.dumps(errors)


def test_malformed_and_server_error_messages_never_forward_raw_reasons(caplog):
    value = secrets.token_hex(16)
    socket = FakeSocket([json.dumps({"type": "error", "data": value}), b"\x00\x01"])
    client = ticker(lambda *args, **kwargs: socket, reconnect_max_tries=0)
    errors, ticks = [], []
    client.on_error = lambda ws, code, reason: errors.append(reason)
    client.on_ticks = lambda ws, items: ticks.extend(items)
    client.connect()
    assert ticks == []
    assert errors == [
        "Kite websocket server rejected a request",
        "Kite websocket unavailable",
    ]
    assert value not in caplog.text + json.dumps(errors)


def test_legacy_service_keeps_tick_reads_and_ignores_stale_callbacks(
    monkeypatch, caplog
):
    instances = []

    class FakeTicker:
        MODE_FULL = "full"

        def __init__(self, *args):
            self.sent = []
            self.connections = 0
            instances.append(self)

        def subscribe(self, tokens, *, mode=None):
            self.sent.append(("subscribe", tokens))
            if mode is not None:
                self.set_mode(mode, tokens)

        def unsubscribe(self, tokens):
            self.sent.append(("unsubscribe", tokens))

        def set_mode(self, mode, tokens):
            self.sent.append((mode, tokens))

        def connect(self, *, threaded):
            assert threaded
            self.connections += 1
            self.on_connect(self, None)

        def close(self):
            pass

    monkeypatch.setattr(service_module, "KiteTicker", FakeTicker)
    service = service_module.WebSocketService(
        secrets.token_hex(12), secrets.token_hex(16)
    )
    service.subscribe([257])
    service.connect()
    service.connect()
    first = instances[0]
    assert first.connections == 1
    assert first.sent == [("subscribe", [257]), ("full", [257])]
    first.on_ticks(first, parse_ticks(frame(quote_packet(184))))
    assert service.get_ltp(257) == 123.45
    assert service.get_oi(257) == 91
    assert service.get_volume(257) == 101
    assert len(service.get_market_depth(257)["buy"]) == 5
    service.disconnect()
    service.unsubscribe([257])
    assert first.sent[-1] == ("unsubscribe", [257])
    first.on_connect(first, None)
    assert not service.is_connected()
    service.connect()
    first.on_close(first, 0, "discarded")
    assert service.is_connected()
    sentinel = secrets.token_hex(16)
    service._on_error(first, 0, sentinel)
    assert sentinel not in caplog.text
    service.shutdown()
