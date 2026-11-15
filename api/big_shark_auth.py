"""A provider feed credential can ingest trades but cannot read owner data."""

import os
import secrets

from fastapi import HTTPException, Request

from api.admin_auth import ADMIN_API_KEY_HEADER, validate_admin_api_key

FEED_HEADER = "X-TrendForge-Feed-Key"
FEED_PATH = "/institutional/big-shark/trades/feed"


def require_big_shark_access(request: Request):
    supplied = request.headers.get(FEED_HEADER)
    if request.method == "POST" and request.url.path == FEED_PATH and supplied:
        expected = os.getenv("TRENDFORGE_BIG_SHARK_FEED_KEY", "").strip()
        admin = os.getenv("TRENDFORGE_ADMIN_API_KEY", "").strip()
        if len(expected) < 32 or secrets.compare_digest(
            expected.encode(), admin.encode()
        ):
            raise HTTPException(
                503, "A distinct, strong Big Shark feed key is not configured."
            )
        if not secrets.compare_digest(supplied.encode(), expected.encode()):
            raise HTTPException(401, "Invalid Big Shark feed key.")
        return
    validate_admin_api_key(request.headers.get(ADMIN_API_KEY_HEADER))
