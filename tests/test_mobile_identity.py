"""Signed JWT verification, owner isolation, revocation and API boundaries."""

import json
import time
from types import SimpleNamespace

import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.auth import crypt, jwt

from api.mobile_auth_router import attach_mobile_auth_routes
from services.mobile_identity import (
    CERTIFICATES_URL,
    LOOKUP_URL,
    CertificateRequest,
    FirebaseOwnerIdentity,
    MobileIdentityError,
)


class Response:
    def __init__(self, body, status=200, headers=None):
        self.body = json.dumps(body).encode()
        self.status_code = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def iter_content(self, _size):
        yield self.body


class Accounts:
    def __init__(self):
        self.calls = []
        self.user = {"localId": "owner-uid", "validSince": "0"}
        self.response = None
        self.failure = False

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        assert url == LOOKUP_URL
        assert kwargs["allow_redirects"] is False
        assert kwargs["timeout"] == 5
        if self.failure:
            raise requests.ConnectionError("private URL and token")
        return self.response or Response({"users": [self.user]})


@pytest.fixture(scope="module")
def signing_keys():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        .decode()
    )
    return crypt.RSASigner.from_string(private, key_id="test-kid"), public


@pytest.fixture
def identity(monkeypatch, signing_keys):
    monkeypatch.setenv("TRENDFORGE_MOBILE_ENABLED", "true")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "test-project")
    monkeypatch.setenv("TRENDFORGE_MOBILE_OWNER_UID", "owner-uid")
    monkeypatch.setenv("FIREBASE_WEB_API_KEY", "test-web-key")
    monkeypatch.delenv("TRENDFORGE_MOBILE_AUTH_EPOCH", raising=False)
    monkeypatch.delenv("TRENDFORGE_MOBILE_TOKEN_MAX_AGE_SECONDS", raising=False)
    signer, public = signing_keys
    accounts = Accounts()

    def certificates(url, method="GET"):
        assert url == CERTIFICATES_URL and method == "GET"
        return SimpleNamespace(
            status=200, data=json.dumps({"test-kid": public}).encode()
        )

    verifier = FirebaseOwnerIdentity(session=accounts, certificate_request=certificates)

    def token(**changes):
        now = int(time.time())
        claims = {
            "iss": "https://securetoken.google.com/test-project",
            "aud": "test-project",
            "sub": "owner-uid",
            "iat": now - 10,
            "exp": now + 3500,
            "auth_time": now - 20,
            **changes,
        }
        return jwt.encode(signer, claims).decode()

    return verifier, accounts, token


def test_real_signature_and_account_verification(identity):
    verifier, accounts, token = identity
    credential = token()
    result = verifier.verify(credential)
    assert result["uid"] == "owner-uid"
    assert accounts.calls[0][1]["json"] == {"idToken": credential}
    assert "test-web-key" not in json.dumps(result)


@pytest.mark.parametrize(
    "changes",
    [
        {"aud": "another-project"},
        {"iss": "https://attacker.invalid"},
        {"exp": 1},
        {"iat": 1},
        {"auth_time": "not-a-time"},
        {"auth_time": True},
        {"exp": float("inf")},
    ],
)
def test_invalid_signed_claims_are_rejected_before_account_lookup(identity, changes):
    verifier, accounts, token = identity
    with pytest.raises(MobileIdentityError) as caught:
        verifier.verify(token(**changes))
    assert caught.value.status == 401
    assert not accounts.calls


def test_valid_non_owner_is_forbidden_before_private_account_lookup(identity):
    verifier, accounts, token = identity
    with pytest.raises(MobileIdentityError) as caught:
        verifier.verify(token(sub="another-user"))
    assert caught.value.status == 403
    assert not accounts.calls


def test_tenant_token_cannot_reuse_an_owner_uid(identity):
    verifier, accounts, token = identity
    with pytest.raises(MobileIdentityError) as caught:
        verifier.verify(token(firebase={"tenant": "another-tenant"}))
    assert caught.value.status == 403 and not accounts.calls


@pytest.mark.parametrize("credential", ["bad.jwt", "x" * 16385, "", "e30.e30.invalid"])
def test_malformed_tokens_fail_closed(identity, credential):
    verifier, accounts, _token = identity
    with pytest.raises(MobileIdentityError) as caught:
        verifier.verify(credential)
    assert caught.value.status == 401
    assert not accounts.calls


def test_signature_cannot_be_replaced_by_unsigned_or_hmac_token(identity):
    verifier, accounts, token = identity
    raw = token()
    parts = raw.split(".")
    parts[-1] = "invalid-signature"
    with pytest.raises(MobileIdentityError) as caught:
        verifier.verify(".".join(parts))
    assert caught.value.status == 401
    assert not accounts.calls


