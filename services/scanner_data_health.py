"""Fixed public data diagnostics; upstream bodies and credentials stay private."""

MESSAGES = {
    "KITE_AUTH_REQUIRED": ("UNAVAILABLE", "Kite authentication needs renewal.", False),
    "DATA_RATE_LIMITED": (
        "UNAVAILABLE",
        "The market-data source is rate limited. Retry later.",
        True,
    ),
    "DATA_TEMPORARILY_UNAVAILABLE": (
        "UNAVAILABLE",
        "The candle request timed out or the source is temporarily unavailable.",
        True,
    ),
    "BATCH_RESPONSE_INCOMPLETE": (
        "UNAVAILABLE",
        "The source omitted this stock from its response.",
        True,
    ),
    "SYMBOL_NOT_RESOLVED": (
        "UNAVAILABLE",
        "This NSE symbol could not be resolved to a current instrument.",
        False,
    ),
    "NO_CANDLE_DATA": (
        "UNAVAILABLE",
        "No candle history was returned for this stock.",
        False,
    ),
    "CANDLE_FETCH_FAILED": (
        "UNAVAILABLE",
        "Candle history could not be fetched. Retry or check the instrument.",
        False,
    ),
    "DAILY_WARMUP_NOT_READY": (
        "WARMING_UP",
        "More completed daily candles are required for this strategy.",
        False,
    ),
    "WEEKLY_WARMUP_NOT_READY": (
        "WARMING_UP",
        "This strategy requires 100 completed weekly candles.",
        False,
    ),
    "ANNUAL_REFERENCE_MISSING": (
        "WARMING_UP",
        "Complete previous-year history is required for the annual pivot reference.",
        False,
    ),
    "CANDLES_STALE": ("STALE", "The latest completed market session is missing.", True),
    "CANDLE_HISTORY_INVALID": (
        "UNAVAILABLE",
        "The returned candle history is incomplete or invalid.",
        False,
    ),
}


def detail(code):
    code = code if code in MESSAGES else "CANDLE_FETCH_FAILED"
    status, message, retryable = MESSAGES[code]
    return {
        "data_status": status,
        "data_code": code,
        "data_reason": message,
        "retryable": retryable,
    }


def provider_detail(failure):
    text = str(failure or "").casefold()
    if any(
        p in text
        for p in (
            "tokenexception",
            "authentication",
            "unauthorized",
            "access_token",
            "incorrect api",
            "session expired",
        )
    ):
        code = "KITE_AUTH_REQUIRED"
    elif any(p in text for p in ("429", "too many requests", "rate limit")):
        code = "DATA_RATE_LIMITED"
    elif any(
        p in text
        for p in (
            "timeout",
            "timed out",
            "connection",
            "networkexception",
            "502",
            "503",
            "504",
        )
    ):
        code = "DATA_TEMPORARILY_UNAVAILABLE"
    elif "missing_from_provider_batch" in text:
        code = "BATCH_RESPONSE_INCOMPLETE"
    elif any(
        p in text
        for p in (
            "instrument",
            "symbol not",
            "symbol_not",
            "not found",
            "unknown symbol",
        )
    ):
        code = "SYMBOL_NOT_RESOLVED"
    elif not text or any(
        p in text for p in ("empty", "no data", "no candle", "missing")
    ):
        code = "NO_CANDLE_DATA"
    else:
        code = "CANDLE_FETCH_FAILED"
    return detail(code)


class DataNotReady(ValueError):
    def __init__(self, code):
        self.public = detail(code)
        super().__init__(self.public["data_reason"])
