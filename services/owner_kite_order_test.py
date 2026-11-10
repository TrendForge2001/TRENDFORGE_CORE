"""Explicit operator-configured, durable, one-shot CNC order; no automation opt-in."""

import hashlib
import json
import logging
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from core.storage_config import resolve_storage, storage_health
from providers.kite_errors import (
    InputException,
    NetworkException,
    OrderException,
    PermissionException,
    TokenException,
)

ENV = "TRENDFORGE_OWNER_KITE_ORDER_TEST"
TZ = ZoneInfo("Asia/Kolkata")
LOG = logging.getLogger(__name__)


class OwnerIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,64}$")
    symbol: Literal["SBIN"]
    quantity: StrictInt = Field(ge=5, le=5)
    variety: Literal["regular", "amo"] = "regular"
    accept_execution: StrictBool
    expires_at: datetime


def _connect(database):
    return sqlite3.connect(
        Path(database).resolve().as_uri() + "?mode=rw", uri=True, timeout=10
    )


def _save(database, key, receipt):
    with closing(_connect(database)) as connection:
        connection.execute(
            "UPDATE settings SET value=? WHERE key=?",
            (json.dumps(receipt, allow_nan=False), key),
        )
        connection.commit()


def _reconcile(client, receipt):
    order_id = receipt.get("order_id")
    if not order_id:
        matches = [
            row
            for row in client.orders()
            if row.get("tag") == receipt["tag"]
            and row.get("tradingsymbol") == receipt["symbol"]
            and row.get("transaction_type") == "BUY"
            and row.get("product") == "CNC"
            and row.get("quantity") == receipt["quantity"]
        ]
        if len(matches) != 1:
            return receipt
        order_id = matches[0].get("order_id")
    if not isinstance(order_id, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{1,64}", order_id
    ):
        return receipt
    receipt["order_id"] = order_id
    receipt["status"] = "accepted"
    rows = client.order_history(order_id)
    if rows:
        row = rows[-1]
        status = row.get("status")
        if isinstance(status, str) and re.fullmatch(r"[A-Z _]{1,40}", status):
            receipt["broker_status"] = status
        for field in ("filled_quantity", "pending_quantity"):
            if type(row.get(field)) is int and 0 <= row[field] <= receipt["quantity"]:
                receipt[field] = row[field]
    return receipt


