"""
S&P 500 RSI(2) Reversal Strategy
Buy when RSI <= 90 (oversold)
Sell when RSI >= 10 (overbought)
"""
import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta


def rsi(series, period=2):
    """Calculate RSI indicator"""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def sp500_signal(df, cfg):
    """
    Check for S&P 500 reversal signal

    Args:
        df: DataFrame with columns ['Open', 'High', 'Low', 'Close'] and DatetimeIndex
        cfg: Config dict with strategy parameters

    Returns:
        dict with signal info or None
    """
    if len(df) < 3:
        return None

    # Calculate RSI(2)
    rsi_series = rsi(df['Close'], period=cfg.get('rsi_period', 2))
    current_rsi = float(rsi_series.iloc[-1])

    if pd.isna(current_rsi):
        return None

    # Get current bar info
    current_bar = df.iloc[-1]
    current_time = current_bar.name if hasattr(current_bar, 'name') else datetime.now()
    current_price = float(current_bar['Close'])

    # Check market open delay (don't trade first 30 mins)
    market_open_delay = cfg.get('market_open_delay_minutes', 30)
    if not is_past_market_open_delay(current_time, market_open_delay):
        return None

    # Check news filter (placeholder - will be implemented in runner)
    # The runner will check this before executing

    # Signal detection
    buy_level = cfg.get('rsi_buy_level', 90)
    sell_level = cfg.get('rsi_sell_level', 10)

    signal_type = None
    if current_rsi <= buy_level:
        signal_type = "BUY"
    elif current_rsi >= sell_level:
        signal_type = "SELL"

    if not signal_type:
        return None

    # Calculate TP and SL
    tp = compute_take_profit(df, cfg)
    sl = compute_stop_loss(df, signal_type, cfg)

    if tp is None or sl is None:
        return None

    return {
        'type': signal_type,
        'entry': current_price,
        'tp': tp,
        'sl': sl,
        'rsi': current_rsi,
        'timestamp': current_time
    }


def compute_take_profit(df, cfg):
    """
    TP = (last 2 candles difference) * 10
    """
    if len(df) < 2:
        return None

    close_prev = float(df['Close'].iloc[-2])
    close_prev2 = float(df['Close'].iloc[-3]) if len(df) >= 3 else close_prev

    diff = abs(close_prev - close_prev2)
    tp_multiplier = cfg.get('tp_multiplier', 10.0)

    tp_distance = diff * tp_multiplier

    # TP is added to entry for BUY, subtracted for SELL
    # We'll return the distance, runner will apply direction
    return tp_distance


def compute_stop_loss(df, signal_type, cfg):
    """
    SL = day's low + configurable pips (for BUY)
    SL = day's high - configurable pips (for SELL)
    """
    sl_pips = cfg.get('sl_pips_from_day_low', 100.0)

    # Get today's bars
    today = df.index[-1].date() if hasattr(df.index[-1], 'date') else datetime.now().date()
    today_bars = df[df.index.date == today] if hasattr(df.index, 'date') else df

    if len(today_bars) == 0:
        return None

    if signal_type == "BUY":
        day_low = float(today_bars['Low'].min())
        # SL below day's low
        sl_price = day_low - (sl_pips / 10000.0)  # Convert pips to price
        return sl_price
    else:  # SELL
        day_high = float(today_bars['High'].max())
        # SL above day's high
        sl_price = day_high + (sl_pips / 10000.0)
        return sl_price


def is_past_market_open_delay(current_time, delay_minutes=30):
    """
    Check if we're past the market open delay period

    For S&P 500 futures (24/5), we check if it's been 30+ mins since:
    - Sunday 22:00 UTC (futures open)
    - Each day at 00:00 UTC (new day)

    Simple implementation: check if current time minutes >= delay
    """
    # For simplicity, check if we're past :30 of any hour
    # This gives a 30-min delay after each hour
    # More sophisticated: track actual market open time

    if isinstance(current_time, pd.Timestamp):
        current_time = current_time.to_pydatetime()

    # Simple check: if we're in first 30 mins of trading day, skip
    # S&P 500 main session opens 14:30 UTC (9:30 EST)
    # Extended hours: Sunday 22:00 UTC

    weekday = current_time.weekday()
    hour = current_time.hour
    minute = current_time.minute

    # Sunday evening open (22:00 UTC)
    if weekday == 6 and hour == 22 and minute < delay_minutes:
        return False

    # Check if we're in first 30 mins after main session open (14:30 UTC)
    if hour == 14 and minute < (30 + delay_minutes):
        return False

    # Otherwise allow trading
    return True


def price_to_dist(entry, sl, tp):
    """Convert prices to distances for IG API"""
    sl_dist = abs(entry - sl)
    tp_dist = abs(tp - entry)
    return max(sl_dist, 0.1), max(tp_dist, 0.1)
