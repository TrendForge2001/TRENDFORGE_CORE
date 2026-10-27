
from indicators.base_indicator import BaseIndicator


class VWMAIndicator(BaseIndicator):

    def __init__(self, period):

        self.period = period

    def calculate(self, df):

        pv = df["close"] * df["volume"]

        return (

            pv.rolling(self.period).sum()

            /

            df["volume"].rolling(self.period).sum()

        )