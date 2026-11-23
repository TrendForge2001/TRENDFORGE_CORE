"""One stock-list catalog for navigation, membership and research admission."""

import json
from dataclasses import dataclass
from pathlib import Path

from config.nifty_universes import NIFTY_UNIVERSES

NSE_INDEX_CATALOG = json.loads(
    Path(__file__).with_name("nse_all_indices.json").read_text(encoding="utf-8")
)
NSE_ALL_INDICES = {row["name"]: row for row in NSE_INDEX_CATALOG["indices"]}

GROUP_SUFFIX = " (Grouped by sector)"


@dataclass(frozen=True)
class StockList:
    base: str
    kind: str = "equity"
    grouped: bool = False


_ORDER = (
    "Major Indices",
    "Global Indices",
    "NIFTY 50",
    "NIFTY 50" + GROUP_SUFFIX,
    "BSE SENSEX",
    "BSE SENSEX" + GROUP_SUFFIX,
    "NIFTY NEXT 50",
    "NIFTY NEXT 50" + GROUP_SUFFIX,
    "NIFTY 100",
    "NIFTY 200",
    "NIFTY 500",
    "NIFTY LARGEMIDCAP 250",
    "NIFTY LARGEMIDCAP 250" + GROUP_SUFFIX,
    "NIFTY MIDCAP 150",
    "NIFTY MIDCAP SELECT",
    "NIFTY SMALLCAP 250",
    "NIFTY MICROCAP 250",
    "NIFTY BANK",
    "NIFTY FINANCIAL SERVICES",
    "NIFTY IT",
    "NIFTY AUTO",
    "NIFTY FMCG",
    "NIFTY PHARMA",
    "NIFTY METAL",
    "NIFTY REALTY",
    "BSE BANKEX",
    "NSE F&O Stocks",
    "NSE F&O Stocks" + GROUP_SUFFIX,
)
STOCK_LISTS = {
    label: StockList(
        label.removesuffix(GROUP_SUFFIX),
        "index" if label in {"Major Indices", "Global Indices"} else "equity",
        label.endswith(GROUP_SUFFIX),
    )
    for label in _ORDER
}
for _name, _row in NSE_ALL_INDICES.items():
    STOCK_LISTS.setdefault(
        _name, StockList(_name, "index" if _row["kind"] == "reference" else "equity")
    )
EQUITY_STOCK_LISTS = tuple(k for k, v in STOCK_LISTS.items() if v.kind == "equity")


def stock_list_label(name):
    return {
        "NIFTY BANK": "Bank Nifty",
        "NIFTY FINANCIAL SERVICES": "Nifty FinNifty",
    }.get(name, name)


def resolve_stock_list(value):
    key = " ".join(str(value or "").upper().replace("_", " ").split())
    aliases = {name.upper(): name for name in STOCK_LISTS}
    aliases.update({name.replace(" ", "").upper(): name for name in STOCK_LISTS})
    aliases.update(
        {
            "BANK NIFTY": "NIFTY BANK",
            "NIFTY FINNIFTY": "NIFTY FINANCIAL SERVICES",
            "BANKNIFTY": "NIFTY BANK",
            "FINNIFTY": "NIFTY FINANCIAL SERVICES",
            "SENSEX": "BSE SENSEX",
            "BANKEX": "BSE BANKEX",
            **{str(n): f"NIFTY {n}" for n in (50, 100, 200, 500)},
        }
    )
    name = aliases.get(key)
    if name is None:
        raise ValueError("Choose a supported stock list")
    return name, STOCK_LISTS[name]


assert set(NIFTY_UNIVERSES) <= set(STOCK_LISTS)
