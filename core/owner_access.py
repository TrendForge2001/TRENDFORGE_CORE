"""Owner portal with signed, expiring cookies before Streamlit and WebSockets."""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import logging
import os
import secrets
import time
from collections import OrderedDict
from urllib.parse import parse_qs, quote

from starlette.requests import HTTPConnection, Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

COOKIE = "tf_owner_session"
CSRF_COOKIE = "tf_owner_login_csrf"
SESSION_SECONDS = 8 * 60 * 60
PRIVATE_HEADERS = {
    "Cache-Control": "private, no-store",
    "Pragma": "no-cache",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
}
_REVOKED = OrderedDict()


def revoke_owner_token(token):
    if valid_token(token):
        _REVOKED[hashlib.sha256(token.encode()).hexdigest()] = time.time()
        while len(_REVOKED) > 4096:
            _REVOKED.popitem(last=False)


def _key():
    key = os.getenv("TRENDFORGE_WEBAPP_ACCESS_KEY", "").strip()
    return key if len(key) >= 32 else ""


def _signing_key():
    secret = os.getenv("TRENDFORGE_OWNER_SIGNING_SECRET", "").strip()
    return secret if len(secret) >= 32 and secret != _key() else ""


def _sign(value):
    return hmac.new(
        _signing_key().encode(),
        ("trendforge-owner-v2:" + _key() + ":" + value).encode(),
        hashlib.sha256,
    ).hexdigest()


def issue_token(purpose, *, now=None):
    if not (_key() and _signing_key()):
        raise ValueError("Owner access is not configured.")
    value = (
        f"{purpose}:{int(time.time() if now is None else now)}:{secrets.token_hex(16)}"
    )
    encoded = base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")
    return encoded + "." + _sign(encoded)


def valid_token(token, purpose="session", *, now=None):
    if (
        not _key()
        or not _signing_key()
        or not isinstance(token, str)
        or len(token) > 400
        or not token.isascii()
    ):
        return False
    digest = hashlib.sha256(token.encode()).hexdigest()
    revoked_at = _REVOKED.get(digest)
    if revoked_at is not None:
        if time.time() - revoked_at < SESSION_SECONDS:
            return False
        _REVOKED.pop(digest, None)
    try:
        encoded, supplied = token.split(".")
        if not hmac.compare_digest(supplied, _sign(encoded)):
            return False
        data = base64.b64decode(
            encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
        ).decode()
        kind, timestamp, _nonce = data.split(":")
        age = (time.time() if now is None else now) - int(timestamp)
        return kind == purpose and 0 <= age < (
            SESSION_SECONDS if purpose == "session" else 600
        )
    except (ValueError, UnicodeError):
        return False


def _next_path(value):
    # Only local Streamlit paths; no authority, encoded slash or open redirect.
    value = str(value or "")
    if value.startswith("/app/") and not any(
        c in value for c in ("\\", "\r", "\n", "%", "?", "#")
    ):
        return value[:300]
    return "/app/"


