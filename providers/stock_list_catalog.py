"""Source-labelled stock lists; membership never falls back to another index."""

import csv
import io
import json
import re
import threading
import time
from datetime import UTC, datetime
from html.parser import HTMLParser

from config.stock_lists import NSE_ALL_INDICES, NSE_INDEX_CATALOG, resolve_stock_list
from providers.nse_broad_market_constituents import INDEX_CONFIGS

FO_URL = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"
EQUITY_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
BSE_URL = "https://www.smart-investing.in/indices-bse-nse.php?index="

# Curated index references, not constituent equity universes or live prices.
INDEX_REFERENCES = {
    "Major Indices": (
        ("NIFTY 50", "NSE:NIFTY 50", "India"),
        ("SENSEX", "BSE:SENSEX", "India"),
        ("NIFTY BANK", "NSE:NIFTY BANK", "India"),
        ("NIFTY FINANCIAL SERVICES", "NSE:NIFTY FIN SERVICE", "India"),
        ("NIFTY NEXT 50", "NSE:NIFTY NEXT 50", "India"),
        ("NIFTY MIDCAP SELECT", "NSE:NIFTY MID SELECT", "India"),
        ("BSE BANKEX", "BSE:BANKEX", "India"),
        ("INDIA VIX", "NSE:INDIA VIX", "India"),
    ),
    "Global Indices": (
        ("S&P 500", "SP:SPX", "United States"),
        ("NASDAQ 100", "NASDAQ:NDX", "United States"),
        ("Dow Jones Industrial Average", "DJ:DJI", "United States"),
        ("FTSE 100", "FTSE:UKX", "United Kingdom"),
        ("DAX", "XETR:DAX", "Germany"),
        ("CAC 40", "EURONEXT:PX1", "France"),
        ("Nikkei 225", "TVC:NI225", "Japan"),
        ("Hang Seng", "HSI:HSI", "Hong Kong"),
        ("Shanghai Composite", "SSE:000001", "China"),
        ("S&P/ASX 200", "ASX:XJO", "Australia"),
    ),
}


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self.table, self.row, self.cell = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table" and self.table is None:
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def company_key(name):
    words = re.findall(r"[A-Z0-9]+", str(name).upper())
    return "".join(w for w in words if w not in {"THE", "LTD", "LIMITED", "AND"})


def parse_bse_members(html, nse_members, *, base):
    parser = _Tables()
    parser.feed(html)
    tables = [
        t
        for t in parser.tables
        if t
        and len(t[0]) >= 2
        and t[0][0].upper() == "COMPANY"
        and "WEIGHTAGE" in t[0][1].upper()
    ]
    if len(tables) != 1:
        raise ValueError("BSE reference membership table is unavailable")
    names = [row[0] for row in tables[0][1:] if row and row[0]]
    low, high = (30, 30) if base == "BSE SENSEX" else (10, 30)
    if not low <= len(names) <= high:
        raise ValueError("BSE reference membership is incomplete")
    mapping = {}
    for member in nse_members:
        mapping.setdefault(company_key(member.get("name")), []).append(member)
    result = []
    for name in names:
        matches = mapping.get(company_key(name), [])
        if len(matches) != 1:
            raise ValueError("BSE member has no unique NSE equity mapping")
        result.append(dict(matches[0]))
    if len({m["symbol"] for m in result}) != len(result):
        raise ValueError("BSE reference contains duplicate constituents")
    return result


def parse_fo_members(text, equity_text):
    equities = {}
    for raw in csv.DictReader(io.StringIO(equity_text.lstrip("\ufeff"))):
        row = {str(k).strip().upper(): str(v or "").strip() for k, v in raw.items()}
        if row.get("SERIES") == "EQ" and re.fullmatch(
            r"[A-Z0-9][A-Z0-9.&-]{0,29}", row.get("SYMBOL", "")
        ):
            equities[row["SYMBOL"]] = row
    lines = text.lstrip("\ufeff").splitlines()
    header = next(
        (
            i
            for i, line in enumerate(lines)
            if "SYMBOL" in [x.strip().upper() for x in next(csv.reader([line]))]
        ),
        None,
    )
    if header is None:
        raise ValueError("NSE F&O membership header is unavailable")
    symbols = set()
    for raw in csv.DictReader(io.StringIO("\n".join(lines[header:]))):
        row = {str(k).strip().upper(): str(v or "").strip() for k, v in raw.items()}
        symbol = row.get("SYMBOL", "")
        if symbol in equities:
            symbols.add(symbol)
    if not 100 <= len(symbols) <= 1000:
        raise ValueError("NSE F&O stock membership is incomplete")
    return [
        {
            "symbol": s,
            "name": equities[s].get("NAME OF COMPANY") or s,
            "sector": "Unclassified",
            "exchange": "NSE",
        }
        for s in sorted(symbols)
    ]


