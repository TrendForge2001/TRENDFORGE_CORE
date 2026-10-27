
from indicators.base_indicator import BaseIndicator


class EMAIndicator(BaseIndicator):

    def __init__(self, period):

        self.period = period

    def calculate(self, df):

        return df["close"].ewm(
            span=self.period,
            adjust=False
        ).mean()