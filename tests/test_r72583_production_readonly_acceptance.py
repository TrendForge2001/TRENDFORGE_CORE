"""R72.5.8.3 acceptance probe: safe HTTP methods and redacted results."""
from contextlib import contextmanager
from io import BytesIO
import pytest

from scripts.production_readonly_acceptance import PATHS, probe, safe_base_url


class FakeResponse:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, body=b"{}"):
        self.body = body

    def read(self, _max_bytes):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_probe_uses_get_only_and_never_discloses_admin_key():
    requests = []

    def opener(request, timeout):
        assert timeout == 20
        assert request.get_method() == "GET"
        requests.append(request)
        return FakeResponse()

    secret = "super-secret-value"
    result = probe("https://example.test", opener=opener, admin_key=secret)
    assert result["all_read_probes_ok"] is True
    assert len(requests) == len(PATHS)
    assert "super-secret-value" not in str(result)
    assert requests[0].get_header("X-trendforge-admin-key") is None
    assert requests[2].get_header("X-trendforge-admin-key") == secret
    assert len(result["not_verified"]) == 4


@pytest.mark.parametrize("base", [
    "http://example.test",
    "https://user:password@example.test",
    "https://example.test/other",
    "https://example.test/?token=secret",
])
def test_unsafe_base_url_rejected(base):
    with pytest.raises(ValueError):
        safe_base_url(base)


def test_probe_records_failure_without_leaking_response_body():
    from urllib.error import HTTPError

    def opener(request, timeout):
        raise HTTPError(request.full_url, 401, "PRIVATE SECRET", None, BytesIO(b"token"))

    result = probe("https://example.test", opener=opener)
    assert result["all_read_probes_ok"] is False
    assert all(c["http_status"] == 401 for c in result["checks"])
    assert "PRIVATE SECRET" not in str(result)
    assert "token" not in str(result)