class StockListCatalogProvider:
    def __init__(self, nse):
        self.nse = nse
        self.session = nse.session if hasattr(nse, "session") else None
        self.cache, self.cached_at, self.retry_after = {}, {}, {}
        self.lock = threading.Lock()
        from providers.nse_all_index_members import NSEAllIndexMembers
        self.all_indices = NSEAllIndexMembers(nse)

    def _get(self, url):
        response = self.session.get(url, timeout=8, allow_redirects=True)
        response.raise_for_status()
        if (
            len(response.content if hasattr(response, "content") else response.text)
            > 5_000_000
        ):
            raise ValueError("Stock-list response exceeds size limit")
        return response.text

    def load(self, label):
        name, definition = resolve_stock_list(label)
        base = definition.base
        if definition.kind == "index" and base not in INDEX_REFERENCES:
            payload = {"source": "NSE_ALL_INDICES_CATALOG", "stale": False,
                       "catalog_as_of": NSE_INDEX_CATALOG["as_of"], "members": [],
                       "source_warning": "Reference index; no standalone equity stock list"}
        elif base in INDEX_REFERENCES:
            payload = {
                "source": "CURATED_INDEX_REFERENCES",
                "stale": False,
                "members": [
                    {
                        "symbol": s,
                        "instrument": s,
                        "name": n,
                        "sector": region,
                        "asset_type": "index",
                    }
                    for n, s, region in INDEX_REFERENCES[base]
                ],
            }
        elif base in INDEX_CONFIGS:
            payload = self.nse.load(base)
        elif base in NSE_ALL_INDICES:
            with self.lock:
                payload = self.all_indices.load(base)
        else:
            with self.lock:
                payload = self._special(base)
        return {
            **payload,
            "index": name,
            "base_index": base,
            "kind": definition.kind,
            "grouped": definition.grouped,
            "count": len(payload["members"]),
        }

    def _special(self, base):
        if base in self.cache and time.monotonic() - self.cached_at[base] < 600:
            return self.cache[base]
        if time.monotonic() < self.retry_after.get(base, 0):
            raise RuntimeError("Stock-list membership is temporarily unavailable")
        try:
            if base == "NSE F&O Stocks":
                members = parse_fo_members(self._get(FO_URL), self._get(EQUITY_URL))
                url, source = FO_URL, "NSE_FO_MARKET_LOTS_AND_EQUITY_MASTER"
                # Sector enrichment is optional; never drop an eligible stock.
                try:
                    sectors = {
                        m["symbol"]: m.get("sector")
                        for m in self.nse.load("NIFTY 500")["members"]
                    }
                    members = [
                        {**m, "sector": sectors.get(m["symbol"]) or "Unclassified"}
                        for m in members
                    ]
                except (ValueError, RuntimeError):
                    pass
            else:
                url = BSE_URL + ("SENSEX" if base == "BSE SENSEX" else "BANKEX")
                members = parse_bse_members(
                    self._get(url), self.nse.load("NIFTY 500")["members"], base=base
                )
                source = "SMART_INVESTING_BSE_REFERENCE_NSE_MAPPED"
            payload = {
                "base_index": base,
                "members": members,
                "source": source,
                "source_url": url,
                "fetched_at": datetime.now(UTC).isoformat(),
                "stale": False,
                "source_warning": (
                    "BSE membership reference: Smart Investing; prices and "
                    "research use the mapped NSE listings."
                    if base.startswith("BSE")
                    else None
                ),
            }
            self.cache[base], self.cached_at[base] = payload, time.monotonic()
            self._save(base, payload)
            return payload
        except Exception:
            self.retry_after[base] = time.monotonic() + 10
            cached = self.cache.get(base) or self._saved(base)
            if cached:
                stale = {
                    **cached,
                    "stale": True,
                    "source_warning": "Live membership refresh unavailable; "
                    "using the last validated list from " + cached["fetched_at"],
                }
                self.cache[base], self.cached_at[base] = stale, time.monotonic()
                return stale
            raise RuntimeError(
                "Stock-list membership is temporarily unavailable"
            ) from None

    def _save(self, base, payload):
        if not hasattr(self.nse, "cache_dir"):
            return
        try:
            self.nse.cache_dir.mkdir(parents=True, exist_ok=True)
            path = self.nse.cache_dir / (
                base.lower().replace(" ", "_").replace("&", "and") + "_catalog.json"
            )
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(payload), encoding="utf-8")
            temp.replace(path)
        except OSError:
            pass

    def _saved(self, base):
        if not hasattr(self.nse, "cache_dir"):
            return None
        try:
            path = self.nse.cache_dir / (
                base.lower().replace(" ", "_").replace("&", "and") + "_catalog.json"
            )
            p = json.loads(path.read_text(encoding="utf-8"))
            members = p["members"]
            expected = (
                "NSE_FO_MARKET_LOTS_AND_EQUITY_MASTER"
                if base == "NSE F&O Stocks"
                else "SMART_INVESTING_BSE_REFERENCE_NSE_MAPPED"
            )
            low, high = (
                (100, 1000)
                if base == "NSE F&O Stocks"
                else (30, 30)
                if base == "BSE SENSEX"
                else (10, 30)
            )
            if (
                p.get("source") != expected
                or p.get("base_index") != base
                or not p.get("fetched_at")
                or not isinstance(members, list)
                or not low <= len(members) <= high
                or not all(
                    isinstance(m, dict)
                    and re.fullmatch(
                        r"[A-Z0-9][A-Z0-9.&-]{0,29}", str(m.get("symbol", ""))
                    )
                    for m in members
                )
                or len({m["symbol"] for m in members}) != len(members)
            ):
                return None
            return p
        except (OSError, ValueError, KeyError, TypeError):
            return None
