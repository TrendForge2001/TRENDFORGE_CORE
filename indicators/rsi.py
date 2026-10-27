
from indicators.base_indicator import BaseIndicator


class RSIIndicator(BaseIndicator):

    def __init__(self, period=14):

        self.period = period

    def calculate(self, df):

        delta = df.close.diff()

        gain = delta.clip(lower=0)

        loss = -delta.clip(upper=0)

        avg_gain = gain.ewm(alpha=1/self.period).mean()

        avg_loss = loss.ewm(alpha=1/self.period).mean()

        rs = avg_gain / avg_loss

        return 100 - (100 / (1 + rs))