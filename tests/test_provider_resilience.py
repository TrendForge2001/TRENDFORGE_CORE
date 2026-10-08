from __future__ import annotations

import pytest

from providers.nse_provider import NSEProvider


def fresh_nse_provider() -> NSEProvider:
    provider = object.__new__(NSEProvider)
    NSEProvider.__init__(provider)
    return provider


class FakeResponse:
    def __init__(
        self,
        *,
        status_code=200,
        text="{}",
        content_type="application/json",
        payload=None,
    ):
        self.status_code = status_code
        self.text = text
        self.headers = {"Content-Type": content_type}
        self._payload = payload if payload is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_nse_rejects_non_json_response_with_diagnostic_context():
    provider = fresh_nse_provider()
    provider._session_ready = True

    response = FakeResponse(
        text="<html>challenge</html>",
        content_type="text/html",
    )

    with pytest.raises(RuntimeError, match="non-JSON response"):
        provider._decode_json_response(response)

    assert provider._session_ready is False


def test_nse_429_enters_provider_cooldown():
    provider = fresh_nse_provider()

    response = FakeResponse(
        status_code=429,
        text="Too Many Requests",
        content_type="text/plain",
    )

    with pytest.raises(RuntimeError, match="HTTP 429"):
        provider._decode_json_response(response)

    assert provider._cooldown_remaining() > 0
    assert provider.health()["status"] == "degraded"
    assert provider.health()["runtime_status"] == "rate_limited"


def test_nse_corporate_actions_use_scoped_current_endpoint_params():
    provider = fresh_nse_provider()
    captured = {}

    def fake_get(endpoint, params=None):
        captured["endpoint"] = endpoint
        captured["params"] = params
        return []

    provider._get = fake_get
    result = provider.corporate_actions("LUPIN", days=90)

    assert result == []
    assert captured["endpoint"] == "/api/corporates-corporateActions"
    assert captured["params"]["index"] == "equities"
    assert captured["params"]["symbol"] == "LUPIN"
    assert "from_date" in captured["params"]
    assert "to_date" in captured["params"]


def test_nse_large_deals_use_combined_historical_endpoint():
    provider = fresh_nse_provider()
    calls = []

    def fake_get(endpoint, params=None):
        calls.append((endpoint, dict(params or {})))
        return {"data": []}

    provider._get = fake_get

    provider.bulk_deals(days=30)
    provider.block_deals(days=30)

    assert calls[0][0] == "/api/historicalOR/bulk-block-short-deals"
    assert calls[0][1]["optionType"] == "bulk_deals"
    assert calls[1][0] == "/api/historicalOR/bulk-block-short-deals"
    assert calls[1][1]["optionType"] == "block_deals"
    assert "from" in calls[0][1]
    assert "to" in calls[0][1]
