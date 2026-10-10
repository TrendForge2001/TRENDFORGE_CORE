"""
TrendForge v2
api/kite_service.py

Production-grade Kite Connect Service
Part 1 - Authentication & Session Management
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from kiteconnect import KiteConnect
from kiteconnect.exceptions import (
    TokenException,
    NetworkException,
    DataException,
)

from config.settings import (
    KITE_API_KEY,
    KITE_API_SECRET,
    KITE_ACCESS_TOKEN,
)

logger = logging.getLogger(__name__)


# ==========================================================
# Exceptions
# ==========================================================

class KiteServiceError(Exception):
    """Base exception."""


class KiteAuthenticationError(KiteServiceError):
    """Authentication failed."""


class KiteConnectionError(KiteServiceError):
    """Connection failed."""


class KiteNotConnectedError(KiteServiceError):
    """Client unavailable."""


# ==========================================================
# Kite Service
# ==========================================================

class KiteService:

    def __init__(self):

        self.api_key = KITE_API_KEY
        self.api_secret = KITE_API_SECRET
        self.access_token = KITE_ACCESS_TOKEN

        self._kite: Optional[KiteConnect] = None

        self._lock = threading.RLock()

        self.cache_dir = Path("cache")
        self.cache_dir.mkdir(exist_ok=True)

        self.instrument_cache = {}

        logger.info("KiteService initialized.")

        if self.access_token:
            self.connect()

    # ======================================================
    # Connection
    # ======================================================

    def connect(self):

        with self._lock:

            try:

                logger.info("Connecting to Kite...")

                kite = KiteConnect(
                    api_key=self.api_key
                )

                kite.set_access_token(
                    self.access_token
                )

                profile = kite.profile()

                self._kite = kite

                logger.info(
                    "Connected as %s",
                    profile.get("user_name"),
                )

            except TokenException as exc:

                logger.exception(
                    "Authentication failed."
                )

                raise KiteAuthenticationError(
                    str(exc)
                ) from exc

            except Exception as exc:

                logger.exception(
                    "Unable to connect."
                )

                raise KiteConnectionError(
                    str(exc)
                ) from exc

    # ======================================================
    # Disconnect
    # ======================================================

    def disconnect(self):

        with self._lock:

            self._kite = None

            logger.info(
                "Disconnected."
            )

    # ======================================================
    # Reconnect
    # ======================================================

    def reconnect(self):

        self.disconnect()

        self.connect()

    # ======================================================
    # Client
    # ======================================================

    @property
    def client(self):

        if self._kite is None:

            raise KiteNotConnectedError(
                "Kite not connected."
            )

        return self._kite

    # ======================================================
    # Status
    # ======================================================

    def is_connected(self):

        return self._kite is not None

    # ======================================================
    # Session Validation
    # ======================================================

    def validate_session(self):

        if self._kite is None:

            return False

        try:

            self._kite.profile()

            return True

        except TokenException:

            logger.warning(
                "Access token expired."
            )

            self.disconnect()

            return False

        except Exception:

            logger.exception(
                "Session validation failed."
            )

            return False

    # ======================================================
    # Health
    # ======================================================

    def health(self):

        return {

            "connected": self.is_connected(),

            "cache_dir": str(self.cache_dir),

            "cached_exchanges":

            list(

                self.instrument_cache.keys()

            ),

        }

    # ======================================================
    # Profile
    # ======================================================

    def profile(self):

        return self.client.profile()

    # ======================================================
    # Margins
    # ======================================================

    def margins(self):

        return self.client.margins()

    # ======================================================
    # Holdings
    # ======================================================

    def holdings(self):

        return self.client.holdings()

    # ======================================================
    # Positions
    # ======================================================

    def positions(self):

        return self.client.positions()

    # ======================================================
    # Orders
    # ======================================================

    def orders(self):

        return self.client.orders()

    # ======================================================
    # Trades
    # ======================================================

    def trades(self):

        return self.client.trades()
    
    # ======================================================
# Instruments
# ======================================================

from database.instrument_repository import (
    InstrumentRepository
)

def download_instruments(
    self,
    exchange="NSE",
):

    logger.info(
        "Downloading instruments..."
    )

    data = self.client.instruments(
        exchange
    )

    repo = InstrumentRepository()

    repo.save_all(data)

    logger.info(
        "%d instruments saved.",
        len(data),
    )

    return data

    logger.info(
        "Downloading %s instruments...",
        exchange,
    )

    instruments = self.client.instruments(exchange)

    import pandas as pd

    df = pd.DataFrame(instruments)

    file = (
        self.cache_dir /
        f"{exchange.lower()}_instruments.csv"
    )

    df.to_csv(
        file,
        index=False,
    )

    self.instrument_cache[exchange] = df

    logger.info(
        "%d instruments downloaded.",
        len(df),
    )

    return df


# ======================================================
# Load Instruments
# ======================================================

def load_instruments(
    self,
    exchange: str = "NSE",
):

    import pandas as pd

    if exchange in self.instrument_cache:

        return self.instrument_cache[
            exchange
        ]

    file = (
        self.cache_dir /
        f"{exchange.lower()}_instruments.csv"
    )

    if file.exists():

        df = pd.read_csv(file)

        self.instrument_cache[
            exchange
        ] = df

        return df

    return self.download_instruments(
        exchange
    )


# ======================================================
# Refresh Instruments
# ======================================================

def refresh_instruments(
    self,
    exchange="NSE",
):

    return self.download_instruments(
        exchange
    )


# ======================================================
# Instrument Token
# ======================================================

def instrument_token(
    self,
    symbol,
):

    repo = InstrumentRepository()

    token = repo.token(symbol)

    if token is None:

        raise KeyError(symbol)

    return token

    df = self.load_instruments(
        exchange
    )

    row = df.loc[
        df["tradingsymbol"] == symbol
    ]

    if row.empty:

        raise KeyError(symbol)

    return int(
        row.iloc[0][
            "instrument_token"
        ]
    )


# ======================================================
# Trading Symbol
# ======================================================

def trading_symbol(
    self,
    token,
    exchange="NSE",
):

    df = self.load_instruments(
        exchange
    )

    row = df.loc[
        df["instrument_token"] == token
    ]

    if row.empty:

        raise KeyError(token)

    return str(
        row.iloc[0][
            "tradingsymbol"
        ]
    )


# ======================================================
# Search Symbol
# ======================================================

def search(
    self,
    text,
    exchange="NSE",
):

    df = self.load_instruments(
        exchange
    )

    return df[
        df["tradingsymbol"]
        .str.contains(
            text.upper(),
            na=False,
        )
    ]


# ======================================================
# LTP
# ======================================================

def ltp(
    self,
    symbol,
):

    return self.client.ltp(symbol)


# ======================================================
# Quote
# ======================================================

def quote(
    self,
    symbol,
):

    return self.client.quote(symbol)


# ======================================================
# OHLC
# ======================================================

def ohlc(
    self,
    symbol,
):

    return self.client.ohlc(symbol)


# ======================================================
# Multiple Quotes
# ======================================================

def quotes(
    self,
    symbols,
):

    return self.client.quote(symbols)


# ======================================================
# Historical Data
# ======================================================

def historical_data(

    self,

    instrument_token,

    from_date,

    to_date,

    interval="day",

    continuous=False,

    oi=False,

):

    return self.client.historical_data(

        instrument_token,

        from_date,

        to_date,

        interval,

        continuous,

        oi,

    )


# ======================================================
# Daily Candles
# ======================================================

def daily_data(

    self,

    instrument_token,

    from_date,

    to_date,

):

    return self.historical_data(

        instrument_token,

        from_date,

        to_date,

        "day",

    )


# ======================================================
# Intraday Candles
# ======================================================

def intraday_data(

    self,

    instrument_token,

    from_date,

    to_date,

    interval="5minute",

):

    return self.historical_data(

        instrument_token,

        from_date,

        to_date,

        interval,

    )


# ======================================================
# Market Depth
# ======================================================

def market_depth(

    self,

    symbol,

):

    quote = self.quote(symbol)

    return quote[symbol].get(
        "depth",
        {},
    )

    # ======================================================
# Place Order
# ======================================================

def place_order(
    self,
    exchange,
    tradingsymbol,
    transaction_type,
    quantity,
    order_type="MARKET",
    product="MIS",
    variety="regular",
    price=None,
    trigger_price=None,
):

    return self.client.place_order(
        variety=variety,
        exchange=exchange,
        tradingsymbol=tradingsymbol,
        transaction_type=transaction_type,
        quantity=quantity,
        product=product,
        order_type=order_type,
        price=price,
        trigger_price=trigger_price,
    )


# ======================================================
# Modify Order
# ======================================================

def modify_order(
    self,
    order_id,
    variety="regular",
    **kwargs,
):

    return self.client.modify_order(
        variety=variety,
        order_id=order_id,
        **kwargs,
    )


# ======================================================
# Cancel Order
# ======================================================

def cancel_order(
    self,
    order_id,
    variety="regular",
):

    return self.client.cancel_order(
        variety=variety,
        order_id=order_id,
    )


# ======================================================
# Order History
# ======================================================

def order_history(
    self,
    order_id,
):

    return self.client.order_history(
        order_id
    )


# ======================================================
# Order Status
# ======================================================

def order_status(
    self,
    order_id,
):

    history = self.order_history(
        order_id
    )

    if history:

        return history[-1]["status"]

    return None


# ======================================================
# Exit Position
# ======================================================

def exit_position(
    self,
    exchange,
    tradingsymbol,
    quantity,
    product="MIS",
):

    return self.place_order(
        exchange=exchange,
        tradingsymbol=tradingsymbol,
        transaction_type="SELL",
        quantity=quantity,
        order_type="MARKET",
        product=product,
    )


# ======================================================
# Buy Market
# ======================================================

def buy_market(
    self,
    exchange,
    tradingsymbol,
    quantity,
    product="MIS",
):

    return self.place_order(
        exchange=exchange,
        tradingsymbol=tradingsymbol,
        transaction_type="BUY",
        quantity=quantity,
        product=product,
    )


# ======================================================
# Sell Market
# ======================================================

def sell_market(
    self,
    exchange,
    tradingsymbol,
    quantity,
    product="MIS",
):

    return self.place_order(
        exchange=exchange,
        tradingsymbol=tradingsymbol,
        transaction_type="SELL",
        quantity=quantity,
        product=product,
    )


# ======================================================
# Buy Limit
# ======================================================

def buy_limit(
    self,
    exchange,
    tradingsymbol,
    quantity,
    price,
    product="MIS",
):

    return self.place_order(
        exchange=exchange,
        tradingsymbol=tradingsymbol,
        transaction_type="BUY",
        quantity=quantity,
        order_type="LIMIT",
        product=product,
        price=price,
    )


# ======================================================
# Sell Limit
# ======================================================

def sell_limit(
    self,
    exchange,
    tradingsymbol,
    quantity,
    price,
    product="MIS",
):

    return self.place_order(
        exchange=exchange,
        tradingsymbol=tradingsymbol,
        transaction_type="SELL",
        quantity=quantity,
        order_type="LIMIT",
        product=product,
        price=price,
    )


# ======================================================
# Bracket Target
# ======================================================

def calculate_target(
    self,
    entry,
    risk_reward=2,
    stoploss=10,
):

    return entry + (
        stoploss * risk_reward
    )


# ======================================================
# Stoploss
# ======================================================

def calculate_stoploss(
    self,
    entry,
    percent=1,
):

    return round(
        entry *
        (1 - percent / 100),
        2,
    )


# ======================================================
# Position Size
# ======================================================

def position_size(
    self,
    capital,
    risk_percent,
    stoploss_points,
):

    risk = capital * (
        risk_percent / 100
    )

    if stoploss_points <= 0:

        return 0

    return int(
        risk /
        stoploss_points
    )


# ======================================================
# Brokerage Estimate
# ======================================================

def estimate_brokerage(
    self,
    turnover,
):

    brokerage = min(
        20,
        turnover * 0.0003,
    )

    return round(
        brokerage,
        2,
    )


# ======================================================
# Available Funds
# ======================================================

def available_cash(self):

    margins = self.margins()

    return margins["equity"]["available"][
        "cash"
    ]


# ======================================================
# Net Margin
# ======================================================

def net_margin(self):

    margins = self.margins()

    return margins["equity"]["net"]
    # ======================================================
# Retry Helper
# ======================================================

def execute(
    self,
    func,
    *args,
    retries=3,
    **kwargs,
):

    last_exception = None

    for attempt in range(retries):

        try:

            return func(
                *args,
                **kwargs,
            )

        except (
            NetworkException,
            DataException,
        ) as exc:

            last_exception = exc

            logger.warning(
                "Retry %d/%d : %s",
                attempt + 1,
                retries,
                exc,
            )

    raise KiteConnectionError(
        str(last_exception)
    )


# ======================================================
# Safe Quote
# ======================================================

def safe_quote(
    self,
    symbol,
):

    return self.execute(
        self.client.quote,
        symbol,
    )


# ======================================================
# Safe LTP
# ======================================================

def safe_ltp(
    self,
    symbol,
):

    return self.execute(
        self.client.ltp,
        symbol,
    )


# ======================================================
# Safe Historical
# ======================================================

def safe_historical_data(

    self,

    instrument_token,

    from_date,

    to_date,

    interval="day",

):

    return self.execute(

        self.client.historical_data,

        instrument_token,

        from_date,

        to_date,

        interval,

    )


# ======================================================
# Bulk Quotes
# ======================================================

def bulk_quotes(
    self,
    symbols,
    batch_size=200,
):

    result = {}

    for i in range(
        0,
        len(symbols),
        batch_size,
    ):

        batch = symbols[
            i:i + batch_size
        ]

        result.update(
            self.safe_quote(batch)
        )

    return result


# ======================================================
# Bulk Historical
# ======================================================

def bulk_historical(

    self,

    instruments,

    from_date,

    to_date,

    interval="day",

):

    data = {}

    for token in instruments:

        try:

            data[token] = (

                self.safe_historical_data(

                    token,

                    from_date,

                    to_date,

                    interval,

                )

            )

        except Exception as exc:

            logger.warning(

                "%s : %s",

                token,

                exc,

            )

    return data


# ======================================================
# Exchange Symbols
# ======================================================

def exchange_symbols(
    self,
    exchange="NSE",
):

    df = self.load_instruments(
        exchange
    )

    return df[
        "tradingsymbol"
    ].tolist()


# ======================================================
# Nifty 500 Symbols
# ======================================================

def nifty500_symbols(self):
    """Legacy adapter delegating to the canonical source-backed universe."""

    try:
        from providers.nse_index_constituents import (
            NSEIndexConstituentProvider,
        )
        from universe.nifty500 import Nifty500Universe

        provider = NSEIndexConstituentProvider()
        universe = Nifty500Universe(loader=provider.nifty500)
        return [
            member.symbol
            for member in universe.refresh()
        ]

    except Exception:
        logger.exception(
            "Unable to load canonical NIFTY 500 universe."
        )

    return []


# ======================================================
# Refresh Cache
# ======================================================

def refresh_cache(self):

    self.instrument_cache.clear()

    self.download_instruments(
        "NSE"
    )

    self.download_instruments(
        "NFO"
    )

    logger.info(
        "Instrument cache refreshed."
    )


# ======================================================
# Scanner Data
# ======================================================

def scanner_quotes(self):

    symbols = self.nifty500_symbols()

    if not symbols:

        return {}

    symbols = [
        f"NSE:{s}"
        for s in symbols
    ]

    return self.bulk_quotes(
        symbols
    )


# ======================================================
# Ping
# ======================================================

def ping(self):

    try:

        self.profile()

        return True

    except Exception:

        return False


# ======================================================
# Health Report
# ======================================================

def health_report(self):

    return {

        "connected": self.is_connected(),

        "authenticated": self.validate_session(),

        "instrument_cache":

        len(

            self.instrument_cache

        ),

        "cache_directory":

        str(

            self.cache_dir

        ),

        "nse_loaded":

        "NSE"

        in

        self.instrument_cache,

        "nfo_loaded":

        "NFO"

        in

        self.instrument_cache,

    }


# ======================================================
# Version
# ======================================================

def version(self):

    return {

        "service":

        "TrendForge Kite Service",

        "version":

        "2.0.0",

    }


# ======================================================
# Close
# ======================================================

def close(self):

    self.disconnect()