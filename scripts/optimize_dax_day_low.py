"""
DAX Day-Low Stop Loss Optimizer
Tests the new "day_low" stop loss method where we track the lowest low from midnight
continuously (24/7) but only enter trades during EU session hours (08:00-22:00 CET).

Compares performance against the original bars_lookback method.
"""
import pandas as pd
import numpy as np
from pathlib import Path
import sys
from datetime import time
import pytz

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from strategy_core import rsi

# Configuration
DATA_DIR = Path("data/dax_monthly")
RESULTS_DIR = Path("results/dax_day_low")
TIMEZONE = pytz.timezone("Europe/Berlin")

# EU Session Configuration
SESSION_START = time(8, 0)   # 08:00 CET
SESSION_END = time(22, 0)    # 22:00 CET

# Parameter grid to test
RSI_PERIODS = [2, 3, 4, 5]
CROSS_UP_LEVELS = [5, 10, 15, 20]
RR_RATIOS = [3.0, 4.0, 5.0]  # Only test profitable R:R ratios
MAX_RISK_POINTS = [150, 200, 250]  # Maximum risk per trade
MIN_BARS_REQUIRED = 4  # Require at least 4 bars (2 hours) of data before first trade


def rsi_cross_up_custom(series, level, period):
    """Custom RSI cross-up detection."""
    rsi_series = rsi(series, period=period)
    prev_below = rsi_series.shift(1) <= level
    curr_above = rsi_series > level
    return prev_below & curr_above


def is_in_session(timestamp):
    """Check if timestamp is within EU trading session (08:00-22:00 CET)."""
    # Localize to Europe/Berlin timezone
    if timestamp.tzinfo is None:
        local_time = TIMEZONE.localize(timestamp)
    else:
        local_time = timestamp.astimezone(TIMEZONE)

    current_time = local_time.time()
    return SESSION_START <= current_time <= SESSION_END


def compute_day_low_sl(df, idx, max_risk):
    """
    Calculate stop loss using day's lowest low.

    Day resets at midnight (00:00 Europe/Berlin).
    Tracks lowest low continuously 24/7.
    Enforces max_risk cap.
    """
    current_bar = df.iloc[idx]
    current_datetime = df.index[idx]

    # Localize to Europe/Berlin
    if current_datetime.tzinfo is None:
        current_datetime_local = TIMEZONE.localize(current_datetime)
    else:
        current_datetime_local = current_datetime.astimezone(TIMEZONE)

    # Find midnight of current day
    midnight = current_datetime_local.replace(hour=0, minute=0, second=0, microsecond=0)

    # Convert midnight to UTC for comparison with UTC-aware index
    midnight_utc = midnight.astimezone(pytz.UTC)

    # Get all bars from midnight until current bar
    mask = df.index >= midnight_utc
    mask &= df.index < current_datetime

    if mask.sum() < MIN_BARS_REQUIRED:
        return None  # Not enough bars since midnight

    day_bars = df[mask]
    if day_bars.empty:
        return None

    day_low = day_bars["Low"].min()
    entry_price = current_bar["Close"]

    # Check if SL is valid
    if entry_price <= day_low:
        return None

    # Apply max risk cap
    risk = entry_price - day_low
    if risk > max_risk:
        return None  # Risk too high

    return day_low


def compute_bars_lookback_sl(df, idx, lookback):
    """Original bars lookback stop loss method."""
    if idx < lookback:
        return None

    lows = [df.iloc[idx - i]["Low"] for i in range(1, lookback + 1)]
    sl = min(lows)
    entry = df.iloc[idx]["Close"]

    if entry <= sl:
        return None

    return sl


