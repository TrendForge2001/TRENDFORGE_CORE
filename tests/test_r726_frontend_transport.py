"""All five tabs receive safe API errors when the HTTP boundary is malformed."""

import secrets
from io import BytesIO

import pytest
import requests

from webapp.api_client import ApiError, TrendForgeApi


class Response:
    ok = True
    status_code = 200
    reason = "OK"
    url = "https://backend.invalid/?token=private"

    def __init__(self, payload=None, *, invalid=False):
        self.payload = payload
        self.invalid = invalid

    def json(self):
        if self.invalid:
            raise ValueError("private gateway response")
        return self.payload


class Session:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def invoke(client, method):
    if method in {"get_json", "delete_json"}:
        return getattr(client, method)("/test")
    if method == "upload_file":
        return client.upload_file(
            "/test",
            filename="test.csv",
            file_obj=BytesIO(b"x"),
            content_type="text/csv",
        )
    return getattr(client, method)("/test", {})


@pytest.mark.parametrize(
    "method", ["get_json", "post_json", "put_json", "delete_json", "upload_file"]
)
@pytest.mark.parametrize(
    "response", [Response(invalid=True), Response({"ltp": float("inf")})]
)
def test_bad_json_and_non_finite_financial_values_are_safe_api_errors(method, response):
    session = Session(response)
    client = TrendForgeApi("https://backend.invalid", session=session)
    with pytest.raises(ApiError, match="invalid JSON") as caught:
        invoke(client, method)
    assert caught.value.detail is None
    assert caught.value.url is None
    assert "private" not in str(caught.value)
    assert len(session.calls) == 1


def test_transport_failure_does_not_expose_credentials_or_retry_mutation():
    private = "https://backend.invalid/?token=" + "private-credential-value"
    session = Session(error=requests.Timeout(private))
    client = TrendForgeApi("https://backend.invalid", session=session)
    with pytest.raises(ApiError, match="unreachable") as caught:
        client.post_json("/paper/open", {})
    assert caught.value.detail is None
    assert caught.value.url is None
    assert "private-credential-value" not in str(caught.value)
    assert len(session.calls) == 1


def test_non_json_gateway_error_body_and_reason_are_not_presented():
    response = Response(invalid=True)
    response.ok = False
    response.status_code = 502
    response.reason = "private upstream failure"
    response.text = "private gateway document"
    client = TrendForgeApi("https://backend.invalid", session=Session(response))
    with pytest.raises(ApiError) as caught:
        client.get_json("/test")
    assert caught.value.status_code == 502
    assert caught.value.detail is None
    assert "private" not in str(caught.value)


def test_get_rejects_non_object_without_echoing_the_payload():
    client = TrendForgeApi(
        "https://backend.invalid", session=Session(Response(["private account row"]))
    )
    with pytest.raises(ApiError, match="non-object") as caught:
        client.get_json("/test")
    assert caught.value.detail is None
    assert "private" not in str(caught.value)


def test_redirect_is_rejected_before_admin_header_can_follow_it():
    response = Response({})
    response.status_code = 307
    session = Session(response)
    client = TrendForgeApi(
        "https://backend.invalid", "session-admin-key", session=session
    )
    with pytest.raises(ApiError, match="unexpected redirect"):
        client.post_json("/paper/open", {})
    assert len(session.calls) == 1
    assert session.calls[0]["allow_redirects"] is False


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_server_json_error_preserves_only_safe_reference_and_known_code(status):
    reference = secrets.token_hex(6)
    response = Response(
        {
            "detail": "provider URL with private-credential-value",
            "reference": reference,
            "error_code": "SERVICE_UNAVAILABLE",
            "debug": "private-credential-value",
        }
    )
    response.ok = False
    response.status_code = status
    client = TrendForgeApi("https://backend.invalid", session=Session(response))
    with pytest.raises(ApiError) as caught:
        client.get_json("/test")
    assert "private-credential-value" not in str(caught.value)
    assert caught.value.detail == {
        "reference": reference,
        "error_code": "SERVICE_UNAVAILABLE",
    }


def test_verified_storage_block_retains_its_actionable_message():
    message = (
        "Administrative writes are disabled because "
        "database storage is not verified persistent."
    )
    response = Response({"detail": message})
    response.ok = False
    response.status_code = 503
    client = TrendForgeApi("https://backend.invalid", session=Session(response))
    with pytest.raises(ApiError) as caught:
        client.post_json("/test", {})
    assert caught.value.message == caught.value.detail == message


def test_malformed_server_error_metadata_is_discarded():
    response = Response({"error_code": ["private"], "reference": {"private": True}})
    response.ok = False
    response.status_code = 503
    client = TrendForgeApi("https://backend.invalid", session=Session(response))
    with pytest.raises(ApiError) as caught:
        client.get_json("/test")
    assert caught.value.detail is None
