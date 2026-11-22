"""Bounded public company facts for display, independent of scanner scoring."""

import calendar
import math
import re
import threading
import time
from collections import OrderedDict
from copy import deepcopy
from datetime import date
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from providers.screener_shareholding import SCREENER_HEADERS

BASE = "https://www.screener.in"


def number(value):
    text = str("" if value is None else value).replace(",", "").replace("%", "").strip()
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return None
    result = float(text)
    return result if math.isfinite(result) else None


def period_end(label):
    from datetime import datetime

    for fmt in ("%b %Y", "%B %Y"):
        try:
            value = datetime.strptime(label.strip(), fmt)
            return date(
                value.year, value.month, calendar.monthrange(value.year, value.month)[1]
            )
        except ValueError:
            pass
    return None


def table(section):
    if section is None:
        return []
    return [
        [" ".join(cell.stripped_strings).strip(" +") for cell in row.select("th,td")]
        for row in section.select("table tr")
    ]


def statement(section, today):
    if section is None or not re.search(
        r"(?:Rs\.?|₹|INR)\s*(?:in\s*)?Crores", section.get_text(" "), re.I
    ):
        return []
    rows = table(section)
    if not rows:
        return []
    labels = {row[0].casefold(): row for row in rows[1:] if row}
    revenue = next(
        (labels[key] for key in ("sales", "revenue", "total income") if key in labels),
        [],
    )
    profit = labels.get("net profit", [])
    result = []
    for i, label in enumerate(rows[0][1:], 1):
        end = period_end(label)
        if end is None or end > today:
            continue
        result.append(
            {
                "period": label,
                "period_end": end.isoformat(),
                "revenue_cr": number(revenue[i]) if i < len(revenue) else None,
                "net_profit_cr": number(profit[i]) if i < len(profit) else None,
            }
        )
    return result[-8:]


def ownership(section, today):
    rows = table(section)
    if not rows:
        return []
    categories = {
        "promoters": "Promoters",
        "fiis": "FII",
        "diis": "DII",
        "government": "Government",
        "public": "Public",
        "others": "Others",
    }
    result = []
    for i, label in enumerate(rows[0][1:], 1):
        end = period_end(label)
        if end is None or end > today:
            continue
        values = []
        for row in rows[1:]:
            name = categories.get(row[0].casefold()) if row else None
            value = number(row[i]) if i < len(row) else None
            if name and value is not None and 0 <= value <= 100:
                values.append({"category": name, "percent": value})
        total = sum(v["percent"] for v in values)
        result.append(
            {
                "period": label,
                "period_end": end.isoformat(),
                "categories": values,
                "total_percent": round(total, 4),
                "complete": bool(values) and abs(total - 100) <= 0.1,
            }
        )
    return result[-8:]


def parse_company_page(html, *, symbol, url, today=None):
    today = today or date.today()
    soup = BeautifulSoup(html, "html.parser")
    metrics = {}
    aliases = {
        "stock p/e": "pe",
        "dividend yield": "dividend_yield_pct",
        "market cap": "market_cap_cr",
        "roe": "roe_pct",
        "roce": "roce_pct",
    }
    for row in soup.select("#top-ratios li"):
        label = row.select_one(".name")
        value = row.select_one(".number")
        key = (
            aliases.get(" ".join(label.stripped_strings).casefold()) if label else None
        )
        if key and value:
            parsed = number(value.get_text())
            if key == "market_cap_cr" and not re.search(
                r"\bCr\.?\b", row.get_text(" "), re.I
            ):
                continue
            if parsed is not None:
                metrics[key] = parsed
    name = soup.find("h1")
    if name is None or soup.select_one("#top-ratios") is None:
        raise ValueError("Unsupported company document")
    return {
        "status": "available",
        "symbol": symbol,
        "company_name": name.get_text(" ", strip=True) if name else symbol,
        "source": "Screener.in",
        "source_url": url,
        "reporting_basis": "Consolidated" if "/consolidated/" in url else "Standalone",
        "metrics": metrics,
        "annual": statement(soup.find(id="profit-loss"), today),
        "quarterly": statement(soup.find(id="quarters"), today),
        "shareholding": ownership(soup.find(id="shareholding"), today),
        "facts_as_of": None,
        "used_for_strategy_scoring": False,
    }


class CompanyReportProvider:
    """Cache public facts only. No private portfolio is sent to this source."""

    def __init__(self, *, session=None, ttl=3600):
        self.session = session or requests.Session()
        self.ttl = ttl
        self._cache = OrderedDict()
        self._lock = threading.Lock()

    def get(self, symbol, *, today=None):
        from datetime import UTC, datetime

        if not re.fullmatch(r"[A-Z0-9][A-Z0-9&._-]{0,29}", symbol) or ".." in symbol:
            raise ValueError("Invalid NSE symbol")
        with self._lock:
            cached = self._cache.get(symbol)
            if cached and time.monotonic() - cached[0] < self.ttl:
                return deepcopy(cached[1])
            url = BASE + "/company/" + quote(symbol, safe="") + "/consolidated/"
            try:
                response = self.session.get(
                    url,
                    timeout=12,
                    headers=SCREENER_HEADERS,
                    allow_redirects=False,
                )
                if response.status_code == 404:
                    url = BASE + "/company/" + quote(symbol, safe="") + "/"
                    response = self.session.get(
                        url,
                        timeout=12,
                        headers=SCREENER_HEADERS,
                        allow_redirects=False,
                    )
                if response.status_code != 200 or len(response.content) > 3_000_000:
                    raise ValueError("Source unavailable")
                result = parse_company_page(
                    response.text, symbol=symbol, url=url, today=today
                )
                result["fetched_at"] = datetime.now(UTC).isoformat()
            except (requests.RequestException, ValueError):
                return {
                    "status": "unavailable",
                    "code": "COMPANY_SOURCE_UNAVAILABLE",
                    "source": "Screener.in",
                    "source_url": url,
                    "metrics": {},
                    "annual": [],
                    "quarterly": [],
                    "shareholding": [],
                }
            self._cache[symbol] = (time.monotonic(), deepcopy(result))
            self._cache.move_to_end(symbol)
            while len(self._cache) > 32:
                self._cache.popitem(last=False)
            return result
