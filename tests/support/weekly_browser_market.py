"""Browser-only deterministic weekly history, plus legacy intraday recovery data."""

from services import weekly_floor_research
from tests.support.research_candles import SyntheticMarket
from tests.support.research_candles import technical_service as original_service
from tests.support.weekly_floor_candles import NOW, example_history


class BrowserMarket(SyntheticMarket):
    def batch_candles_with_errors(self, symbols, *, interval, period, **kwargs):
        if interval == "1d" and period == "5y":
            raw = example_history()
            return {symbol: raw.copy() for symbol in symbols}, {}
        return super().batch_candles_with_errors(
            symbols, interval=interval, period=period, **kwargs
        )


def technical_service(database):
    # This isolated fixture has no broker client. Freeze only its weekly research
    # clock so browser acceptance does not depend on the real calendar year.
    weekly_floor_research.local_now = lambda now=None: NOW
    service = original_service(database)
    service.market_data = BrowserMarket()
    return service
