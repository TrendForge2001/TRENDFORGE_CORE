"""Official BSE Regulation-31 shareholding fallback for Big Shark evidence."""

from __future__ import annotations

from datetime import datetime
from html.parser import HTMLParser
import re
import time
from typing import Any, Callable, Mapping
from urllib.parse import urljoin, urlparse

import requests

from .nse_shareholding import CATEGORY_MEMBERS, PERCENT_FACT


BSE_API_BASE = "https://api.bseindia.com/BseIndiaAPI/api"
BSE_WEB_BASE = "https://www.bseindia.com"

BSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bseindia.com/",
    "Accept": "application/json, text/plain, */*",
}


def _local_name(value: str) -> str:
    text = str(value or "")
    if "}" in text:
        text = text.rsplit("}", 1)[-1]
    if ":" in text:
        text = text.rsplit(":", 1)[-1]
    return text


def _number(value: Any) -> float | None:
    try:
        result = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if result != result or result in {float("inf"), float("-inf")}:
        return None
    return result


def _scale_percentages(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}

    promoter = values.get("promoter")
    public = values.get("public")
    reference: float | None = None

    if promoter is not None and public is not None:
        reference = promoter + public
    else:
        magnitudes = [abs(value) for value in values.values()]
        if magnitudes:
            reference = max(magnitudes)

    scale = 1.0
    if reference is not None:
        if reference > 1000:
            scale = 0.01
        elif 0 < reference < 2:
            scale = 100.0

    return {
        key: round(value * scale, 4)
        for key, value in values.items()
    }


class _InlineXBRLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.context_members: dict[str, set[str]] = {}
        self.facts: list[tuple[str, str, str]] = []
        self._context_id: str | None = None
        self._member_buffer: list[str] | None = None
        self._fact_name: str | None = None
        self._fact_context: str | None = None
        self._fact_buffer: list[str] | None = None

    @staticmethod
    def _attrs(attrs) -> dict[str, str]:
        return {
            str(key).lower(): str(value or "")
            for key, value in attrs
        }

    def handle_starttag(self, tag: str, attrs) -> None:
        local = _local_name(tag).lower()
        values = self._attrs(attrs)

        if local == "context":
            context_id = values.get("id", "").strip()
            self._context_id = context_id or None
            if self._context_id:
                self.context_members.setdefault(self._context_id, set())
            return

        if local == "explicitmember" and self._context_id:
            self._member_buffer = []
            return

        if local == "nonfraction":
            name = values.get("name", "").strip()
            context = (
                values.get("contextref", "")
                or values.get("context-ref", "")
            ).strip()
            if _local_name(name) == PERCENT_FACT and context:
                self._fact_name = name
                self._fact_context = context
                self._fact_buffer = []

    def handle_data(self, data: str) -> None:
        if self._member_buffer is not None:
            self._member_buffer.append(data)
        if self._fact_buffer is not None:
            self._fact_buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        local = _local_name(tag).lower()

        if local == "explicitmember" and self._member_buffer is not None:
            member = _local_name("".join(self._member_buffer).strip())
            if self._context_id and member:
                self.context_members.setdefault(
                    self._context_id,
                    set(),
                ).add(member)
            self._member_buffer = None
            return

        if local == "context":
            self._context_id = None
            self._member_buffer = None
            return

        if local == "nonfraction" and self._fact_buffer is not None:
            value = "".join(self._fact_buffer).strip()
            self.facts.append(
                (
                    self._fact_name or "",
                    self._fact_context or "",
                    value,
                )
            )
            self._fact_name = None
            self._fact_context = None
            self._fact_buffer = None


def parse_shareholding_ixbrl(html_text: str) -> dict[str, float]:
    """Extract aggregate promoter/FII/DII/public percentages from BSE iXBRL."""

    text = str(html_text or "").strip()
    if not text:
        return {}

    parser = _InlineXBRLParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception:
        return {}

    candidates: dict[str, list[tuple[int, float]]] = {
        key: [] for key in CATEGORY_MEMBERS
    }

    for name, context_ref, raw_value in parser.facts:
        if _local_name(name) != PERCENT_FACT:
            continue

        value = _number(raw_value)
        if value is None:
            continue

        members = parser.context_members.get(context_ref, set())
        if not members or len(members) > 2:
            continue

        for category, member_name in CATEGORY_MEMBERS.items():
            if member_name in members:
                candidates[category].append((len(members), value))

    values: dict[str, float] = {}
    for category, rows in candidates.items():
        if not rows:
            continue
        rows.sort(key=lambda item: item[0])
        values[category] = rows[0][1]

    return _scale_percentages(values)


