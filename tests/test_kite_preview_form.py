"""Preview inputs explain price ordering without generating broker orders."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from streamlit.testing.v1 import AppTest

from scanner.portfolio_policy import evidence_rows  # noqa: F401
from services.kite_market_preflight import PreflightInputError, preview_order

NOW = datetime(2026, 11, 11, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


class Broker:
    def health(self):
        return {"authenticated": True}

    def instruments(self, exchange):
        assert exchange == "NSE"
        return [
            {
                "exchange": "NSE",
                "segment": "NSE",
                "instrument_type": "EQ",
                "tradingsymbol": "EXAMPLE",
                "tick_size": 0.05,
                "lot_size": 1,
            }
        ]

    def quote(self, symbols):
        return {
            symbol: {"last_price": 100, "timestamp": NOW.isoformat()}
            for symbol in symbols
        }

    def place_order(self, **kwargs):
        pytest.fail("A read-only preview must never submit a broker order")


@pytest.mark.parametrize(
    "side,stop,target,ordering",
    [
        ("BUY", 100, 110, "stop price < fresh quote < target price"),
        ("BUY", 95, 100, "stop price < fresh quote < target price"),
        ("BUY", 105, 90, "stop price < fresh quote < target price"),
        ("SHORT", 100, 90, "target price < fresh quote < stop price"),
        ("SHORT", 105, 100, "target price < fresh quote < stop price"),
        ("SHORT", 95, 110, "target price < fresh quote < stop price"),
    ],
)
def test_wrong_side_or_equal_prices_show_quote_and_direction(
    side, stop, target, ordering
):
    with pytest.raises(PreflightInputError) as failure:
        preview_order(
            Broker(),
            symbol="EXAMPLE",
            side=side,
            product="MIS",
            quantity=1,
            stoploss=stop,
            target=target,
            now=NOW,
        )
    message = str(failure.value)
    assert ordering in message
    assert "Fresh quote: 100.00" in message
    assert f"entered stop: {stop:.2f}" in message
    assert f"entered target: {target:.2f}" in message
    assert "No order was submitted" in message


@pytest.mark.parametrize("side,stop,target", [("BUY", 95, 110), ("SHORT", 105, 90)])
def test_valid_preview_preserves_no_order_boundary(side, stop, target):
    result = preview_order(
        Broker(),
        symbol="EXAMPLE",
        side=side,
        product="MIS",
        quantity=1,
        stoploss=stop,
        target=target,
        now=NOW,
    )
    assert result["preview_only"] is True
    assert result["orders_submitted"] == 0
    assert result["broker_orders_allowed"] is False


def test_empty_prices_do_not_request_preview_and_explicit_prices_do(monkeypatch):
    calls = []

    class Client:
        def get_json(self, path, **kwargs):
            assert path == "/workspace/kite-session"
            return {"status": "ready", "authenticated": True}

        def post_json(self, path, payload, **kwargs):
            assert path == "/workspace/kite/order-preview"
            calls.append(payload)
            return {"preview_only": True, "orders_submitted": 0}

    monkeypatch.setattr("webapp.runtime.api_client", lambda **kwargs: Client())
    monkeypatch.setattr("webapp.runtime.admin_key_configured", lambda: True)
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "webapp/pages/live_kite.py"
    ).run(timeout=15)
    assert not app.exception
    prices = {widget.label: widget for widget in app.number_input}
    assert prices["Stop price"].value is None
    assert prices["Target price"].value is None
    next(
        widget for widget in app.button if widget.label == "Preview with fresh quote"
    ).click().run(timeout=15)
    assert not app.exception
    assert not calls
    assert any("Enter both" in warning.value for warning in app.warning)
    for label, value in (("Stop price", 95.0), ("Target price", 110.0)):
        next(widget for widget in app.number_input if widget.label == label).set_value(
            value
        )
    next(
        widget for widget in app.button if widget.label == "Preview with fresh quote"
    ).click().run(timeout=15)
    assert not app.exception
    assert len(calls) == 1
    assert calls[0]["stoploss"] == 95
    assert calls[0]["target"] == 110