class OwnerAccessMiddleware:
    """Gate the entire UI, including static resources and WebSocket upgrades."""

    def __init__(self, app):
        self.app = app
        self.attempts = OrderedDict()

    def _limited(self, client, *, failed=False):
        now = time.monotonic()
        first, attempts = self.attempts.pop(client, (now, 0))
        if now - first > 300:
            first, attempts = now, 0
        if failed:
            attempts += 1
        self.attempts[client] = (first, attempts)
        while len(self.attempts) > 4096:
            self.attempts.popitem(last=False)
        if failed and attempts == 20:
            logging.getLogger(__name__).warning(
                "Owner sign-in rate limit reached for five-minute window"
            )
        return attempts >= 20

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        request = HTTPConnection(scope)
        if path.startswith("/owner/"):
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 4401})
            request = Request(scope, receive)
            response = await self.portal(request)
            return await response(scope, receive, send)
        if path == "/app" or path.startswith("/app/"):
            token = request.cookies.get(COOKIE)
            if not valid_token(token):
                if scope["type"] == "websocket":
                    return await send({"type": "websocket.close", "code": 4401})
                response = RedirectResponse(
                    "/owner/laptop?next=" + quote(_next_path(path), safe=""),
                    status_code=303,
                    headers=PRIVATE_HEADERS,
                )
                return await response(scope, receive, send)

            closed = False

            async def private_send(message):
                nonlocal closed
                if scope["type"] == "websocket":
                    if closed:
                        return
                    if not valid_token(token):
                        closed = True
                        return await send({"type": "websocket.close", "code": 4401})
                if message["type"] == "http.response.start":
                    additions = [
                        (k.lower().encode(), v.encode())
                        for k, v in PRIVATE_HEADERS.items()
                    ]
                    names = {k for k, _ in additions}
                    message["headers"] = [
                        (k, v)
                        for k, v in message.get("headers", [])
                        if k.lower() not in names
                    ] + additions
                await send(message)

            async def private_receive():
                nonlocal closed
                message = await receive()
                if scope["type"] == "websocket" and (closed or not valid_token(token)):
                    if not closed:
                        closed = True
                        await send({"type": "websocket.close", "code": 4401})
                    return {"type": "websocket.disconnect", "code": 4401}
                return message

            return await self.app(scope, private_receive, private_send)
        return await self.app(scope, receive, send)

    async def portal(self, request):
        path = request.url.path
        secure = request.url.scheme == "https" or request.url.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
            "testserver",
        }
        if path == "/owner/logout":
            revoke_owner_token(request.cookies.get(COOKIE))
            response = RedirectResponse(
                "/owner/laptop", status_code=303, headers=PRIVATE_HEADERS
            )
            response.delete_cookie(
                COOKIE, path="/", secure=secure, httponly=True, samesite="strict"
            )
            return response
        if path not in {"/owner/mobile", "/owner/laptop"}:
            return JSONResponse(
                {"detail": "Not found"}, status_code=404, headers=PRIVATE_HEADERS
            )
        if request.method not in {"GET", "POST"}:
            return JSONResponse(
                {"detail": "Method not allowed"},
                status_code=405,
                headers=PRIVATE_HEADERS,
            )
        if not (_key() and _signing_key()):
            return HTMLResponse(
                "TrendForge is locked. Owner access must be configured on the server.",
                status_code=503,
                headers=PRIVATE_HEADERS,
            )
        destination = _next_path(request.query_params.get("next"))
        error, status = "", 200
        if request.method == "POST":
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 4096:
                    return JSONResponse(
                        {"detail": "Request too large"},
                        status_code=413,
                        headers=PRIVATE_HEADERS,
                    )
            try:
                fields = parse_qs(
                    body.decode("utf-8", errors="replace"), max_num_fields=8
                )
            except ValueError:
                return JSONResponse(
                    {"detail": "Invalid form"},
                    status_code=400,
                    headers=PRIVATE_HEADERS,
                )
            csrf = fields.get("csrf", [""])[0]
            destination = _next_path(fields.get("next", [""])[0])
            origin = request.headers.get("origin")
            expected_origin = (
                f"https://{request.url.netloc}"
                if secure
                else str(request.base_url).rstrip("/")
            )
            if (
                len(csrf) != 43
                or not csrf.isascii()
                or not secrets.compare_digest(
                    csrf.encode(), request.cookies.get(CSRF_COOKIE, "").encode()
                )
                or (origin and origin != expected_origin)
            ):
                return JSONResponse(
                    {"detail": "Invalid login request. Reload the sign-in page."},
                    status_code=403,
                    headers=PRIVATE_HEADERS,
                )
            client = request.client.host if request.client else "unknown"
            if self._limited(client):
                return HTMLResponse(
                    "Too many attempts. Try again in five minutes.",
                    status_code=429,
                    headers={**PRIVATE_HEADERS, "Retry-After": "300"},
                )
            supplied = fields.get("access_key", [""])[0].strip()
            if supplied and secrets.compare_digest(supplied.encode(), _key().encode()):
                self.attempts.pop(client, None)
                response = RedirectResponse(
                    destination, status_code=303, headers=PRIVATE_HEADERS
                )
                response.set_cookie(
                    COOKIE,
                    issue_token("session"),
                    max_age=SESSION_SECONDS,
                    path="/",
                    secure=secure,
                    httponly=True,
                    samesite="strict",
                )
                response.delete_cookie(
                    CSRF_COOKIE,
                    path="/owner",
                    secure=secure,
                    httponly=True,
                    samesite="strict",
                )
                return response
            self._limited(client, failed=True)
            error, status = "Invalid webapp access key. Access denied.", 401
        csrf = secrets.token_urlsafe(32)
        device = "mobile" if path.endswith("mobile") else "laptop"
        response = HTMLResponse(
            f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>TrendForge — Secure Sign In</title><style>
body{{font:16px system-ui;background:#0d1420;color:#f0f5ff;margin:0;
min-height:100vh;display:grid;place-items:center}}
main{{width:min(85vw,390px);padding:28px;background:#172338;
border:1px solid #334766;border-radius:16px}}
label,input,button{{display:block;box-sizing:border-box;width:100%;margin:12px 0}}
input,button{{padding:14px;font:inherit;border-radius:8px}}
button{{background:#4f8cff;color:white;border:0;cursor:pointer}}
p{{color:#c5d2e9;line-height:1.5}}.error{{color:#ffb1b1}}
</style></head><body><main><h1>TrendForge</h1><h2>Secure Sign In</h2>
<p>Private {device} workspace. Sign in with your owner access key.</p>
<p class="error">{html.escape(error)}</p><form method="post" action="{path}">
<input type="hidden" name="csrf" value="{csrf}">
<input type="hidden" name="next" value="{html.escape(destination, quote=True)}">
<label for="owner-key">Webapp access key</label>
<input id="owner-key" name="access_key" type="password" 
autocomplete="current-password" required maxlength="512">
<button type="submit">Open TrendForge</button></form>
<p>Your link does not contain credentials. 
This session expires after eight hours.</p></main></body></html>''',
            status_code=status,
            headers={
                **PRIVATE_HEADERS,
                "Content-Security-Policy": (
                    "default-src 'none'; style-src 'unsafe-inline'; "
                    "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
                ),
            },
        )
        response.set_cookie(
            CSRF_COOKIE,
            csrf,
            max_age=600,
            path="/owner",
            secure=secure,
            httponly=True,
            samesite="strict",
        )
        return response