def backtest_day_low(df, rsi_period, cross_level, rr_ratio, max_risk):
    """Backtest using day-low stop loss method."""
    df = df.copy()
    close, high, low = df["Close"], df["High"], df["Low"]

    # Calculate RSI
    df["RSI"] = rsi(close, period=rsi_period)
    df["signal"] = rsi_cross_up_custom(close, level=cross_level, period=rsi_period)

    trades = []
    in_trade = False
    entry_price = sl = tp = entry_time = None

    for i in range(rsi_period, len(df)):
        ts = df.index[i]

        if not in_trade:
            # Only enter trades during session hours
            if not is_in_session(ts):
                continue

            # Check for entry signal
            if bool(df["signal"].iat[i]):
                # Avoid overlapping trades
                if trades and (df.index[i] <= trades[-1]["exit_time"]):
                    continue

                # Calculate SL using day's low
                sl_price = compute_day_low_sl(df, i, max_risk)
                if sl_price is None:
                    continue

                entry_price = close.iat[i]
                sl = sl_price

                # Calculate TP using R:R ratio
                risk = entry_price - sl
                if risk <= 0:
                    continue

                tp = entry_price + (risk * rr_ratio)
                in_trade = True
                entry_time = ts
        else:
            # Check for exit (can exit anytime, not just during session)
            bar_low, bar_high = low.iat[i], high.iat[i]
            sl_hit = bar_low <= sl
            tp_hit = bar_high >= tp

            if sl_hit or tp_hit:
                exit_reason = "SL" if sl_hit else "TP"
                exit_price = sl if sl_hit else tp
                pnl_pts = exit_price - entry_price

                trades.append({
                    "entry_time": entry_time,
                    "entry": float(entry_price),
                    "exit_time": ts,
                    "exit": float(exit_price),
                    "reason": exit_reason,
                    "pnl_pts": float(pnl_pts),
                    "bars_held": i - df.index.get_loc(entry_time),
                    "risk_pts": float(entry_price - sl)
                })

                in_trade = False
                entry_price = sl = tp = entry_time = None

    # Calculate statistics
    if not trades:
        return {
            "trades": 0, "wins": 0, "losses": 0,
            "win_rate_pct": 0.0, "total_pnl_pts": 0.0,
            "profit_factor": 0.0, "avg_bars_held": 0.0,
            "avg_risk_pts": 0.0
        }

    trades_df = pd.DataFrame(trades)
    wins = trades_df[trades_df["reason"] == "TP"]
    losses = trades_df[trades_df["reason"] == "SL"]

    total_win_pts = wins["pnl_pts"].sum() if not wins.empty else 0.0
    total_loss_pts = abs(losses["pnl_pts"].sum()) if not losses.empty else 0.0

    pf = (total_win_pts / total_loss_pts) if total_loss_pts > 0 else (999.0 if total_win_pts > 0 else 0.0)

    return {
        "trades": len(trades_df),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(100 * len(wins) / len(trades_df), 1),
        "total_pnl_pts": round(trades_df["pnl_pts"].sum(), 2),
        "profit_factor": round(pf, 2),
        "avg_bars_held": round(trades_df["bars_held"].mean(), 1),
        "avg_risk_pts": round(trades_df["risk_pts"].mean(), 2)
    }


