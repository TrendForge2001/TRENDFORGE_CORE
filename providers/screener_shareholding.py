"""Conservative Screener.in shareholding fallback for Big Shark enrichment."""

from __future__ import annotations

import calendar
from datetime import datetime
from html.parser import HTMLParser
import re
import time
from typing import Any

import requests


SCREENER_BASE = "https://www.screener.in"
SCREENER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/134.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class _ShareholdingHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._section_depth = 0
        self._in_shareholding = False
        self._table_depth = 0
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._cell_buffer: list[str] = []
        self._row: list[str] = []
        self._table: list[list[str]] = []
        self.tables: list[list[list[str]]] = []

    @staticmethod
    def _attrs(attrs) -> dict[str, str]:
        return {
            str(key).lower(): str(value or "")
            for key, value in attrs
        }

    def handle_starttag(self, tag: str, attrs) -> None:
        name = str(tag).lower()
        values = self._attrs(attrs)

        if name == "section":
            if self._in_shareholding:
                self._section_depth += 1
            elif values.get("id", "").strip().lower() == "shareholding":
                self._in_shareholding = True
                self._section_depth = 1
            return

        if not self._in_shareholding:
            return

        if name == "table":
            if not self._in_table:
                self._in_table = True
                self._table_depth = 1
                self._table = []
            else:
                self._table_depth += 1
            return

        if not self._in_table:
            return

        if name == "tr":
            self._in_row = True
            self._row = []
        elif name in {"th", "td"} and self._in_row:
            self._in_cell = True
            self._cell_buffer = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        name = str(tag).lower()

        if self._in_shareholding and self._in_table:
            if name in {"th", "td"} and self._in_cell:
                text = " ".join(
                    " ".join(self._cell_buffer).split()
                ).strip()
                self._row.append(text)
                self._cell_buffer = []
                self._in_cell = False
                return

            if name == "tr" and self._in_row:
                if any(cell.strip() for cell in self._row):
                    self._table.append(list(self._row))
                self._row = []
                self._in_row = False
                return

            if name == "table":
                self._table_depth -= 1
                if self._table_depth <= 0:
                    if self._table:
                        self.tables.append(list(self._table))
                    self._table = []
                    self._in_table = False
                    self._table_depth = 0
                return

        if name == "section" and self._in_shareholding:
            self._section_depth -= 1
            if self._section_depth <= 0:
                self._in_shareholding = False
                self._section_depth = 0


def _clean_label(value: str) -> str:
    return re.sub(r"[^a-z]+", "", str(value or "").lower())


