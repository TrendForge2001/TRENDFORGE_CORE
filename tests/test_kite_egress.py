"""Network setup contracts: fake transports only, never a broker order."""

import json
import secrets

import pytest
import requests

from providers.kite_egress import IPS_ENV, PROXY_ENV, load_kite_egress
from providers.kite_errors import NetworkException
from providers.kite_rest_client import KiteRESTClient
from services.kite_network_readiness import PROBE_URLS, kite_network_readiness


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    monkeypatch.delenv(PROXY_ENV, raising=False)
    monkeypatch.delenv(IPS_ENV, raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("Network tests must use fake transports")

    monkeypatch.setattr(requests.Session, "request", forbidden)


@pytest.fixture
def proxy_url():
    return "https://operator:" + secrets.token_hex(18) + "@proxy.invalid:8443"


class Reply:
    status_code = 200
    content = b'{"status":"success","data":{"broker":"ZERODHA"}}'
    headers = {"Content-Type": "application/json"}

    def __init__(self, body=b"8.8.8.8\n"):
        self.body = body

    def json(self):
        return json.loads(self.content)

    def iter_content(self, chunk_size):
        yield self.body

    def close(self):
        pass


class Transport:
    def __init__(self, calls, reply=None):
        self.calls = calls
        self.reply = reply or Reply()

    def request(self, method, url, **options):
        self.calls.append((method, url, options))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

    def close(self):
        pass


def test_default_preserves_existing_network_configuration():
    configuration = load_kite_egress({})
    assert configuration.request_options() == {}
    assert configuration.expected_ips == ()
    assert configuration.public_configuration()["proxy_configured"] is False


@pytest.mark.parametrize(
    "bad",
    [
        "socks5://proxy.invalid:1080",
        "http://",
        "https://proxy.invalid/path",
        "https://proxy.invalid?key=value",
        "https://proxy.invalid#fragment",
        "https://proxy.invalid:70000",
        "https://proxy.invalid:0",
        "https://proxy.invalid/%0A",
    ],
)
def test_invalid_proxy_fails_closed_without_echoing_value(bad):
    with pytest.raises(ValueError, match="Kite proxy configuration is invalid") as err:
        load_kite_egress({PROXY_ENV: bad})
    assert bad not in str(err.value)


def test_control_characters_in_generated_proxy_credentials_are_rejected(proxy_url):
    bad = proxy_url.replace("operator:", "operator:%0D")
    with pytest.raises(ValueError, match="Kite proxy configuration is invalid") as err:
        load_kite_egress({PROXY_ENV: bad})
    assert proxy_url not in str(err.value)


@pytest.mark.parametrize(
    "bad", ["8.8.8.0/24", "127.0.0.1", "not-an-ip", "8.8.8.8 1.1.1.1 9.9.9.9"]
)
def test_whitelist_configuration_requires_at_most_two_public_literals(bad):
    with pytest.raises(ValueError, match="at most two public"):
        load_kite_egress({IPS_ENV: bad})


def test_ipv4_and_ipv6_are_canonicalized_without_exposing_proxy(proxy_url):
    configuration = load_kite_egress(
        {PROXY_ENV: proxy_url, IPS_ENV: "8.8.8.8,2606:4700:4700::1111 8.8.8.8"}
    )
    assert configuration.expected_ips == ("8.8.8.8", "2606:4700:4700::1111")
    assert proxy_url not in repr(configuration)
    assert proxy_url not in json.dumps(configuration.public_configuration())


def test_broker_requests_use_explicit_proxy_and_tls_verification(
    monkeypatch, proxy_url
):
    monkeypatch.setenv(PROXY_ENV, proxy_url)
    calls = []
    client = KiteRESTClient(
        api_key=secrets.token_hex(12),
        access_token=secrets.token_hex(18),
        session=Transport(calls),
    )
    assert client.profile() == {"broker": "ZERODHA"}
    assert calls[0][0:2] == ("GET", "https://api.kite.trade/user/profile")
    assert calls[0][2]["proxies"] == {"https": proxy_url}
    assert calls[0][2]["verify"] is True
    assert calls[0][2]["allow_redirects"] is False


def test_failed_proxy_never_retries_direct_or_leaks_password(monkeypatch, proxy_url):
    monkeypatch.setenv(PROXY_ENV, proxy_url)
    calls = []
    client = KiteRESTClient(
        api_key=secrets.token_hex(12),
        access_token=secrets.token_hex(18),
        session=Transport(calls, requests.exceptions.ProxyError(proxy_url)),
    )
    with pytest.raises(NetworkException) as err:
        client.profile()
    assert err.value.reason == "proxy_failure"
    assert proxy_url not in str(err.value)
    assert len(calls) == 1
    assert calls[0][2]["proxies"] == {"https": proxy_url}


def test_unconfigured_check_never_attempts_network():
    def forbidden():
        raise AssertionError("No probe is permitted before route configuration")

    report = kite_network_readiness(probe=True, session_factory=forbidden)
    assert report["status"] == "fixed_egress_not_configured"
    assert report["orders_submitted"] == 0


def test_configuration_only_check_never_attempts_network(monkeypatch, proxy_url):
    monkeypatch.setenv(PROXY_ENV, proxy_url)

    def forbidden():
        raise AssertionError("Probe was not requested")

    report = kite_network_readiness(session_factory=forbidden)
    assert report["status"] == "not_probed"


def test_read_only_probes_never_carry_broker_credentials(monkeypatch, proxy_url):
    monkeypatch.setenv(PROXY_ENV, proxy_url)
    monkeypatch.setenv(IPS_ENV, "8.8.8.8")
    calls = []
    report = kite_network_readiness(
        probe=True, session_factory=lambda: Transport(calls)
    )
    assert report["status"] == "observed_ips_match_configuration"
    assert report["observed_ips"] == ["8.8.8.8"]
    assert report["samples_completed"] == 3
    assert report["broker_whitelist_verified"] is False
    assert report["broker_orders_allowed"] is False
    assert report["orders_submitted"] == 0
    assert proxy_url not in json.dumps(report)
    assert [call[1] for call in calls] == list(PROBE_URLS)
    for method, _, options in calls:
        assert method == "GET"
        assert options["headers"] == {"Accept": "text/plain"}
        assert options["proxies"] == {"https": proxy_url}
        assert options["verify"] is True
        assert options["allow_redirects"] is False


@pytest.mark.parametrize(
    "expected,status",
    [("", "expected_ips_missing"), ("1.1.1.1", "observed_ip_mismatch")],
)
def test_observed_ip_cannot_approve_absent_or_wrong_whitelist(
    monkeypatch, proxy_url, expected, status
):
    monkeypatch.setenv(PROXY_ENV, proxy_url)
    monkeypatch.setenv(IPS_ENV, expected)
    report = kite_network_readiness(probe=True, session_factory=lambda: Transport([]))
    assert report["status"] == status
    assert report["broker_whitelist_verified"] is False


@pytest.mark.parametrize("body", [b"x" * 129, b"127.0.0.1", b"not-an-ip", b"\xff"])
def test_invalid_or_oversized_echo_response_is_rejected(monkeypatch, proxy_url, body):
    monkeypatch.setenv(PROXY_ENV, proxy_url)
    report = kite_network_readiness(
        probe=True, session_factory=lambda: Transport([], Reply(body))
    )
    assert report["status"] == "probe_unavailable"
    assert report["samples_completed"] == 0


def test_echo_redirect_and_proxy_error_are_not_followed_or_exposed(
    monkeypatch, proxy_url
):
    monkeypatch.setenv(PROXY_ENV, proxy_url)
    redirect = Reply()
    redirect.status_code = 302
    for reply in (redirect, requests.exceptions.ProxyError(proxy_url)):
        calls = []
        report = kite_network_readiness(
            probe=True,
            session_factory=lambda calls=calls, reply=reply: Transport(calls, reply),
        )
        assert report["status"] == "probe_unavailable"
        assert len(calls) == 1
        assert proxy_url not in json.dumps(report)
