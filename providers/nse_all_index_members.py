"""Exact-name NSE membership. Missing indices never become another universe."""

import hashlib
import json
import re
import time
from datetime import UTC, datetime

from config.stock_lists import NSE_ALL_INDICES

URL = "https://www.nseindia.com/api/equity-stockIndices"
SOURCE = "NSE_EXACT_INDEX_EQUITY_MEMBERS"


def parse_members(payload, index):
    rows = payload.get("data") if isinstance(payload, dict) else None
    if (
        not isinstance(rows, list)
        or not rows
        or not all(isinstance(row, dict) for row in rows)
    ):
        raise ValueError("NSE constituent response is empty")
    identity = str(payload.get("name") or rows[0].get("symbol") or "").strip().upper()
    if identity != index:
        raise ValueError("NSE returned a different index")
    members = []
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        if symbol == index:
            continue
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9.&-]{0,29}", symbol):
            raise ValueError("NSE returned an invalid constituent")
        meta = row.get("meta") or {}
        if not isinstance(meta, dict):
            raise ValueError("NSE constituent metadata is invalid")
        if meta.get("symbol") and str(meta["symbol"]).strip().upper() != symbol:
            raise ValueError("NSE constituent identity is inconsistent")
        members.append(
            {
                "symbol": symbol,
                "name": meta.get("companyName") or symbol,
                "sector": meta.get("industry") or "Unclassified",
                "exchange": "NSE",
            }
        )
    if (
        not members
        or len(members) > 1000
        or len({m["symbol"] for m in members}) != len(members)
    ):
        raise ValueError("NSE constituent count is invalid")
    advance = payload.get("advance") or {}
    counts = [
        str(advance.get(key, "")) for key in ("advances", "declines", "unchanged")
    ]
    if all(v.isdigit() for v in counts) and sum(map(int, counts)) != len(members):
        raise ValueError("NSE constituent response is incomplete")
    return members


class NSEAllIndexMembers:
    def __init__(self, nse):
        self.session = getattr(nse, "session", None)
        self.cache_dir = getattr(nse, "cache_dir", None)
        self.cache, self.checked, self.retry_after = {}, {}, {}

    def _path(self, index):
        return (
            self.cache_dir
            / ("nse-index-" + hashlib.sha256(index.encode()).hexdigest() + ".json")
            if self.cache_dir
            else None
        )

    def _saved(self, index):
        path = self._path(index)
        if path is None:
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload.get("members") or []
            if payload.get("base_index") != index or payload.get("source") != SOURCE:
                return None
            if (
                not isinstance(rows, list)
                or not 1 <= len(rows) <= 1000
                or not payload.get("fetched_at")
            ):
                return None
            if not all(
                isinstance(row, dict)
                and re.fullmatch(
                    r"[A-Z0-9][A-Z0-9.&-]{0,29}", str(row.get("symbol", ""))
                )
                for row in rows
            ):
                return None
            if len({m["symbol"] for m in rows}) != len(rows):
                return None
            return payload
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def load(self, index):
        if index not in NSE_ALL_INDICES or NSE_ALL_INDICES[index]["kind"] != "equity":
            raise ValueError("This index has no standalone equity constituent list")
        now = time.monotonic()
        if index in self.cache and now - self.checked.get(index, 0) < 600:
            return self.cache[index]
        cached = self.cache.get(index) or self._saved(index)
        if now < self.retry_after.get(index, 0):
            if cached:
                return {
                    **cached,
                    "stale": True,
                    "source_warning": "Using last verified NSE membership",
                }
            raise RuntimeError("NSE constituent membership is temporarily unavailable")
        try:
            response = self.session.get(
                URL, params={"index": index}, timeout=(3, 10), allow_redirects=False
            )
            response.raise_for_status()
            if len(response.content) > 3_000_000:
                raise ValueError("NSE constituent response exceeds size limit")
            payload = {
                "base_index": index,
                "source": SOURCE,
                "source_url": response.url,
                "fetched_at": datetime.now(UTC).isoformat(),
                "stale": False,
                "members": parse_members(response.json(), index),
            }
            path = self._path(index)
            if path:
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_suffix(".tmp")
                temp.write_text(json.dumps(payload), encoding="utf-8")
                temp.replace(path)
            self.cache[index], self.checked[index] = payload, now
            return payload
        except Exception:
            self.retry_after[index] = now + 30
            if cached:
                return {
                    **cached,
                    "stale": True,
                    "source_warning": "Using last verified NSE membership",
                }
            raise RuntimeError(
                "NSE constituent membership is temporarily unavailable"
            ) from None