def _parse_percent(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text in {"-", "--"}:
        return None

    match = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return None

    try:
        number = float(match.group(0))
    except ValueError:
        return None

    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _quarter_date(value: str) -> str | None:
    text = " ".join(str(value or "").split()).strip()
    for fmt in ("%b %Y", "%B %Y"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue

        day = calendar.monthrange(parsed.year, parsed.month)[1]
        return f"{parsed.year:04d}-{parsed.month:02d}-{day:02d}"

    return None


ROW_ALIASES = {
    "promoters": "promoter",
    "promoter": "promoter",
    "fiis": "fii",
    "fii": "fii",
    "fpis": "fii",
    "fpi": "fii",
    "foreigninstitutionalinvestors": "fii",
    "foreignportfolioinvestors": "fii",
    "diis": "dii",
    "dii": "dii",
    "domesticinstitutionalinvestors": "dii",
    "public": "public",
}


def parse_screener_shareholding(html_text: str) -> list[dict[str, Any]]:
    """Parse quarterly source-labelled ownership percentages from Screener."""

    parser = _ShareholdingHTMLParser()
    try:
        parser.feed(str(html_text or ""))
        parser.close()
    except Exception:
        return []

    best: list[dict[str, Any]] = []

    for table in parser.tables:
        if len(table) < 2:
            continue

        header = table[0]
        if len(header) < 3:
            continue

        dates = [_quarter_date(cell) for cell in header[1:]]
        valid_indexes = [
            index for index, value in enumerate(dates, start=1)
            if value is not None
        ]
        if len(valid_indexes) < 2:
            continue

        categories: dict[str, dict[int, float]] = {}
        for row in table[1:]:
            if not row:
                continue
            category = ROW_ALIASES.get(_clean_label(row[0]))
            if not category:
                continue

            values: dict[int, float] = {}
            for index in valid_indexes:
                if index >= len(row):
                    continue
                number = _parse_percent(row[index])
                if number is not None:
                    values[index] = number
            if values:
                categories[category] = values

        if not categories or not (
            "fii" in categories
            or "dii" in categories
            or "promoter" in categories
        ):
            continue

        periods: list[dict[str, Any]] = []
        for index in valid_indexes:
            snapshot: dict[str, Any] = {
                "as_of": dates[index - 1],
            }
            for category, values in categories.items():
                if index in values:
                    snapshot[category] = values[index]
            if len(snapshot) > 1:
                periods.append(snapshot)

        if len(periods) > len(best):
            best = periods

    return best


def build_screener_shareholding_evidence(
    periods: list[dict[str, Any]],
) -> dict[str, Any]:
    if not periods:
        return {}

    dated = [
        row for row in periods
        if isinstance(row, dict) and row.get("as_of")
    ]
    if not dated:
        return {}

    dated.sort(key=lambda row: str(row.get("as_of")))
    latest = dated[-1]
    previous = dated[-2] if len(dated) >= 2 else {}

    snapshot = {
        key: latest.get(key)
        for key in ("promoter", "fii", "dii", "public")
        if latest.get(key) is not None
    }
    if not snapshot:
        return {}

    snapshot.update(
        {
            "source": "SCREENER_SHAREHOLDING",
            "as_of": latest.get("as_of"),
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
                "name": f"Screener {category} aggregate",
                "category": category,
                "holding": current,
                "previous_holding": prior,
                "change": round(float(current) - float(prior), 4),
                "date": latest.get("as_of"),
                "previous_date": previous.get("as_of"),
                "source": "SCREENER_SHAREHOLDING",
            }
        )

    evidence: dict[str, Any] = {
        "shareholding_snapshot": snapshot,
        "holding_changes": changes,
        "_meta": {
            "source": "SCREENER_SHAREHOLDING",
            "periods_parsed": len(dated),
            "latest_as_of": snapshot.get("as_of"),
            "classification_note": (
                "FII/DII/promoter labels are retained exactly from the "
                "published Screener shareholding table; TrendForge does not "
                "infer or relabel investor categories."
            ),
        },
    }

    if latest.get("promoter") is not None:
        evidence["promoter"] = {
            "current": latest.get("promoter"),
            "previous": previous.get("promoter"),
            "holding": latest.get("promoter"),
            "previous_holding": previous.get("promoter"),
            "source": "SCREENER_SHAREHOLDING",
        }

    return evidence


class ScreenerShareholdingProvider:
    """Public Screener shareholding fallback; no authentication or mutations."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: int = 30,
        cache_ttl: int = 21600,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(SCREENER_HEADERS)
        self.timeout = max(1, int(timeout))
        self.cache_ttl = max(0, int(cache_ttl))
        self._cache: dict[
            str,
            tuple[dict[str, Any], float],
        ] = {}
        self._last_success_at: float | None = None
        self._last_error: str | None = None

    def _fresh(self, timestamp: float) -> bool:
        return time.time() - timestamp <= self.cache_ttl

    def get(self, symbol: str) -> dict[str, Any]:
        symbol = str(symbol or "").strip().upper()
        cached = self._cache.get(symbol)
        if cached is not None and self._fresh(cached[1]):
            return dict(cached[0])

        errors: list[str] = []
        for suffix in ("/consolidated/", "/"):
            url = f"{SCREENER_BASE}/company/{symbol}{suffix}"
            try:
                response = self.session.get(
                    url,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
                response.raise_for_status()
                periods = parse_screener_shareholding(response.text)
                evidence = build_screener_shareholding_evidence(periods)
                if evidence:
                    self._cache[symbol] = (evidence, time.time())
                    self._last_success_at = time.time()
                    self._last_error = None
                    return dict(evidence)
                errors.append(f"{url}:shareholding_table_unavailable")
            except Exception as exc:
                errors.append(f"{url}:{exc}")

        self._last_error = "; ".join(errors)
        raise RuntimeError(
            self._last_error
            or f"Screener shareholding unavailable for {symbol}"
        )

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
            "cached_symbols": len(self._cache),
        }


screener_shareholding_provider = ScreenerShareholdingProvider()


__all__ = [
    "ROW_ALIASES",
    "ScreenerShareholdingProvider",
    "build_screener_shareholding_evidence",
    "parse_screener_shareholding",
    "screener_shareholding_provider",
]
