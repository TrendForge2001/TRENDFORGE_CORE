"""Execution placement is explicit and independent of broker credentials."""

import os


def cloud_read_only() -> bool:
    return os.getenv("TRENDFORGE_CLOUD_READ_ONLY", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
