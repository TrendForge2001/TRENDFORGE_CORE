"""Bounded public disclosures. Owner portfolios and credentials never leave the app."""

import calendar
import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from services.big_shark_activity import MAX_RECORDS, TZ, normalise_records, parse_csv

MONEYCONTROL = "https://www.moneycontrol.com/india-investors-portfolio/"
HOLDINGS = MONEYCONTROL + "top-stocks-bought-sold"
NSE_REPORT = "https://www.nseindia.com/report-detail/display-bulk-and-block-deals"
HOSTS = frozenset(
    {
        "www.moneycontrol.com",
        "www.nseindia.com",
        "www.nseindia.in",
        "nsearchives.nseindia.com",
        "archives.nseindia.com",
    }
)
MAX_BYTES = 3 * 1024 * 1024
ERROR_CODES = frozenset(
    {
        "SOURCE_UNAVAILABLE",
        "SOURCE_NUMBER_INVALID",
        "SOURCE_QUANTITY_INVALID",
        "SOURCE_PERCENT_INVALID",
        "SOURCE_TOO_LARGE",
        "SOURCE_TOO_MANY_ROWS",
        "MONEYCONTROL_CATALOG_UNAVAILABLE",
        "MONEYCONTROL_HOLDINGS_UNAVAILABLE",
        "NSE_RESPONSE_INVALID",
        "NSE_RESPONSE_TRUNCATED",
        "NSE_RECORD_INVALID",
        "SOURCE_URL_REJECTED",
        "SOURCE_ACCESS_UNAVAILABLE",
        "SOURCE_NETWORK_UNAVAILABLE",
        "SOURCE_REDIRECT_REJECTED",
        "SOURCE_NOT_SUPPORTED",
        "NSE_ARCHIVE_INVALID",
        "NSE_REPORT_OUTSIDE_WINDOW",
        "REFRESH_ALREADY_RUNNING",
    }
)


class PublicFeedError(ValueError):
    """Only fixed codes may cross the API/log boundary."""

    def __init__(self, code):
        self.code = code if code in ERROR_CODES else "SOURCE_UNAVAILABLE"
        super().__init__(self.code)


def _text(value):
    return " ".join(str(value or "").split())[:300]


def _number(value, *, integer=False, percent=False):
    raw = _text(value).replace(",", "").replace("₹", "").replace("%", "").strip()
    if raw in {"", "-", "--", "NA", "N/A"}:
        return None
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", raw):
        raise PublicFeedError("SOURCE_NUMBER_INVALID")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise PublicFeedError("SOURCE_NUMBER_INVALID") from None
    if not value.is_finite() or abs(value) > Decimal("1e15"):
        raise PublicFeedError("SOURCE_NUMBER_INVALID")
    if integer and (value < 0 or value != value.to_integral_value()):
        raise PublicFeedError("SOURCE_QUANTITY_INVALID")
    if percent and not 0 <= value <= 100:
        raise PublicFeedError("SOURCE_PERCENT_INVALID")
    return int(value) if integer else float(value)