@pytest.mark.parametrize(
    "update,expected",
    [
        ({"disabled": True}, 401),
        ({"localId": "different-owner"}, 401),
        ({"validSince": "99999999999"}, 401),
        ({"validSince": "invalid"}, 503),
    ],
)
def test_disabled_revoked_and_malformed_accounts_are_rejected(
    identity, update, expected
):
    verifier, accounts, token = identity
    accounts.user.update(update)
    with pytest.raises(MobileIdentityError) as caught:
        verifier.verify(token())
    assert caught.value.status == expected


def test_account_revocation_is_not_cached(identity):
    verifier, accounts, token = identity
    credential = token()
    verifier.verify(credential)
    accounts.user["disabled"] = True
    with pytest.raises(MobileIdentityError):
        verifier.verify(credential)
    assert len(accounts.calls) == 2


def test_local_auth_epoch_forces_reauthentication(identity, monkeypatch):
    verifier, accounts, token = identity
    monkeypatch.setenv("TRENDFORGE_MOBILE_AUTH_EPOCH", str(int(time.time()) - 5))
    with pytest.raises(MobileIdentityError) as caught:
        verifier.verify(token())
    assert caught.value.status == 401 and not accounts.calls


def test_network_failure_is_sanitized(identity):
    verifier, accounts, token = identity
    accounts.failure = True
    with pytest.raises(MobileIdentityError) as caught:
        verifier.verify(token())
    assert caught.value.status == 503
    assert "private" not in str(caught.value)


@pytest.mark.parametrize(
    "message,status", [("INVALID_ID_TOKEN", 401), ("API_KEY_INVALID", 503)]
)
def test_bad_project_configuration_is_not_labelled_an_expired_session(
    identity, message, status
):
    verifier, accounts, token = identity
    accounts.response = Response({"error": {"message": message}}, status=400)
    with pytest.raises(MobileIdentityError) as caught:
        verifier.verify(token())
    assert caught.value.status == status


def test_certificate_unavailability_fails_closed_before_account_lookup(identity):
    verifier, accounts, token = identity

    def unavailable(*_args, **_kwargs):
        raise MobileIdentityError(503)

    verifier.certificate_request = unavailable
    with pytest.raises(MobileIdentityError) as caught:
        verifier.verify(token())
    assert caught.value.status == 503 and not accounts.calls


def test_missing_configuration_disables_mobile_without_network(identity, monkeypatch):
    verifier, accounts, token = identity
    monkeypatch.setenv("TRENDFORGE_MOBILE_ENABLED", "false")
    with pytest.raises(MobileIdentityError) as caught:
        verifier.verify(token())
    assert caught.value.status == 503 and not accounts.calls


def test_certificate_cache_is_fixed_url_bounded_and_no_redirects():
    calls = []

    class Certificates:
        def get(self, url, **kwargs):
            calls.append(url)
            assert kwargs == {"timeout": 5, "allow_redirects": False, "stream": True}
            return Response(
                {"kid": "public-certificate"},
                headers={"Cache-Control": "public, max-age=3600"},
            )

    transport = CertificateRequest(Certificates())
    assert transport(CERTIFICATES_URL).status == 200
    assert transport(CERTIFICATES_URL).status == 200
    assert len(calls) == 1
    with pytest.raises(MobileIdentityError):
        transport("https://attacker.invalid/certificates")


def test_owner_api_rejects_missing_auth_returns_no_secrets_and_never_trades(
    identity, monkeypatch
):
    verifier, accounts, token = identity
    app = FastAPI()
    attach_mobile_auth_routes(app, identity=verifier)
    monkeypatch.setattr(
        "api.mobile_auth_router.paper_storage_setup",
        lambda: {"verified": False, "checks": []},
    )
    client = TestClient(app)
    for path in ("/mobile/v1/auth/session", "/mobile/v1/readiness"):
        denied = client.get(path)
        assert denied.status_code == 401
        assert denied.headers["cache-control"] == "no-store"
        accepted = client.get(path, headers={"Authorization": f"Bearer {token()}"})
        assert accepted.status_code == 200
        assert accepted.json()["broker_orders_allowed"] is False
        assert accepted.json()["trading_mutations_available"] is False
        assert "test-web-key" not in accepted.text
        assert accepted.headers["vary"] == "Authorization"
    assert (
        client.put("/mobile/v1/paper/automation", json={"enabled": True}).status_code
        == 404
    )
    assert len(accounts.calls) == 2


def test_mobile_identity_never_satisfies_core_admin_auth(identity, monkeypatch):
    from fastapi import Depends

    from api.admin_auth import require_admin_api_key

    verifier, _, token = identity
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", "test-admin-value-" * 4)
    app = FastAPI()
    attach_mobile_auth_routes(app, identity=verifier)

    @app.get("/core-protected", dependencies=[Depends(require_admin_api_key)])
    def protected():
        return {"unreachable": True}

    result = TestClient(app).get(
        "/core-protected", headers={"Authorization": f"Bearer {token()}"}
    )
    assert result.status_code == 401