def backtest_bars_lookback(df, rsi_period, cross_level, sl_lookback, rr_ratio):
    """Backtest using original bars lookback method (for comparison)."""
    df = df.copy()
    close, high, low = df["Close"], df["High"], df["Low"]

    df["RSI"] = rsi(close, period=rsi_period)
    df["signal"] = rsi_cross_up_custom(close, level=cross_level, period=rsi_period)

    trades = []
    in_trade = False
    entry_price = sl = tp = entry_time = None

    for i in range(max(rsi_period, sl_lookback), len(df)):
        ts = df.index[i]

        if not in_trade:
            # Only enter during session hours
            if not is_in_session(ts):
                continue

            if bool(df["signal"].iat[i]):
                if trades and (df.index[i] <= trades[-1]["exit_time"]):
                    continue

                sl_price = compute_bars_lookback_sl(df, i, sl_lookback)
                if sl_price is None:
                    continue

                entry_price = close.iat[i]
                sl = sl_price

                risk = entry_price - sl
                if risk <= 0:
                    continue

                tp = entry_price + (risk * rr_ratio)
                in_trade = True
                entry_time = ts
        else:
            bar_low, bar_high = low.iat[i], high.iat[i]
            sl_hit = bar_low <= sl
            tp_hit = bar_high >= tp

            if sl_hit or tp_hit:
                exit_reason = "SL" if sl_hit else "TP"
                exit_price = sl if sl_hit else tp
                pnl_pts = exit_price - entry_price

                trades.append({
                    "entry_time": entry_time,
                    "entry": float(entry_price),
                    "exit_time": ts,
                    "exit": float(exit_price),
                    "reason": exit_reason,
                    "pnl_pts": float(pnl_pts),
                    "bars_held": i - df.index.get_loc(entry_time),
                    "risk_pts": float(entry_price - sl)
                })

                in_trade = False
                entry_price = sl = tp = entry_time = None

    if not trades:
        return {
            "trades": 0, "wins": 0, "losses": 0,
            "win_rate_pct": 0.0, "total_pnl_pts": 0.0,
            "profit_factor": 0.0, "avg_bars_held": 0.0,
            "avg_risk_pts": 0.0
        }

    trades_df = pd.DataFrame(trades)
    wins = trades_df[trades_df["reason"] == "TP"]
    losses = trades_df[trades_df["reason"] == "SL"]

    total_win_pts = wins["pnl_pts"].sum() if not wins.empty else 0.0
    total_loss_pts = abs(losses["pnl_pts"].sum()) if not losses.empty else 0.0

    pf = (total_win_pts / total_loss_pts) if total_loss_pts > 0 else (999.0 if total_win_pts > 0 else 0.0)

    return {
        "trades": len(trades_df),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(100 * len(wins) / len(trades_df), 1),
        "total_pnl_pts": round(trades_df["pnl_pts"].sum(), 2),
        "profit_factor": round(pf, 2),
        "avg_bars_held": round(trades_df["bars_held"].mean(), 1),
        "avg_risk_pts": round(trades_df["risk_pts"].mean(), 2)
    }