def _soup(data):
    if len(data) > MAX_BYTES:
        raise PublicFeedError("SOURCE_TOO_LARGE")
    soup = BeautifulSoup(data, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup


def parse_moneycontrol_catalog(data):
    soup = _soup(data)
    investors = {}
    for heading in soup.find_all(["h2", "h3", "h4"]):
        link = heading.find("a", href=True)
        if link is None:
            continue
        url = urljoin(MONEYCONTROL, link["href"])
        path = urlsplit(url).path
        if (
            urlsplit(url).netloc != "www.moneycontrol.com"
            or not re.fullmatch(r"/india-investors-portfolio/[a-z0-9-]+/?", path)
            or "top-stocks" in path
        ):
            continue
        name = _text(link.get_text(" ", strip=True))
        if not name:
            continue
        category = heading.find_previous("h2")
        category = _text(category.get_text(" ", strip=True)) if category else "Unknown"
        if "institutional" in category.casefold():
            category = "Institutional"
        elif "fii" in category.casefold():
            category = "FII"
        elif "individual" in category.casefold():
            category = "Individual"
        else:
            category = "Unknown"
        container = heading.find_parent("tr") or heading.parent
        count = re.search(
            r"Company\s+Holdings\s*:\s*([\d,]+)",
            container.get_text(" ", strip=True),
            re.I,
        )
        cells = container.find_all("td", recursive=False)
        try:
            networth = (
                _number(cells[-1].get_text(" ", strip=True)) if len(cells) > 1 else None
            )
        except PublicFeedError:
            networth = None
        investors[name.casefold()] = {
            "investor_name": name,
            "category": category,
            "url": url,
            "company_holdings": int(count[1].replace(",", "")) if count else None,
            "networth_cr": networth,
        }
    if not investors or len(investors) > 1000:
        raise PublicFeedError("MONEYCONTROL_CATALOG_UNAVAILABLE")
    return list(investors.values())


def parse_moneycontrol_holdings(data, *, now):
    soup = _soup(data)
    label = re.search(
        r"as\s+on\s+quarter\s+(Mar(?:ch)?|Jun(?:e)?|Sep(?:tember)?|Dec(?:ember)?)\s+(20\d{2})",
        soup.get_text(" ", strip=True),
        re.I,
    )
    period, end, status = None, None, "UNKNOWN"
    if label:
        month = {"mar": 3, "jun": 6, "sep": 9, "dec": 12}[label[1][:3].lower()]
        year = int(label[2])
        end = datetime(year, month, calendar.monthrange(year, month)[1]).date()
        period = f"{year}-Q{month // 3}"
        status = (
            "COMPLETED_QUARTER"
            if end < now.astimezone(TZ).date()
            else "OPEN_OR_FUTURE_QUARTER"
        )
    rows = []
    for table in soup.find_all("table"):
        headers = None
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"], recursive=False)
            values = [_text(c.get_text(" ", strip=True)) for c in cells]
            normalized = [re.sub(r"[^a-z0-9]", "", v.casefold()) for v in values]
            if {"stockname", "investorname", "quantityheld"}.issubset(normalized):
                headers = normalized
                continue
            if not headers or len(values) < len(headers):
                continue
            raw = dict(zip(headers, values, strict=False))
            if not raw.get("stockname") or not raw.get("investorname"):
                continue
            action = raw.get("action", "UNKNOWN").upper()
            rows.append(
                {
                    "stock_name": raw["stockname"],
                    "investor_name": raw["investorname"],
                    "reported_action": action,
                    "holding_percent": _number(raw.get("holding"), percent=True),
                    "reported_change": raw.get("changefromprevqtr"),
                    "holding_value_cr": _number(raw.get("holdingvaluecrs")),
                    "quantity_held": _number(raw.get("quantityheld"), integer=True),
                    "reporting_period": period,
                    "disclosed_at": None,
                    "source_url": HOLDINGS,
                    "is_actual_trade": False,
                }
            )
            if len(rows) > MAX_RECORDS:
                raise PublicFeedError("SOURCE_TOO_MANY_ROWS")
    if not rows:
        raise PublicFeedError("MONEYCONTROL_HOLDINGS_UNAVAILABLE")
    unique = {json.dumps(row, sort_keys=True): row for row in rows}
    return {
        "rows": list(unique.values()),
        "reporting_period": period,
        "period_status": status,
        "source_url": HOLDINGS,
        "coverage": "VISIBLE_PUBLIC_ROWS_ONLY",
        "disclosure_time_basis": "UNKNOWN",
        "holding_changes_are_trade_quantities": False,
    }


def parse_nse_deals(data, *, now):
    try:
        payload = json.loads(data)
    except (ValueError, UnicodeError):
        raise PublicFeedError("NSE_RESPONSE_INVALID") from None
    if isinstance(payload, dict):
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise PublicFeedError("NSE_RESPONSE_INVALID")
        count = payload.get("totalRecords", payload.get("total_records"))
        if count is not None:
            if type(count) not in (str, int) or not str(count).isdigit():
                raise PublicFeedError("NSE_RESPONSE_INVALID")
            if int(count) != len(rows):
                raise PublicFeedError("NSE_RESPONSE_TRUNCATED")
    else:
        rows = payload
    if not isinstance(rows, list) or len(rows) > MAX_RECORDS:
        raise PublicFeedError("NSE_RESPONSE_INVALID")
    if not rows:
        return []
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise PublicFeedError("NSE_RESPONSE_INVALID")
        result.append(
            {
                "trade_date": row.get("BD_DT_DATE"),
                "symbol": row.get("BD_SYMBOL"),
                "stock_name": row.get("BD_SCRIP_NAME"),
                "investor_name": row.get("BD_CLIENT_NAME"),
                "side": row.get("BD_BUY_SELL"),
                "quantity": row.get("BD_QTY_TRD"),
                "price": row.get("BD_TP_WATP"),
                # BD_DT_ORDER is a sort/trade-date field, not a publication timestamp.
                "disclosed_at": None,
            }
        )
    try:
        return normalise_records(result, now=now)[0]
    except (ValueError, TypeError):
        raise PublicFeedError("NSE_RECORD_INVALID") from None


class BigSharkPublicProvider:
    def __init__(self, session=None):
        self.session = session or requests.Session()

    def _get(self, url):
        for _ in range(3):
            try:
                parsed = urlsplit(url)
                port = parsed.port
            except ValueError:
                raise PublicFeedError("SOURCE_URL_REJECTED") from None
            if (
                parsed.scheme != "https"
                or parsed.hostname not in HOSTS
                or port not in (None, 443)
                or parsed.username
                or parsed.password
            ):
                raise PublicFeedError("SOURCE_URL_REJECTED")
            try:
                response = self.session.get(
                    url,
                    timeout=(4, 8),
                    stream=True,
                    allow_redirects=False,
                    headers={
                        "User-Agent": "TrendForgePublicDisclosureReader/1.0",
                        "Accept": "text/html,application/json,text/csv",
                    },
                )
                with response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        url = urljoin(url, response.headers.get("Location", ""))
                        continue
                    if response.status_code in {401, 403, 429}:
                        raise PublicFeedError("SOURCE_ACCESS_UNAVAILABLE")
                    response.raise_for_status()
                    data = bytearray()
                    for chunk in response.iter_content(65536):
                        data.extend(chunk)
                        if len(data) > MAX_BYTES:
                            raise PublicFeedError("SOURCE_TOO_LARGE")
                    return bytes(data), url
            except requests.RequestException:
                raise PublicFeedError("SOURCE_NETWORK_UNAVAILABLE") from None
        raise PublicFeedError("SOURCE_REDIRECT_REJECTED")

    def holdings(self, *, now):
        catalog, _ = self._get(MONEYCONTROL)
        holdings, _ = self._get(HOLDINGS)
        return {
            **parse_moneycontrol_holdings(holdings, now=now),
            "investors": parse_moneycontrol_catalog(catalog),
            "document_sha256": hashlib.sha256(catalog + holdings).hexdigest(),
        }

    def trades(self, *, source, start, end, now):
        if source not in {"NSE_BULK", "NSE_BLOCK"}:
            raise PublicFeedError("SOURCE_NOT_SUPPORTED")
        option = "bulk_deals" if source == "NSE_BULK" else "block_deals"
        url = (
            "https://www.nseindia.com/api/historicalOR/bulk-block-short-deals?"
            + urlencode(
                {
                    "optionType": option,
                    "from": start.strftime("%d-%m-%Y"),
                    "to": end.strftime("%d-%m-%Y"),
                }
            )
        )
        try:
            _, report_url = self._get(NSE_REPORT)
            origin = urlsplit(report_url)
            if origin.hostname not in {"www.nseindia.com", "www.nseindia.in"}:
                raise PublicFeedError("SOURCE_URL_REJECTED")
            url = (
                origin.scheme
                + "://"
                + origin.netloc
                + "/api/historicalOR/bulk-block-short-deals?"
                + urlencode(
                    {
                        "optionType": option,
                        "from": start.strftime("%d-%m-%Y"),
                        "to": end.strftime("%d-%m-%Y"),
                    }
                )
            )
            data, actual_url = self._get(url)
            rows = parse_nse_deals(data, now=now)
            coverage = "DISCLOSED_ONLY"
        except PublicFeedError:
            filename = "bulk.csv" if source == "NSE_BULK" else "block.csv"
            data, actual_url = self._get(
                "https://nsearchives.nseindia.com/content/equities/" + filename
            )
            try:
                rows = normalise_records(parse_csv(data), now=now)[0]
            except (ValueError, TypeError):
                raise PublicFeedError("NSE_ARCHIVE_INVALID") from None
            coverage = "SINGLE_DAILY_REPORT"
        if any(
            not start.isoformat() <= r["trade_date"] <= end.isoformat() for r in rows
        ):
            raise PublicFeedError("NSE_REPORT_OUTSIDE_WINDOW")
        return {
            "rows": rows,
            "source": source,
            "source_url": actual_url,
            "coverage": coverage,
            "document_sha256": hashlib.sha256(data).hexdigest(),
            "disclosure_time_basis": "UNKNOWN",
        }