def parse_scripcode_search(response_text: str, symbol: str) -> str | None:
    """Resolve exact BSE scrip code from PeerSmartSearch HTML."""

    symbol = str(symbol or "").strip().upper()
    if not symbol:
        return None

    text = str(response_text or "").replace("&nbsp;", " ")
    patterns = (
        rf"<strong>\s*{re.escape(symbol)}\s*</strong>\s+[A-Z0-9]+\s+(\d{{6}})",
        rf">\s*{re.escape(symbol)}\s*<[^>]*>.*?\b(\d{{6}})\b",
    )

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            return match.group(1)

    return None


def _filing_rows(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, Mapping)]
    if isinstance(value, Mapping):
        for key in ("Table", "data", "rows", "results", "items"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [
                    row for row in nested
                    if isinstance(row, Mapping)
                ]
    return []


def _filing_date(row: Mapping[str, Any]) -> datetime | None:
    value = (
        row.get("date")
        or row.get("EndDate")
        or row.get("DisplayDT")
        or row.get("D")
    )
    if value in (None, ""):
        return None

    text = str(value).strip()
    formats = (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%d-%b-%Y",
        "%d-%m-%Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except ValueError:
        return None


def _filing_url(row: Mapping[str, Any]) -> str | None:
    for key in ("xbrl", "XBRLAttachment", "attachment", "url"):
        value = row.get(key)
        if not isinstance(value, str) or not value.strip():
            continue

        candidate = value.strip()
        if candidate.startswith("/"):
            candidate = urljoin(BSE_WEB_BASE, candidate)
        if "xbrl" in candidate.lower() or candidate.lower().endswith(".html"):
            return candidate

    return None


def build_bse_shareholding_evidence(
    filings: Any,
    fetch_document: Callable[[str], str],
    *,
    max_filings: int = 5,
) -> tuple[dict[str, Any], list[str]]:
    """Build Big Shark ownership evidence from official BSE Reg-31 iXBRL."""

    rows = _filing_rows(filings)
    rows.sort(
        key=lambda row: _filing_date(row) or datetime.min,
        reverse=True,
    )

    parsed: list[tuple[Mapping[str, Any], dict[str, float]]] = []
    errors: list[str] = []

    for row in rows[: max(1, int(max_filings))]:
        url = _filing_url(row)
        if not url:
            continue

        try:
            facts = parse_shareholding_ixbrl(fetch_document(url))
        except Exception as exc:
            errors.append(f"ixbrl:{exc}")
            continue

        if facts:
            parsed.append((row, facts))
        if len(parsed) >= 2:
            break

    if not parsed:
        return {}, errors

    latest_row, latest = parsed[0]
    previous_row, previous = (
        parsed[1] if len(parsed) > 1 else ({}, {})
    )
    latest_date = _filing_date(latest_row)
    previous_date = _filing_date(previous_row)

    snapshot = {
        key: latest.get(key)
        for key in ("promoter", "fii", "dii", "public", "noninst")
        if latest.get(key) is not None
    }
    snapshot.update(
        {
            "source": "BSE_REG31_IXBRL",
            "as_of": (
                latest_date.date().isoformat()
                if latest_date is not None
                else str(latest_row.get("EndDate") or "")
            ),
        }
    )

    changes: list[dict[str, Any]] = []
    for key, category in (
        ("promoter", "PROMOTER"),
        ("fii", "FII"),
        ("dii", "DII"),
    ):
        current = latest.get(key)
        prior = previous.get(key)
        if current is None or prior is None:
            continue

        changes.append(
            {
                "name": f"BSE {category} aggregate",
                "category": category,
                "holding": current,
                "previous_holding": prior,
                "change": round(current - prior, 4),
                "date": (
                    latest_date.date().isoformat()
                    if latest_date is not None
                    else None
                ),
                "previous_date": (
                    previous_date.date().isoformat()
                    if previous_date is not None
                    else None
                ),
                "source": "BSE_REG31_IXBRL",
            }
        )

    evidence: dict[str, Any] = {
        "shareholding_snapshot": snapshot,
        "holding_changes": changes,
    }

    promoter_current = latest.get("promoter")
    promoter_previous = previous.get("promoter")
    if promoter_current is not None:
        evidence["promoter"] = {
            "current": promoter_current,
            "previous": promoter_previous,
            "holding": promoter_current,
            "previous_holding": promoter_previous,
            "source": "BSE_REG31_IXBRL",
        }

    evidence["_meta"] = {
        "source": "BSE_REG31_IXBRL",
        "filings_parsed": len(parsed),
        "latest_as_of": snapshot.get("as_of"),
    }
    return evidence, errors


class BSEShareholdingProvider:
    """Minimal BSE client for Reg-31 shareholding fallback."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: int = 30,
        cache_ttl: int = 21600,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(BSE_HEADERS)
        self.timeout = max(1, int(timeout))
        self.cache_ttl = max(0, int(cache_ttl))
        self._scrip_cache: dict[str, tuple[str, float]] = {}
        self._filing_cache: dict[str, tuple[list[dict[str, Any]], float]] = {}
        self._document_cache: dict[str, tuple[str, float]] = {}
        self._last_error: str | None = None
        self._last_success_at: float | None = None

    def _fresh(self, timestamp: float) -> bool:
        return time.time() - timestamp <= self.cache_ttl

    def resolve_scripcode(self, symbol: str) -> str:
        symbol = str(symbol or "").strip().upper()
        cached = self._scrip_cache.get(symbol)
        if cached is not None and self._fresh(cached[1]):
            return cached[0]

        response = self.session.get(
            f"{BSE_API_BASE}/PeerSmartSearch/w",
            params={"Type": "SS", "text": symbol},
            timeout=self.timeout,
        )
        response.raise_for_status()

        code = parse_scripcode_search(response.text, symbol)
        if not code:
            self._last_error = f"BSE scrip code unavailable for {symbol}"
            raise RuntimeError(self._last_error)

        self._scrip_cache[symbol] = (code, time.time())
        self._last_success_at = time.time()
        self._last_error = None
        return code

    def shareholding_filings(self, symbol: str) -> list[dict[str, Any]]:
        symbol = str(symbol or "").strip().upper()
        cached = self._filing_cache.get(symbol)
        if cached is not None and self._fresh(cached[1]):
            return list(cached[0])

        code = self.resolve_scripcode(symbol)
        response = self.session.get(
            f"{BSE_API_BASE}/Corp_Shareholding_ng/w",
            params={
                "scripcode": code,
                "flag": "0",
                "indtype": "",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()

        content_type = str(
            response.headers.get("Content-Type") or ""
        ).lower()
        if "html" in content_type:
            raise RuntimeError(
                "BSE shareholding endpoint returned HTML instead of JSON"
            )

        data = response.json()
        rows = _filing_rows(data)
        normalized: list[dict[str, Any]] = []

        for row in rows:
            attachment = str(row.get("XBRLAttachment") or "").strip()
            is_xbrl = row.get("IsXBRL")
            if not attachment or str(is_xbrl).strip() in {"0", "False", "false"}:
                continue

            normalized.append(
                {
                    **dict(row),
                    "date": row.get("EndDate") or row.get("DisplayDT"),
                    "xbrl": urljoin(BSE_WEB_BASE, attachment),
                    "bse_scripcode": code,
                }
            )

        self._filing_cache[symbol] = (normalized, time.time())
        self._last_success_at = time.time()
        self._last_error = None
        return list(normalized)

    def public_document(self, url: str) -> str:
        url = str(url or "").strip()
        cached = self._document_cache.get(url)
        if cached is not None and self._fresh(cached[1]):
            return cached[0]

        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme not in {"http", "https"}
            or host not in {"www.bseindia.com", "bseindia.com"}
            or not parsed.path.lower().startswith("/xbrlfiles/")
        ):
            raise ValueError(
                "BSE shareholding document URL is outside the allowed XBRL host/path"
            )

        response = self.session.get(
            url,
            timeout=max(self.timeout, 60),
            allow_redirects=True,
        )
        response.raise_for_status()
        text = str(response.text or "").strip()
        if not text:
            raise RuntimeError("BSE iXBRL filing returned an empty document")

        self._document_cache[url] = (text, time.time())
        self._last_success_at = time.time()
        self._last_error = None
        return text

    def health(self) -> dict[str, Any]:
        return {
            "status": (
                "runtime_verified"
                if self._last_success_at is not None
                else "degraded"
                if self._last_error
                else "configured"
            ),
            "provider": self.__class__.__name__,
            "network_probe": False,
            "last_error": self._last_error,
            "last_success_at_epoch": self._last_success_at,
            "cached_symbols": len(self._scrip_cache),
            "cached_filings": len(self._filing_cache),
            "cached_documents": len(self._document_cache),
        }


bse_shareholding_provider = BSEShareholdingProvider()


__all__ = [
    "BSEShareholdingProvider",
    "BSE_HEADERS",
    "build_bse_shareholding_evidence",
    "bse_shareholding_provider",
    "parse_scripcode_search",
    "parse_shareholding_ixbrl",
]
