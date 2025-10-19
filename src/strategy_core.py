import pandas as pd
import numpy as np

def rsi(series: pd.Series, period: int = 2) -> pd.Series:
    delta = series.diff()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(up, index=series.index).ewm(alpha=1/period, adjust=False).mean()
    roll_down = pd.Series(down, index=series.index).ewm(alpha=1/period, adjust=False).mean()
    rs = roll_up / roll_down.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def rsi_cross_up(series_close: pd.Series, level: int = 10, period: int = 2) -> pd.Series:
    r = rsi(series_close, period)
    return (r.shift(1) <= level) & (r > level)

def compute_sl_tp_fixed_rr(df: pd.DataFrame, entry_idx: int, rr: float):
    entry = float(df["Close"].iloc[entry_idx])
    l1, l2 = float(df["Low"].iloc[entry_idx-1]), float(df["Low"].iloc[entry_idx-2])
    ll2 = min(l1, l2)
    risk = entry - ll2
    if risk <= 0: return None
    tp = entry + risk * rr
    return {"entry": entry, "sl": ll2, "tp": tp, "risk": risk}

def compute_tp_gapN(df: pd.DataFrame, entry_idx: int, N: float):
    entry = float(df["Close"].iloc[entry_idx])
    l1, l2 = float(df["Low"].iloc[entry_idx-1]), float(df["Low"].iloc[entry_idx-2])
    ll2, other_low = min(l1, l2), max(l1, l2)
    risk = entry - ll2
    if risk <= 0: return None
    gap = abs(other_low - ll2)
    return {"entry": entry, "sl": ll2, "tp": entry + gap * N, "risk": risk}
