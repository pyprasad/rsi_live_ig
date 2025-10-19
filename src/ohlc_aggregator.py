from dataclasses import dataclass
from typing import Optional

@dataclass
class Bar:
    ts_open: float
    open: float
    high: float
    low: float
    close: float

class BarBuilder:
    def __init__(self, timeframe_sec: int):
        self.tf = timeframe_sec
        self.cur: Optional[Bar] = None

    def _bucket(self, t: float) -> float:
        return t - (t % self.tf)

    def on_tick(self, t: float, price: float):
        b = self._bucket(t)
        if self.cur is None or b > self.cur.ts_open:
            finished = self.cur
            self.cur = Bar(ts_open=b, open=price, high=price, low=price, close=price)
            return finished
        self.cur.high = max(self.cur.high, price)
        self.cur.low  = min(self.cur.low, price)
        self.cur.close = price
        return None

    def flush(self):
        f = self.cur; self.cur = None; return f
