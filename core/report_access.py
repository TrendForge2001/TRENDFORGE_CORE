"""Server-only report passwords and expiring Kite-window reauthentication."""

import hashlib
import hmac
import io
import os
import secrets
import threading
import time
from collections import deque

_attempts = deque()
_attempt_lock = threading.Lock()


def validate_portal_secrets():
    names = (
        "TRENDFORGE_WEBAPP_ACCESS_KEY",
        "TRENDFORGE_EXCEL_PASSWORD",
        "TRENDFORGE_KITE_WINDOW_PASSWORD",
    )
    values = [os.getenv(name, "").strip() for name in names]
    if min(map(len, values)) < 32 or len(set(values)) != len(values):
        raise ValueError(
            "Configure distinct owner, Excel and Kite-window passwords "
            "of at least 32 characters"
        )


def password(scope):
    if scope not in {"excel", "kite"}:
        raise ValueError("Unknown password scope")
    key = (
        "TRENDFORGE_EXCEL_PASSWORD"
        if scope == "excel"
        else "TRENDFORGE_KITE_WINDOW_PASSWORD"
    )
    value = os.getenv(key, "").strip()
    if len(value) < 32:
        raise ValueError(
            "Configure the dedicated TrendForge password "
            "(at least 32 characters) before using this feature"
        )
    return value


def check_password(supplied, scope="kite"):
    return (
        isinstance(supplied, str)
        and len(supplied) <= 2048
        and secrets.compare_digest(supplied.encode(), password(scope).encode())
    )


def kite_token(supplied, *, now=None):
    with _attempt_lock:
        stamp = time.monotonic()
        while _attempts and stamp - _attempts[0] >= 300:
            _attempts.popleft()
        if len(_attempts) >= 10:
            raise ValueError(
                "Too many Kite-window attempts. Try again in five minutes."
            )
        if not check_password(supplied):
            _attempts.append(stamp)
            raise ValueError("Incorrect Kite-window password")
    expiry = int(time.time() if now is None else now) + 900
    payload = f"kite-window:{expiry}:{secrets.token_hex(16)}"
    signature = hmac.new(
        password("kite").encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return payload + ":" + signature


def kite_unlocked(token, *, now=None):
    if not isinstance(token, str) or len(token) > 200:
        return False
    try:
        purpose, expiry, nonce, signature = token.split(":")
        current = int(time.time() if now is None else now)
        if purpose != "kite-window" or not current < int(expiry) <= current + 900:
            return False
        expected = hmac.new(
            password("kite").encode(),
            f"{purpose}:{expiry}:{nonce}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return secrets.compare_digest(signature, expected)
    except (ValueError, TypeError):
        return False


def encrypted_excel(data):
    """Actual Office Agile encryption, never worksheet-only protection."""
    import msoffcrypto
    from msoffcrypto.format.ooxml import OOXMLFile

    data = bytes(data)
    key = password("excel")
    office = msoffcrypto.OfficeFile(io.BytesIO(data))
    if office.is_encrypted():
        return data
    target = io.BytesIO()
    OOXMLFile(io.BytesIO(data)).encrypt(key, target)
    return target.getvalue()