def submit_once(intent, *, database, factory, clock=lambda: datetime.now(TZ)):
    """Claim before I/O. A crash/timeout never permits a second order POST."""
    intent = OwnerIntent.model_validate(intent)
    if intent.accept_execution is not True or ".." in intent.symbol:
        raise ValueError("Explicit execution acceptance and an NSE symbol are required")
    if intent.expires_at.tzinfo is None:
        raise ValueError("Order-test expiry requires an explicit timezone")
    now = clock().astimezone(TZ)
    expiry = intent.expires_at.astimezone(TZ)
    if expiry.date() != now.date():
        raise ValueError("This order test must expire today in IST")
    if intent.variety == "regular" and expiry.time().isoformat() > "09:15:00":
        raise ValueError("This regular test expires by 09:15 IST today")
    if intent.variety == "amo" and (expiry - now).total_seconds() > 3600:
        raise ValueError("An AMO test submission expires within one hour")
    payload = intent.model_dump(mode="json")
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    key = "kite.owner_order_test.once." + intent.intent_id
    receipt = {
        "intent_id": intent.intent_id,
        "intent_sha256": digest,
        "symbol": intent.symbol,
        "quantity": intent.quantity,
        "side": "BUY",
        "product": "CNC",
        "order_type": "MARKET",
        "variety": intent.variety,
        "market_protection": -1,
        "validity": "DAY",
        "tag": "TF" + digest[:16],
        "status": "reserved",
        "submit_attempts": 0,
        "created_at": now.isoformat(),
    }
    with closing(_connect(database)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        previous = connection.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        if previous is not None:
            saved = json.loads(previous[0])
            if saved.get("intent_sha256") != digest:
                raise ValueError("This intent ID already belongs to another request")
            return {**saved, "duplicate_blocked": True}
        if now >= expiry:
            return {**receipt, "status": "expired"}
        connection.execute(
            "INSERT INTO settings(key,value) VALUES (?,?)", (key, json.dumps(receipt))
        )
        connection.commit()

    used = False

    def permit_once():
        nonlocal used
        if used or receipt["status"] != "submitting":
            raise RuntimeError("No further broker mutations are authorized")
        used = True

    try:
        client = factory(permit_once)
        client.profile()
        instruments = {
            row.get("tradingsymbol"): row
            for row in client.instruments("NSE")
            if row.get("exchange") == "NSE" and row.get("instrument_type") == "EQ"
        }
        instrument = instruments.get(intent.symbol)
        if (
            instrument is None
            or type(instrument.get("lot_size")) is not int
            or instrument["lot_size"] <= 0
            or intent.quantity % instrument["lot_size"]
        ):
            receipt.update(
                status="preflight_blocked", code="NSE_EQUITY_OR_LOT_UNAVAILABLE"
            )
        elif clock().astimezone(TZ) >= expiry:
            receipt.update(status="expired")
        else:
            receipt.update(status="submitting", submit_attempts=1)
            _save(database, key, receipt)
            try:
                order_id = client.place_order(
                    variety=intent.variety,
                    exchange="NSE",
                    tradingsymbol=intent.symbol,
                    transaction_type="BUY",
                    quantity=intent.quantity,
                    product="CNC",
                    order_type="MARKET",
                    validity="DAY",
                    market_protection=-1,
                    tag=receipt["tag"],
                )
                if not isinstance(order_id, str) or not re.fullmatch(
                    r"[A-Za-z0-9_-]{1,64}", order_id
                ):
                    raise ValueError("Invalid order acknowledgement")
                receipt.update(order_id=order_id, status="accepted")
            except (
                InputException,
                OrderException,
                PermissionException,
                TokenException,
            ) as error:
                receipt.update(
                    status="broker_rejected" if 400 <= error.code < 500 else "unknown",
                    code=type(error).__name__,
                    http_status=error.code,
                )
                receipt["reason"] = (
                    _rejection_reason(error)
                    if 400 <= error.code < 500
                    else "BROKER_SERVER_OUTCOME_UNKNOWN"
                )
            except NetworkException:
                receipt.update(status="unknown", code="TRANSPORT_OUTCOME_UNKNOWN")
            except Exception:
                receipt.update(status="unknown", code="ORDER_OUTCOME_UNKNOWN")
            if receipt["status"] in {"accepted", "unknown"}:
                try:
                    receipt = _reconcile(client, receipt)
                except Exception:
                    receipt["reconciliation"] = "unavailable_check_kite_orders"
    except Exception:
        receipt.update(
            status="unknown" if receipt["submit_attempts"] else "preflight_blocked",
            code="CHECK_RECEIPT_AND_KITE_ORDERS"
            if receipt["submit_attempts"]
            else "SESSION_OR_INSTRUMENT_CHECK_FAILED",
        )
    receipt["updated_at"] = clock().astimezone(TZ).isoformat()
    _save(database, key, receipt)
    return receipt


def _rejection_reason(error):
    """Classify known broker messages without logging their private contents."""
    message = str(error).lower()
    if re.search(r"\bip(?:v[46])?\b", message) and any(
        word in message for word in ("whitelist", "allowlist", "static", "registered")
    ):
        return "IP_NOT_AUTHORIZED"
    if "market_protection" in message or "market protection" in message:
        return "MARKET_PROTECTION_REQUIRED"
    if ("amo" in message or "after market" in message) and any(
        word in message for word in ("window", "between", "timing", "market hours")
    ):
        return "AMO_WINDOW_NOT_ALLOWED"
    if "market" in message and any(
        word in message for word in ("closed", "not open", "holiday")
    ):
        return "MARKET_CLOSED"
    if "insufficient" in message and any(
        word in message for word in ("fund", "margin")
    ):
        return "INSUFFICIENT_FUNDS"
    return (
        "BROKER_PERMISSION_DENIED"
        if isinstance(error, PermissionException)
        else "BROKER_REJECTION"
    )


def run_configured_order_test():
    raw = os.getenv(ENV, "")
    if not raw:
        return None
    if (
        len(raw) > 2048
        or os.getenv("RENDER") != "true"
        or storage_health().get("verified_persistent") is not True
    ):
        raise ValueError("The owner order test requires the verified Render book")
    from core.kite_environment import resolve_kite_environment
    from providers.kite_rest_client import KiteRESTClient

    credentials = resolve_kite_environment().values

    def factory(guard):
        client = KiteRESTClient(
            api_key=credentials["KITE_API_KEY"], execution_guard=guard
        )
        client.set_access_token(credentials["KITE_ACCESS_TOKEN"])
        return client

    receipt = submit_once(
        json.loads(raw), database=str(resolve_storage().database), factory=factory
    )
    LOG.warning("owner_kite_order_test %s", json.dumps(receipt, sort_keys=True))
    return receipt
