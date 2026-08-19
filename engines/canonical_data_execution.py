"""Canonical scanner execution dependencies.

The scanner must score prepared payloads without hidden network/database I/O.
Standalone legacy callers can continue using the original engines directly.
"""
from __future__ import annotations


class PayloadOnlyDependency:
    """Non-fetching dependency used by canonical scanner engine instances."""

    def __getattr__(self, name):
        def _no_fetch(*args, **kwargs):
            return None
        return _no_fetch


PAYLOAD_ONLY = PayloadOnlyDependency()

__all__ = ["PayloadOnlyDependency", "PAYLOAD_ONLY"]
