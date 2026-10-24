"""Fixed, credential-free descriptions of Kite session failures."""

from providers.kite_errors import (
    DataException,
    KiteException,
    NetworkException,
    PermissionException,
    TokenException,
)

MESSAGES = {
    "tls_failure": (
        "The backend could not verify Kite's TLS connection. "
        "Check proxy and trusted certificate settings."
    ),
    "proxy_failure": "The configured network proxy could not connect to Kite.",
    "request_timeout": "The Kite request timed out. Check connectivity and retry.",
    "connection_failed": "The backend could not establish a connection to Kite.",
    "credential_format_invalid": "Loaded Kite credentials contain invalid formatting.",
    "api_key_missing": "The running backend has no Kite API key loaded.",
    "access_token_missing": "The running backend has no Kite access token loaded.",
    "token_rejected": "Kite rejected the API key/access token pair.",
    "permission_denied": "Kite denied permission for this request.",
    "transport_unavailable": (
        "The backend could not connect to Kite. Check internet, proxy and TLS settings."
    ),
    "rate_limited": "Kite rate-limited the session check. Retry after a pause.",
    "upstream_unavailable": "Kite returned a server error. Retry later.",
    "invalid_response": "Kite returned an unexpected response to the session check.",
    "probe_failed": "The session check failed; the cause has not been identified.",
}


def session_failure(error: Exception) -> dict:
    status = getattr(error, "code", None)
    status = status if type(status) is int and 400 <= status <= 599 else None
    if isinstance(error, NetworkException):
        code = (
            error.reason
            if error.reason
            in {"tls_failure", "proxy_failure", "request_timeout", "connection_failed"}
            else "transport_unavailable"
        )
        status = None
    elif status == 429:
        code = "rate_limited"
    elif isinstance(error, TokenException):
        code = "token_rejected"
        if str(error) in {
            "Kite API key is missing or invalid",
            "Kite access token is missing or invalid",
            "Kite credentials contain invalid characters",
        }:
            code, status = "credential_format_invalid", None
    elif isinstance(error, PermissionException):
        code = "permission_denied"
    elif isinstance(error, DataException):
        code = "invalid_response"
    elif isinstance(error, KiteException) and status is not None and status >= 500:
        code = "upstream_unavailable"
    else:
        code = "probe_failed"
        status = None
    return {"code": code, "message": MESSAGES[code], "http_status": status}


def safe_session_failure(health: dict) -> dict:
    code = health.get("auth_error_code")
    if not isinstance(code, str) or code not in MESSAGES:
        code = "probe_failed"
    status = health.get("auth_http_status")
    status = status if type(status) is int and 400 <= status <= 599 else None
    return {"code": code, "message": MESSAGES[code], "http_status": status}
