"""Owner-only Firebase ID-token verification; no Admin or broker credentials."""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import requests

CERTIFICATES_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/"
    "securetoken@system.gserviceaccount.com"
)
LOOKUP_URL = "https://identitytoolkit.googleapis.com/v1/accounts:lookup"


class MobileIdentityError(RuntimeError):
    """Only fixed, public error categories cross the API boundary."""

    def __init__(self, status: int):
        self.status = status
        super().__init__("Mobile identity verification failed")


@dataclass(frozen=True)
class MobileIdentitySettings:
    project: str
    owner: str
    web_api_key: str
    max_age: int
    auth_epoch: int

    @classmethod
    def from_env(cls) -> MobileIdentitySettings:
        if os.getenv("TRENDFORGE_MOBILE_ENABLED", "").strip().lower() != "true":
            raise MobileIdentityError(503)
        project = os.getenv("FIREBASE_PROJECT_ID", "").strip()
        owner = os.getenv("TRENDFORGE_MOBILE_OWNER_UID", "").strip()
        key = os.getenv("FIREBASE_WEB_API_KEY", "").strip()
        try:
            max_age = int(os.getenv("TRENDFORGE_MOBILE_TOKEN_MAX_AGE_SECONDS", "900"))
            epoch = int(os.getenv("TRENDFORGE_MOBILE_AUTH_EPOCH", "0"))
        except ValueError:
            raise MobileIdentityError(503) from None
        if (
            not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project)
            or not 1 <= len(owner) <= 128
            or not key
            or not 60 <= max_age <= 3600
            or epoch < 0
        ):
            raise MobileIdentityError(503)
        return cls(project, owner, key, max_age, epoch)


class CertificateRequest:
    """Fixed Google certificate URL, bounded time/body and a short cache."""

    def __init__(self, session: Any = None):
        self.session = session or requests.Session()
        self.lock = threading.Lock()
        self.expires = 0.0
        self.cached: bytes | None = None

    def __call__(self, url: str, method: str = "GET") -> Any:
        if url != CERTIFICATES_URL or method != "GET":
            raise MobileIdentityError(503)
        with self.lock:
            if self.cached is not None and time.monotonic() < self.expires:
                return SimpleNamespace(status=200, data=self.cached)
            try:
                with self.session.get(
                    url, timeout=5, allow_redirects=False, stream=True
                ) as response:
                    if response.status_code != 200:
                        raise MobileIdentityError(503)
                    data = bytearray()
                    for chunk in response.iter_content(16384):
                        data.extend(chunk)
                        if len(data) > 100_000:
                            raise MobileIdentityError(503)
                    body = json.loads(data)
                    if not isinstance(body, dict) or not body:
                        raise MobileIdentityError(503)
                    cache_age = re.search(
                        r"(?:^|,)\s*max-age=(\d+)",
                        response.headers.get("Cache-Control", ""),
                    )
                    ttl = min(300, int(cache_age[1])) if cache_age else 60
            except (requests.RequestException, ValueError):
                raise MobileIdentityError(503) from None
            self.cached = bytes(data)
            self.expires = time.monotonic() + ttl
            return SimpleNamespace(status=200, data=self.cached)


class FirebaseOwnerIdentity:
    def __init__(self, *, session: Any = None, certificate_request: Any = None):
        self.session = session or requests.Session()
        self.certificate_request = certificate_request or CertificateRequest()

    def verify(self, token: str) -> dict[str, Any]:
        settings = MobileIdentitySettings.from_env()
        if not token or len(token) > 16384:
            raise MobileIdentityError(401)
        from google.auth import jwt
        from google.oauth2 import id_token

        try:
            header = jwt.decode_header(token)
            if (
                not isinstance(header, dict)
                or header.get("alg") != "RS256"
                or not isinstance(header.get("kid"), str)
                or not 1 <= len(header["kid"]) <= 256
            ):
                raise MobileIdentityError(401)
            claims = id_token.verify_firebase_token(
                token,
                self.certificate_request,
                audience=settings.project,
            )
        except MobileIdentityError:
            raise
        except (ValueError, TypeError, KeyError):
            raise MobileIdentityError(401) from None
        # Signature/audience/expiry verification above must precede claim use.
        now = time.time()
        times = [claims.get(name) for name in ("iat", "exp", "auth_time")]
        if not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            for value in times
        ):
            raise MobileIdentityError(401)
        issued, expires, authenticated = times
        if (
            claims.get("iss") != f"https://securetoken.google.com/{settings.project}"
            or claims.get("aud") != settings.project
            or issued > now
            or expires <= now
            or expires <= issued
            or expires - issued > 3600
            or now - issued > settings.max_age
            or authenticated > issued
            or authenticated < settings.auth_epoch
        ):
            raise MobileIdentityError(401)
        if claims.get("sub") != settings.owner:
            raise MobileIdentityError(403)
        firebase_claims = claims.get("firebase", {})
        if not isinstance(firebase_claims, dict) or firebase_claims.get("tenant"):
            # Owner UIDs are not assumed unique across Identity Platform tenants.
            raise MobileIdentityError(403)
        # Check account disable/revocation on every request, not only JWT expiry.
        try:
            with self.session.post(
                LOOKUP_URL,
                params={"key": settings.web_api_key},
                json={"idToken": token},
                timeout=5,
                allow_redirects=False,
                stream=True,
            ) as response:
                raw = bytearray()
                for chunk in response.iter_content(16384):
                    raw.extend(chunk)
                    if len(raw) > 100_000:
                        raise MobileIdentityError(503)
                body = json.loads(raw)
                if response.status_code != 200:
                    error = body.get("error") if isinstance(body, dict) else None
                    message = (
                        error.get("message", "") if isinstance(error, dict) else ""
                    )
                    invalid_session = message in {
                        "INVALID_ID_TOKEN",
                        "TOKEN_EXPIRED",
                        "USER_DISABLED",
                        "USER_NOT_FOUND",
                        "CREDENTIAL_MISMATCH",
                    }
                    raise MobileIdentityError(401 if invalid_session else 503)
            users = body.get("users") if isinstance(body, dict) else None
            if not isinstance(users, list) or len(users) != 1:
                raise MobileIdentityError(401)
            user = users[0]
            if (
                not isinstance(user, dict)
                or user.get("localId") != settings.owner
                or user.get("disabled", False) is not False
            ):
                raise MobileIdentityError(401)
            valid_since = user.get("validSince")
            if not isinstance(valid_since, str) or not re.fullmatch(
                r"\d{1,12}", valid_since
            ):
                raise MobileIdentityError(503)
            if authenticated < int(valid_since):
                raise MobileIdentityError(401)
        except (requests.RequestException, ValueError, TypeError):
            raise MobileIdentityError(503) from None
        return {"uid": settings.owner, "expires_at": int(expires)}