def main():
    print("=" * 80)
    print("🔬 DAX DAY-LOW STOP LOSS OPTIMIZER")
    print("=" * 80)
    print()
    print("Testing new 'day_low' stop loss method vs original 'bars_lookback' method")
    print()
    print(f"Session Hours: {SESSION_START.strftime('%H:%M')} - {SESSION_END.strftime('%H:%M')} Europe/Berlin")
    print(f"Day-low tracking: Continuous (24/7), resets at midnight")
    print(f"Entry allowed: Only during session hours")
    print(f"Exit allowed: Anytime (24/7)")
    print()
    print(f"Testing {len(RSI_PERIODS)} RSI periods: {RSI_PERIODS}")
    print(f"Testing {len(CROSS_UP_LEVELS)} cross-up levels: {CROSS_UP_LEVELS}")
    print(f"Testing {len(RR_RATIOS)} R:R ratios: {RR_RATIOS}")
    print(f"Testing {len(MAX_RISK_POINTS)} max risk levels: {MAX_RISK_POINTS} points")
    print()

    total_day_low = len(RSI_PERIODS) * len(CROSS_UP_LEVELS) * len(RR_RATIOS) * len(MAX_RISK_POINTS)
    total_lookback = len(RSI_PERIODS) * len(CROSS_UP_LEVELS) * len(RR_RATIOS)

    print(f"📊 Total day_low combinations: {total_day_low}")
    print(f"📊 Total bars_lookback combinations: {total_lookback} (SL lookback fixed at 2)")
    print()

    # Create results directory
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Get all monthly CSV files
    csv_files = sorted(DATA_DIR.glob("dax_*.csv"))

    if not csv_files:
        print(f"❌ No CSV files found in {DATA_DIR}")
        return

    # Load and combine all monthly data
    print(f"📁 Loading {len(csv_files)} monthly files...")
    dfs = []
    for csv_file in csv_files:
        df = pd.read_csv(csv_file)
        df["Datetime"] = pd.to_datetime(df["Datetime"], utc=True)
        dfs.append(df)

    combined_df = pd.concat(dfs, ignore_index=True)
    combined_df = combined_df.set_index("Datetime")
    combined_df = combined_df.sort_index()

    print(f"✅ Loaded {len(combined_df)} total bars")
    print(f"📅 Date Range: {combined_df.index.min()} to {combined_df.index.max()}")
    print()

    # Test day_low method
    print("=" * 80)
    print("🔄 Testing DAY_LOW stop loss method...")
    print("=" * 80)
    print()

    day_low_results = []
    combo_count = 0

    for rsi_period in RSI_PERIODS:
        for cross_level in CROSS_UP_LEVELS:
            for rr_ratio in RR_RATIOS:
                for max_risk in MAX_RISK_POINTS:
                    combo_count += 1

                    variant_name = f"RSI{rsi_period}_L{cross_level}_RR{rr_ratio}_MR{max_risk}"

                    result = backtest_day_low(combined_df, rsi_period, cross_level, rr_ratio, max_risk)

                    result["method"] = "day_low"
                    result["rsi_period"] = rsi_period
                    result["cross_level"] = cross_level
                    result["rr_ratio"] = rr_ratio
                    result["max_risk"] = max_risk
                    result["variant"] = variant_name

                    day_low_results.append(result)

                    if combo_count % 20 == 0:
                        print(f"   Tested {combo_count}/{total_day_low} combinations...")

    print(f"✅ Completed {combo_count} day_low combinations")
    print()

    # Test bars_lookback method (for comparison)
    print("=" * 80)
    print("🔄 Testing BARS_LOOKBACK stop loss method (baseline)...")
    print("=" * 80)
    print()

    lookback_results = []
    combo_count = 0
    SL_LOOKBACK = 2  # Fixed at 2 bars (best from previous optimization)

    for rsi_period in RSI_PERIODS:
        for cross_level in CROSS_UP_LEVELS:
            for rr_ratio in RR_RATIOS:
                combo_count += 1

                variant_name = f"RSI{rsi_period}_L{cross_level}_RR{rr_ratio}_SL{SL_LOOKBACK}"

                result = backtest_bars_lookback(combined_df, rsi_period, cross_level, SL_LOOKBACK, rr_ratio)

                result["method"] = "bars_lookback"
                result["rsi_period"] = rsi_period
                result["cross_level"] = cross_level
                result["rr_ratio"] = rr_ratio
                result["sl_lookback"] = SL_LOOKBACK
                result["variant"] = variant_name

                lookback_results.append(result)

                if combo_count % 20 == 0:
                    print(f"   Tested {combo_count}/{total_lookback} combinations...")

    print(f"✅ Completed {combo_count} bars_lookback combinations")
    print()

    # Combine and save results
    all_results_df = pd.DataFrame(day_low_results + lookback_results)
    output_file = RESULTS_DIR / "dax_day_low_comparison.csv"
    all_results_df.to_csv(output_file, index=False)

    # Analyze results
    print("=" * 80)
    print("📊 OPTIMIZATION RESULTS")
    print("=" * 80)
    print()

    # Best day_low results
    day_low_df = pd.DataFrame(day_low_results)
    profitable_day_low = day_low_df[day_low_df["total_pnl_pts"] > 0].copy()

    if len(profitable_day_low) > 0:
        profitable_day_low = profitable_day_low.sort_values("total_pnl_pts", ascending=False)

        print("🏆 TOP 10 DAY_LOW VARIANTS (by profit):")
        print("-" * 80)
        for idx, row in profitable_day_low.head(10).iterrows():
            print(f"{row['variant']:35s} | PnL: {row['total_pnl_pts']:+8.2f} pts | "
                  f"WR: {row['win_rate_pct']:5.1f}% | Trades: {row['trades']:3d} | "
                  f"PF: {row['profit_factor']:5.2f} | Avg Risk: {row['avg_risk_pts']:5.1f} pts")
        print()
    else:
        print("❌ No profitable day_low variants found")
        print()

    # Best bars_lookback results
    lookback_df = pd.DataFrame(lookback_results)
    profitable_lookback = lookback_df[lookback_df["total_pnl_pts"] > 0].copy()

    if len(profitable_lookback) > 0:
        profitable_lookback = profitable_lookback.sort_values("total_pnl_pts", ascending=False)

        print("🏆 TOP 10 BARS_LOOKBACK VARIANTS (by profit):")
        print("-" * 80)
        for idx, row in profitable_lookback.head(10).iterrows():
            print(f"{row['variant']:35s} | PnL: {row['total_pnl_pts']:+8.2f} pts | "
                  f"WR: {row['win_rate_pct']:5.1f}% | Trades: {row['trades']:3d} | "
                  f"PF: {row['profit_factor']:5.2f} | Avg Risk: {row['avg_risk_pts']:5.1f} pts")
        print()
    else:
        print("❌ No profitable bars_lookback variants found")
        print()

    # Direct comparison of best methods
    print("=" * 80)
    print("🎯 HEAD-TO-HEAD COMPARISON: BEST OF EACH METHOD")
    print("=" * 80)
    print()

    if len(profitable_day_low) > 0 and len(profitable_lookback) > 0:
        best_day_low = profitable_day_low.iloc[0]
        best_lookback = profitable_lookback.iloc[0]

        print("DAY_LOW Method (Best):")
        print(f"  Variant: {best_day_low['variant']}")
        print(f"  Total PnL: {best_day_low['total_pnl_pts']:+.2f} points")
        print(f"  Win Rate: {best_day_low['win_rate_pct']:.1f}%")
        print(f"  Total Trades: {int(best_day_low['trades'])}")
        print(f"  Profit Factor: {best_day_low['profit_factor']:.2f}")
        print(f"  Avg Risk per Trade: {best_day_low['avg_risk_pts']:.1f} points")
        print()

        print("BARS_LOOKBACK Method (Best):")
        print(f"  Variant: {best_lookback['variant']}")
        print(f"  Total PnL: {best_lookback['total_pnl_pts']:+.2f} points")
        print(f"  Win Rate: {best_lookback['win_rate_pct']:.1f}%")
        print(f"  Total Trades: {int(best_lookback['trades'])}")
        print(f"  Profit Factor: {best_lookback['profit_factor']:.2f}")
        print(f"  Avg Risk per Trade: {best_lookback['avg_risk_pts']:.1f} points")
        print()

        # Calculate improvements
        pnl_improvement = best_day_low['total_pnl_pts'] - best_lookback['total_pnl_pts']
        wr_improvement = best_day_low['win_rate_pct'] - best_lookback['win_rate_pct']

        print("IMPROVEMENT (day_low vs bars_lookback):")
        print(f"  PnL Difference: {pnl_improvement:+.2f} points ({pnl_improvement/best_lookback['total_pnl_pts']*100:+.1f}%)")
        print(f"  Win Rate Difference: {wr_improvement:+.1f} percentage points")
        print()

        if best_day_low['total_pnl_pts'] > best_lookback['total_pnl_pts']:
            print("✅ DAY_LOW method is MORE PROFITABLE")
        else:
            print("⚠️  BARS_LOOKBACK method is more profitable")

        if best_day_low['win_rate_pct'] > best_lookback['win_rate_pct']:
            print("✅ DAY_LOW method has HIGHER WIN RATE")
        else:
            print("⚠️  BARS_LOOKBACK method has higher win rate")
        print()

    print(f"💾 Full results saved to: {output_file}")
    print()


if __name__ == "__main__":
    main()
