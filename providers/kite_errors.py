"""Safe exception contract shared by TrendForge's Kite transports."""

from __future__ import annotations


class KiteException(Exception):
    default_code = 500

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = self.default_code if code is None else code


class GeneralException(KiteException):
    pass


class TokenException(KiteException):
    default_code = 403


class PermissionException(KiteException):
    default_code = 403


class OrderException(KiteException):
    pass


class InputException(KiteException):
    default_code = 400


class DataException(KiteException):
    default_code = 502


class NetworkException(KiteException):
    default_code = 503

    def __init__(
        self, message: str, code: int | None = None, *, reason: str | None = None
    ):
        super().__init__(message, code)
        self.reason = reason
