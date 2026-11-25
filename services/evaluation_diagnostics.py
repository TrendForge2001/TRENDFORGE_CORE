"""Small public diagnostic contract; never echoes upstream exception bodies."""

from services.scanner_data_health import MESSAGES


def diagnostics(row):
    state = row.get("data_status")
    code = row.get("data_code")
    state = (
        state
        if state in {"READY", "STALE", "WARMING_UP", "UNAVAILABLE"}
        else "UNAVAILABLE"
    )
    if state == "READY":
        code, reason = (
            "DATA_READY",
            "Completed candle evidence is available for this evaluation.",
        )
    else:
        code = code if code in MESSAGES else "EVALUATION_NOT_RECORDED"
        reason = (
            MESSAGES[code][1]
            if code in MESSAGES
            else (
                "No complete candle evaluation was recorded; run a new scan "
                "or inspect source readiness."
            )
        )
    rating = row.get("institutional_rating") or {}
    rating = rating if isinstance(rating, dict) else {}
    score = row.get("rating_score", rating.get("score"))
    coverage = (
        row.get("rating_data_coverage")
        or rating.get("data_coverage")
        or "NO_TRADE_DATA"
    )
    rating_reason = row.get("rating_reason") or rating.get("reason")
    rating_reason = (
        rating_reason
        if isinstance(rating_reason, str) and rating_reason
        else (
            "Actual institutional buying/selling evidence was not "
            "recorded; no combined score can be calculated."
        )
    )
    ready = type(score) in {int, float} and 0 <= score <= 100
    return [
        {
            "component": "Technical data",
            "status": state,
            "code": code,
            "reason": reason,
            "as_of": row.get("bar_at"),
            "source": row.get("data_source") or "unrecorded",
        },
        {
            "component": "Combined rating",
            "status": "READY" if ready else "UNAVAILABLE",
            "code": "RATING_READY" if ready else "INSTITUTIONAL_EVIDENCE_INCOMPLETE",
            "reason": (
                "The recorded technical and institutional evidence produced this score."
            )
            if ready
            else rating_reason,
            "as_of": row.get("rating_disclosure_time") or rating.get("disclosure_time"),
            "source": coverage,
        },
    ]
