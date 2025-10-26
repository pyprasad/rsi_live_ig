"""
DAX ATR Volatility Filter Optimizer

Tests adding ATR (Average True Range) filter to the momentum confirm entry signal.

Logic:
- Only trade when ATR is above a threshold (market has enough volatility for R:R 5.0)
- Combines with momentum confirm entry (RSI cross + price breaks prior high)
- Goal: Improve expectancy by avoiding low-volatility sideways markets

ATR Filter Options:
1. No filter (baseline - momentum confirm only)
2. ATR > ATR_MA (current volatility above average)
3. ATR > 1.2 * ATR_MA (20% above average)
4. ATR > 1.5 * ATR_MA (50% above average)
5. ATR > fixed threshold (e.g., 50, 75, 100 points)
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
RESULTS_DIR = Path("results/dax_atr_filter")
TIMEZONE = pytz.timezone("Europe/Berlin")

# EU Session Configuration
SESSION_START = time(8, 0)   # 08:00 CET
SESSION_END = time(22, 0)    # 22:00 CET

# Parameter grid to test (focused on proven winners)
RSI_PERIODS = [2]
CROSS_UP_LEVELS = [7, 10]  # Best performers from previous test
RR_RATIOS = [5.0]  # Fixed at 5.0 (proven best)
SL_LOOKBACK = 2

# ATR Configuration
ATR_PERIOD = 14  # Standard ATR period
ATR_MA_PERIOD = 20  # Moving average of ATR for comparison

# ATR filter types to test
ATR_FILTERS = [
    {"type": "none", "label": "No Filter (Baseline)"},
    {"type": "above_ma", "multiplier": 1.0, "label": "ATR > ATR_MA"},
    {"type": "above_ma", "multiplier": 1.2, "label": "ATR > 1.2x ATR_MA"},
    {"type": "above_ma", "multiplier": 1.5, "label": "ATR > 1.5x ATR_MA"},
    {"type": "fixed", "threshold": 50, "label": "ATR > 50 pts"},
    {"type": "fixed", "threshold": 75, "label": "ATR > 75 pts"},
    {"type": "fixed", "threshold": 100, "label": "ATR > 100 pts"},
]


def calculate_atr(df, period=14):
    """
    Calculate Average True Range (ATR).

    True Range = max(high - low, abs(high - prev_close), abs(low - prev_close))
    ATR = moving average of True Range
    """
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = abs(high - prev_close)
    tr3 = abs(low - prev_close)

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.rolling(window=period).mean()

    return atr


def is_in_session(timestamp):
    """Check if timestamp is within EU trading session (08:00-22:00 CET)."""
    if timestamp.tzinfo is None:
        local_time = TIMEZONE.localize(timestamp)
    else:
        local_time = timestamp.astimezone(TIMEZONE)

    current_time = local_time.time()
    return SESSION_START <= current_time <= SESSION_END


def compute_bars_lookback_sl(df, idx, lookback):
    """Calculate stop loss using N-bar lookback method."""
    if idx < lookback:
        return None

    lows = [df.iloc[idx - i]["Low"] for i in range(1, lookback + 1)]
    sl = min(lows)
    entry = df.iloc[idx]["Close"]

    if entry <= sl:
        return None

    return sl


def detect_momentum_confirm_signal(df, idx, rsi_period, cross_level):
    """
    Detect momentum confirm entry signal.

    Conditions:
    1. RSI crosses above level
    2. Current close breaks above prior bar's high
    """
    if idx < 1:
        return False

    # RSI cross-up
    current_rsi = df["RSI"].iat[idx]
    prev_rsi = df["RSI"].iat[idx - 1]
    rsi_cross_up = (prev_rsi <= cross_level) and (current_rsi > cross_level)

    if not rsi_cross_up:
        return False

    # Momentum confirmation: close breaks prior high
    current_close = df["Close"].iat[idx]
    prior_high = df["High"].iat[idx - 1]

    return current_close > prior_high


def check_atr_filter(df, idx, atr_filter):
    """
    Check if current bar passes ATR filter.

    Args:
        df: DataFrame with ATR and ATR_MA columns
        idx: Current bar index
        atr_filter: Dictionary with filter configuration

    Returns:
        bool: True if passes filter (or no filter)
    """
    if atr_filter["type"] == "none":
        return True

    current_atr = df["ATR"].iat[idx]

    if pd.isna(current_atr):
        return False

    if atr_filter["type"] == "above_ma":
        atr_ma = df["ATR_MA"].iat[idx]
        if pd.isna(atr_ma):
            return False
        threshold = atr_ma * atr_filter["multiplier"]
        return current_atr > threshold

    elif atr_filter["type"] == "fixed":
        return current_atr > atr_filter["threshold"]

    return True


def backtest_atr_filter(df, rsi_period, cross_level, sl_lookback, rr_ratio, atr_filter):
    """
    Backtest momentum confirm strategy with ATR filter.

    Args:
        df: DataFrame with OHLC data
        rsi_period: RSI calculation period
        cross_level: RSI cross-up level
        sl_lookback: Number of bars for stop loss lookback
        rr_ratio: Risk:Reward ratio
        atr_filter: ATR filter configuration
    """
    df = df.copy()
    close, high, low = df["Close"], df["High"], df["Low"]

    # Calculate indicators
    df["RSI"] = rsi(close, period=rsi_period)
    df["ATR"] = calculate_atr(df, period=ATR_PERIOD)
    df["ATR_MA"] = df["ATR"].rolling(window=ATR_MA_PERIOD).mean()

    trades = []
    in_trade = False
    entry_price = sl = tp = entry_time = None

    # Start index after warmup period
    start_idx = max(rsi_period, sl_lookback, ATR_PERIOD, ATR_MA_PERIOD)

    for i in range(start_idx, len(df)):
        ts = df.index[i]

        if not in_trade:
            # Only enter trades during session hours
            if not is_in_session(ts):
                continue

            # Check momentum confirm signal
            signal = detect_momentum_confirm_signal(df, i, rsi_period, cross_level)

            if not signal:
                continue

            # Check ATR filter
            if not check_atr_filter(df, i, atr_filter):
                continue

            # Avoid overlapping trades
            if trades and (df.index[i] <= trades[-1]["exit_time"]):
                continue

            # Calculate SL
            sl_price = compute_bars_lookback_sl(df, i, sl_lookback)
            if sl_price is None:
                continue

            entry_price = close.iat[i]
            sl = sl_price

            # Calculate TP
            risk = entry_price - sl
            if risk <= 0:
                continue

            tp = entry_price + (risk * rr_ratio)
            in_trade = True
            entry_time = ts
        else:
            # Check for exit
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
            "avg_risk_pts": 0.0, "avg_win_pts": 0.0,
            "avg_loss_pts": 0.0, "max_dd_pts": 0.0,
            "expectancy": 0.0
        }

    trades_df = pd.DataFrame(trades)
    wins = trades_df[trades_df["reason"] == "TP"]
    losses = trades_df[trades_df["reason"] == "SL"]

    total_win_pts = wins["pnl_pts"].sum() if not wins.empty else 0.0
    total_loss_pts = abs(losses["pnl_pts"].sum()) if not losses.empty else 0.0

    pf = (total_win_pts / total_loss_pts) if total_loss_pts > 0 else (999.0 if total_win_pts > 0 else 0.0)

    # Calculate drawdown
    trades_df["cumulative_pnl"] = trades_df["pnl_pts"].cumsum()
    trades_df["running_max"] = trades_df["cumulative_pnl"].cummax()
    trades_df["drawdown"] = trades_df["running_max"] - trades_df["cumulative_pnl"]
    max_dd = trades_df["drawdown"].max()

    # Calculate expectancy
    expectancy = trades_df["pnl_pts"].mean()

    return {
        "trades": len(trades_df),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(100 * len(wins) / len(trades_df), 1),
        "total_pnl_pts": round(trades_df["pnl_pts"].sum(), 2),
        "profit_factor": round(pf, 2),
        "avg_bars_held": round(trades_df["bars_held"].mean(), 1),
        "avg_risk_pts": round(trades_df["risk_pts"].mean(), 2),
        "avg_win_pts": round(wins["pnl_pts"].mean(), 2) if not wins.empty else 0.0,
        "avg_loss_pts": round(losses["pnl_pts"].mean(), 2) if not losses.empty else 0.0,
        "max_dd_pts": round(max_dd, 2),
        "expectancy": round(expectancy, 2)
    }


def main():
    print("=" * 80)
    print("📊 DAX ATR VOLATILITY FILTER OPTIMIZER")
    print("=" * 80)
    print()
    print("Strategy: Momentum Confirm + ATR Filter")
    print()
    print("Entry Signal: RSI cross-up + price breaks prior high (momentum confirm)")
    print("ATR Filter: Only trade when volatility is sufficient")
    print()
    print(f"Session Hours: {SESSION_START.strftime('%H:%M')} - {SESSION_END.strftime('%H:%M')} Europe/Berlin")
    print(f"ATR Period: {ATR_PERIOD}")
    print(f"ATR MA Period: {ATR_MA_PERIOD}")
    print()
    print(f"Testing {len(RSI_PERIODS)} RSI period(s): {RSI_PERIODS}")
    print(f"Testing {len(CROSS_UP_LEVELS)} cross-up levels: {CROSS_UP_LEVELS}")
    print(f"Testing {len(RR_RATIOS)} R:R ratio(s): {RR_RATIOS}")
    print(f"Testing {len(ATR_FILTERS)} ATR filters")
    print(f"SL Lookback: {SL_LOOKBACK} bars (fixed)")
    print()

    total_combinations = len(RSI_PERIODS) * len(CROSS_UP_LEVELS) * len(RR_RATIOS) * len(ATR_FILTERS)
    print(f"📊 Total combinations: {total_combinations}")
    print()

    # Create results directory
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Load data
    csv_files = sorted(DATA_DIR.glob("dax_*.csv"))

    if not csv_files:
        print(f"❌ No CSV files found in {DATA_DIR}")
        return

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

    # Run optimization
    print("=" * 80)
    print("🔄 Running optimization...")
    print("=" * 80)
    print()

    all_results = []
    combo_count = 0

    for atr_filter in ATR_FILTERS:
        print(f"\nTesting: {atr_filter['label']}...")

        for rsi_period in RSI_PERIODS:
            for cross_level in CROSS_UP_LEVELS:
                for rr_ratio in RR_RATIOS:
                    combo_count += 1

                    atr_label = atr_filter['label'].replace(" ", "_").replace("(", "").replace(")", "").replace(">", "gt")
                    variant_name = f"RSI{rsi_period}_L{cross_level}_RR{rr_ratio}_SL{SL_LOOKBACK}_{atr_label}"

                    result = backtest_atr_filter(
                        combined_df, rsi_period, cross_level,
                        SL_LOOKBACK, rr_ratio, atr_filter
                    )

                    result["rsi_period"] = rsi_period
                    result["cross_level"] = cross_level
                    result["rr_ratio"] = rr_ratio
                    result["sl_lookback"] = SL_LOOKBACK
                    result["atr_filter"] = atr_filter["label"]
                    result["variant"] = variant_name

                    all_results.append(result)

                    print(f"   {variant_name}: {result['total_pnl_pts']:+.2f} pts, WR: {result['win_rate_pct']:.1f}%, Trades: {result['trades']}, Expect: {result['expectancy']:+.2f}")

    print(f"\n✅ Completed all {combo_count} combinations")
    print()

    # Save results
    all_results_df = pd.DataFrame(all_results)
    output_file = RESULTS_DIR / "dax_atr_filter_results.csv"
    all_results_df.to_csv(output_file, index=False)

    # Analyze results
    print("=" * 80)
    print("📊 RESULTS SUMMARY")
    print("=" * 80)
    print()

    # Group by ATR filter
    for atr_filter in ATR_FILTERS:
        subset = all_results_df[all_results_df["atr_filter"] == atr_filter["label"]]

        if subset.empty:
            continue

        best = subset.sort_values("total_pnl_pts", ascending=False).iloc[0]

        print(f"\n{atr_filter['label']}:")
        print(f"  Best: {best['variant']}")
        print(f"  PnL: {best['total_pnl_pts']:+,.2f} pts | WR: {best['win_rate_pct']:.1f}% | Trades: {int(best['trades'])} | Expect: {best['expectancy']:+.2f} pts/trade")
        print(f"  PF: {best['profit_factor']:.2f} | Max DD: {best['max_dd_pts']:.2f} pts")

    # Head-to-head comparison
    print("\n" + "=" * 80)
    print("🎯 HEAD-TO-HEAD: BEST OF EACH ATR FILTER")
    print("=" * 80)
    print()

    best_by_filter = {}
    for atr_filter in ATR_FILTERS:
        subset = all_results_df[all_results_df["atr_filter"] == atr_filter["label"]]
        if not subset.empty:
            best = subset.sort_values("total_pnl_pts", ascending=False).iloc[0]
            best_by_filter[atr_filter["label"]] = best

    if best_by_filter:
        # Sort by profit
        sorted_best = sorted(best_by_filter.items(), key=lambda x: x[1]["total_pnl_pts"], reverse=True)

        print(f"{'ATR Filter':<25} {'PnL (pts)':>12} {'WR%':>6} {'Trades':>8} {'PF':>6} {'Expect':>8} {'MaxDD':>10}")
        print(f"{'-'*25} {'-'*12} {'-'*6} {'-'*8} {'-'*6} {'-'*8} {'-'*10}")

        for filter_label, result in sorted_best:
            print(f"{filter_label:<25} {result['total_pnl_pts']:+12.2f} {result['win_rate_pct']:6.1f} {int(result['trades']):8d} {result['profit_factor']:6.2f} {result['expectancy']:+8.2f} {result['max_dd_pts']:10.2f}")

        print()

        # Winner analysis
        winner_label, winner = sorted_best[0]
        baseline_label, baseline = next((item for item in sorted_best if "No Filter" in item[0]), (None, None))

        print(f"🏆 WINNER: {winner_label}")
        print(f"   Configuration: {winner['variant']}")
        print(f"   Total Profit: {winner['total_pnl_pts']:+,.2f} points over 3 years")
        print(f"   Win Rate: {winner['win_rate_pct']:.1f}%")
        print(f"   Total Trades: {int(winner['trades'])}")
        print(f"   Expectancy: {winner['expectancy']:+.2f} pts per trade")
        print(f"   Profit Factor: {winner['profit_factor']:.2f}")
        print(f"   Max Drawdown: {winner['max_dd_pts']:.2f} pts")
        print()

        if baseline is not None:
            pnl_improvement = winner['total_pnl_pts'] - baseline['total_pnl_pts']
            wr_improvement = winner['win_rate_pct'] - baseline['win_rate_pct']
            trades_change = int(winner['trades']) - int(baseline['trades'])
            expect_improvement = winner['expectancy'] - baseline['expectancy']
            dd_improvement = baseline['max_dd_pts'] - winner['max_dd_pts']

            print(f"📈 IMPROVEMENT vs BASELINE (No Filter):")
            print(f"   PnL: {pnl_improvement:+.2f} points ({pnl_improvement/baseline['total_pnl_pts']*100:+.1f}%)")
            print(f"   Win Rate: {wr_improvement:+.1f} percentage points")
            print(f"   Trades: {trades_change:+d} ({trades_change/baseline['trades']*100:+.1f}%)")
            print(f"   Expectancy: {expect_improvement:+.2f} pts/trade ({expect_improvement/baseline['expectancy']*100:+.1f}%)")
            print(f"   Max DD: {dd_improvement:+.2f} pts ({dd_improvement/baseline['max_dd_pts']*100:+.1f}%)")
            print()

            if winner_label != "No Filter (Baseline)":
                print(f"✅ ATR FILTER WORKS! {winner_label} outperforms baseline")
            else:
                print(f"⚠️  Baseline (no ATR filter) is still the best performer")

        print()

    print(f"💾 Full results saved to: {output_file}")
    print()
    print("=" * 80)
    print("✅ OPTIMIZATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
