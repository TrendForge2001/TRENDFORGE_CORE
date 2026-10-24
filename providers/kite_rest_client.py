"""The Kite REST subset used by TrendForge, without the legacy SDK reactor.

Calls use a fixed TLS origin, bounded timeouts and no automatic HTTP retries.
Broker response messages and Requests exceptions are never exposed verbatim.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from datetime import date, datetime
from typing import Any, Protocol, cast
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter

from core.broker_execution_policy import LiveTradingDisabled
from providers.kite_errors import (
    DataException,
    GeneralException,
    InputException,
    KiteException,
    NetworkException,
    OrderException,
    PermissionException,
    TokenException,
)

BASE_URL = "https://api.kite.trade"
_MAX_RESPONSE_BYTES = 40_000_000
_COMPONENT = re.compile(r"[A-Za-z0-9_-]{1,64}")
_DATES = (
    "order_timestamp",
    "exchange_timestamp",
    "created",
    "last_instalment",
    "fill_timestamp",
    "timestamp",
    "last_trade_time",
    "login_time",
)
_ERRORS: dict[str, type[KiteException]] = {
    cls.__name__: cls
    for cls in (
        GeneralException,
        TokenException,
        PermissionException,
        OrderException,
        InputException,
        DataException,
        NetworkException,
    )
}


class _Response(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def content(self) -> bytes: ...

    @property
    def headers(self) -> Mapping[str, str]: ...

    def json(self) -> Any: ...


class _Transport(Protocol):
    def request(self, method: str, url: str, **kwargs: Any) -> _Response: ...


def _component(value: Any) -> str:
    result = str(value)
    if not _COMPONENT.fullmatch(result):
        raise InputException("Invalid Kite resource identifier")
    return result


def _record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DataException("Kite returned an invalid record")
    result = dict(cast(dict[str, Any], value))
    for field in _DATES:
        text = result.get(field)
        if isinstance(text, str) and len(text) == 19:
            with suppress(ValueError):
                result[field] = datetime.fromisoformat(text)
    return result


def _records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise DataException("Kite returned an invalid record list")
    return [_record(item) for item in cast(list[Any], value)]


def _validate_numbers(value: Any, depth: int = 0) -> None:
    if depth > 64:
        raise DataException("Kite JSON nesting exceeds the supported depth")
    if isinstance(value, float) and not math.isfinite(value):
        raise DataException("Kite returned a non-finite numeric value")
    if isinstance(value, dict):
        for child in cast(dict[str, Any], value).values():
            _validate_numbers(child, depth + 1)
    elif isinstance(value, list):
        for child in cast(list[Any], value):
            _validate_numbers(child, depth + 1)


class KiteRESTClient:
    """Broker protocol adapter; direct mutation requires an execution guard."""

    def __init__(
        self,
        api_key: str = "",
        *,
        access_token: str | None = None,
        session: requests.Session | _Transport | None = None,
        timeout: float = 7.0,
        execution_guard: Callable[[], None] | None = None,
    ) -> None:
        self.api_key = str(api_key).strip()
        self.access_token = (
            str(access_token).strip() if access_token is not None else None
        )
        self.timeout = max(1.0, min(60.0, float(timeout)))
        self._execution_guard = execution_guard
        self._session: requests.Session | _Transport = (
            session if session is not None else requests.Session()
        )
        if isinstance(self._session, requests.Session):
            # Never retry ambiguous order submissions in the HTTP layer.
            # Requests selects the longest adapter prefix, so remove narrower
            # adapters supplied by a caller before installing this policy.
            for prefix in list(self._session.adapters):
                if prefix.lower().startswith((BASE_URL + "/").lower()):
                    del self._session.adapters[prefix]
            self._session.mount(BASE_URL + "/", HTTPAdapter(max_retries=0))
            self._session.verify = True

    def set_access_token(self, access_token: str) -> None:
        self.access_token = str(access_token).strip()

    def _credentials(self, *, authenticated: bool) -> dict[str, str]:
        if not self.api_key or any(char in self.api_key for char in "\r\n"):
            raise TokenException("Kite API key is missing or invalid")
        try:
            self.api_key.encode("ascii")
            if self.access_token:
                self.access_token.encode("ascii")
        except UnicodeError:
            raise TokenException(
                "Kite credentials contain invalid characters"
            ) from None
        headers = {"X-Kite-Version": "3"}
        if authenticated or self.access_token:
            if not self.access_token or any(
                char in self.access_token for char in "\r\n"
            ):
                raise TokenException("Kite access token is missing or invalid")
            headers["Authorization"] = f"token {self.api_key}:{self.access_token}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        authenticated: bool = True,
        csv_response: bool = False,
    ) -> Any:
        headers = self._credentials(authenticated=authenticated)
        arguments: dict[str, Any] = {
            "headers": headers,
            "timeout": self.timeout,
            "allow_redirects": False,
        }
        if params is not None:
            arguments["params"] = {
                key: value for key, value in params.items() if value is not None
            }
        if data is not None:
            arguments["data"] = {
                key: value for key, value in data.items() if value is not None
            }
        try:
            response = self._session.request(method, BASE_URL + path, **arguments)
        except requests.RequestException as error:
            reason = (
                "tls_failure"
                if isinstance(error, requests.exceptions.SSLError)
                else "proxy_failure"
                if isinstance(error, requests.exceptions.ProxyError)
                else "request_timeout"
                if isinstance(error, requests.exceptions.Timeout)
                else "connection_failed"
                if isinstance(error, requests.exceptions.ConnectionError)
                else "transport_unavailable"
            )
            raise NetworkException(
                "Kite transport unavailable", reason=reason
            ) from None
        if 300 <= response.status_code < 400:
            raise DataException("Kite redirect rejected", response.status_code)
        raw = response.content
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise DataException("Kite response exceeds the supported size")
        is_json = "json" in response.headers.get("Content-Type", "").lower()
        if csv_response and not is_json and response.status_code < 400:
            return raw
        try:
            payload = response.json()
        except (ValueError, RecursionError):
            raise DataException(
                "Kite returned invalid JSON", response.status_code
            ) from None
        if not isinstance(payload, dict):
            raise DataException("Kite returned an invalid response envelope")
        body = cast(dict[str, Any], payload)
        _validate_numbers(body)
        if (
            response.status_code >= 400
            or body.get("status") == "error"
            or body.get("error_type")
        ):
            default = (
                TokenException if response.status_code == 403 else GeneralException
            )
            error_type = body.get("error_type")
            if error_type is not None and not isinstance(error_type, str):
                raise DataException("Kite returned an invalid error envelope")
            kind = _ERRORS.get(error_type, default) if error_type else default
            raise kind(
                f"Kite request failed (HTTP {response.status_code})",
                response.status_code,
            )
        if body.get("status") != "success" or "data" not in body:
            raise DataException("Kite returned an invalid response envelope")
        return body["data"]

    def login_url(self) -> str:
        self._credentials(authenticated=False)
        return "https://kite.zerodha.com/connect/login?" + urlencode(
            {"api_key": self.api_key, "v": "3"}
        )

    def generate_session(
        self, request_token: object, api_secret: object
    ) -> dict[str, Any]:
        if (
            not isinstance(request_token, str)
            or not request_token
            or not isinstance(api_secret, str)
            or not api_secret
        ):
            raise InputException("Kite session exchange requires credentials")
        checksum = hashlib.sha256(
            (self.api_key + request_token + api_secret).encode("utf-8")
        ).hexdigest()
        result = _record(
            self._request(
                "POST",
                "/session/token",
                authenticated=False,
                data={
                    "api_key": self.api_key,
                    "request_token": request_token,
                    "checksum": checksum,
                },
            )
        )
        token = result.get("access_token")
        if not isinstance(token, str) or not token:
            raise DataException("Kite session response lacks an access token")
        self.set_access_token(token)
        return result

    def invalidate_access_token(self, access_token: str | None = None) -> Any:
        try:
            return self._request(
                "DELETE",
                "/session/token",
                params={
                    "api_key": self.api_key,
                    "access_token": access_token or self.access_token,
                },
            )
        finally:
            self.access_token = None

    def profile(self) -> dict[str, Any]:
        return _record(self._request("GET", "/user/profile"))

    def margins(self, segment: str | None = None) -> dict[str, Any]:
        path = "/user/margins" + ("/" + _component(segment) if segment else "")
        return _record(self._request("GET", path))

    def holdings(self) -> list[dict[str, Any]]:
        return _records(self._request("GET", "/portfolio/holdings"))

    def positions(self) -> dict[str, Any]:
        return _record(self._request("GET", "/portfolio/positions"))

    def orders(self) -> list[dict[str, Any]]:
        return _records(self._request("GET", "/orders"))

    def trades(self) -> list[dict[str, Any]]:
        return _records(self._request("GET", "/trades"))

    def order_history(self, order_id: str) -> list[dict[str, Any]]:
        return _records(self._request("GET", "/orders/" + _component(order_id)))

    def order_trades(self, order_id: str) -> list[dict[str, Any]]:
        return _records(
            self._request("GET", "/orders/" + _component(order_id) + "/trades")
        )

    def get_gtts(self) -> list[dict[str, Any]]:
        return _records(self._request("GET", "/gtt/triggers"))

    def _quote(self, resource: str, instruments: tuple[Any, ...]) -> dict[str, Any]:
        values: Sequence[Any] = (
            cast(list[Any] | tuple[Any, ...], instruments[0])
            if len(instruments) == 1 and isinstance(instruments[0], (list, tuple))
            else instruments
        )
        if not values or any(
            not isinstance(value, str) or not value for value in values
        ):
            raise InputException("Kite quotes require instrument names")
        result = self._request("GET", resource, params={"i": list(values)})
        if not isinstance(result, dict):
            raise DataException("Kite returned an invalid quote map")
        return {
            name: _record(value) for name, value in cast(dict[str, Any], result).items()
        }

    def quote(self, *instruments: Any) -> dict[str, Any]:
        return self._quote("/quote", instruments)

    def ohlc(self, *instruments: Any) -> dict[str, Any]:
        return self._quote("/quote/ohlc", instruments)

    def ltp(self, *instruments: Any) -> dict[str, Any]:
        return self._quote("/quote/ltp", instruments)

    def instruments(self, exchange: str | None = None) -> list[dict[str, Any]]:
        path = "/instruments" + ("/" + _component(exchange) if exchange else "")
        raw = self._request("GET", path, authenticated=False, csv_response=True)
        try:
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), strict=True)
            required = {
                "instrument_token",
                "tradingsymbol",
                "exchange",
                "lot_size",
                "last_price",
                "strike",
                "tick_size",
                "expiry",
            }
            if reader.fieldnames is None or not required.issubset(reader.fieldnames):
                raise ValueError
            result: list[dict[str, Any]] = []
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError
                item: dict[str, Any] = dict(row)
                for name in ("instrument_token", "lot_size"):
                    item[name] = int(item[name])
                for name in ("last_price", "strike", "tick_size"):
                    item[name] = float(item[name])
                    if not math.isfinite(item[name]):
                        raise ValueError
                if item["expiry"]:
                    item["expiry"] = date.fromisoformat(item["expiry"])
                result.append(item)
            return result
        except (ValueError, TypeError, UnicodeError, csv.Error, AttributeError):
            raise DataException("Kite returned invalid instrument CSV") from None

    def historical_data(
        self,
        instrument_token: int,
        from_date: Any,
        to_date: Any,
        interval: str,
        continuous: bool = False,
        oi: bool = False,
    ) -> list[dict[str, Any]]:
        if (
            isinstance(instrument_token, bool)
            or not str(instrument_token).isdigit()
            or int(instrument_token) <= 0
        ):
            raise InputException("Invalid Kite instrument token")
        if interval not in {
            "minute",
            "3minute",
            "5minute",
            "10minute",
            "15minute",
            "30minute",
            "60minute",
            "day",
        }:
            raise InputException("Invalid Kite candle interval")
        # Preserve the existing SDK's datetime formatting contract, including
        # its wall-clock interpretation of aware inputs.
        params = {
            "from": from_date.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(from_date, datetime)
            else from_date,
            "to": to_date.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(to_date, datetime)
            else to_date,
            "interval": interval,
            "continuous": int(bool(continuous)),
            "oi": int(bool(oi)),
        }
        data = self._request(
            "GET",
            f"/instruments/historical/{instrument_token}/{interval}",
            params=params,
        )
        try:
            rows = data["candles"]
            if not isinstance(rows, list):
                raise ValueError
            result: list[dict[str, Any]] = []
            for row_value in cast(list[Any], rows):
                if not isinstance(row_value, list):
                    raise ValueError
                row = cast(list[Any], row_value)
                if len(row) not in {6, 7} or not isinstance(row[0], str):
                    raise ValueError
                if any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    for value in row[1:]
                ):
                    raise ValueError
                item: dict[str, Any] = dict(
                    zip(
                        ("date", "open", "high", "low", "close", "volume"),
                        row[:6],
                        strict=True,
                    )
                )
                item["date"] = datetime.fromisoformat(row[0])
                if len(row) == 7:
                    item["oi"] = row[6]
                result.append(item)
            return result
        except (KeyError, ValueError, TypeError, OverflowError):
            raise DataException("Kite returned invalid candles") from None

    def _require_execution(self) -> None:
        if self._execution_guard is None:
            raise LiveTradingDisabled(
                "Live trading disabled: broker order operations require explicit opt-in"
            )
        self._execution_guard()

    @staticmethod
    def _order_id(result: Any) -> str:
        value = (
            cast(dict[str, Any], result).get("order_id")
            if isinstance(result, dict)
            else None
        )
        if not isinstance(value, str) or not value:
            raise DataException("Kite order response lacks an order identifier")
        return value

    def place_order(
        self,
        variety: str,
        exchange: str,
        tradingsymbol: str,
        transaction_type: str,
        quantity: int,
        product: str,
        order_type: str,
        **kwargs: Any,
    ) -> str:
        self._require_execution()
        data = {
            **kwargs,
            "variety": variety,
            "exchange": exchange,
            "tradingsymbol": tradingsymbol,
            "transaction_type": transaction_type,
            "quantity": quantity,
            "product": product,
            "order_type": order_type,
        }
        return self._order_id(
            self._request("POST", "/orders/" + _component(variety), data=data)
        )

    def modify_order(self, variety: str, order_id: str, **kwargs: Any) -> str:
        self._require_execution()
        return self._order_id(
            self._request(
                "PUT",
                "/orders/" + _component(variety) + "/" + _component(order_id),
                data={**kwargs, "variety": variety, "order_id": order_id},
            )
        )

    def cancel_order(
        self, variety: str, order_id: str, parent_order_id: str | None = None
    ) -> str:
        self._require_execution()
        return self._order_id(
            self._request(
                "DELETE",
                "/orders/" + _component(variety) + "/" + _component(order_id),
                params={"parent_order_id": parent_order_id},
            )
        )
