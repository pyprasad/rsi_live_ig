"""
DAX Mean Reversion Strategy Optimizer

OPPOSITE of momentum strategy - buy extreme oversold conditions.

Strategy Logic:
- LONG when RSI drops BELOW threshold (e.g., RSI < 20)
- Bet on mean reversion (price bounces back from extreme)
- Exit with fixed R:R ratio or opposite extreme

Entry Variations:
1. RSI crosses below threshold (e.g., RSI crosses below 20)
2. RSI below threshold + momentum confirm (close breaks prior LOW - capitulation)
3. RSI below threshold + ATR filter (only in volatile markets)

Test different:
- RSI thresholds: 10, 15, 20, 25, 30
- R:R ratios: 1.5, 2.0, 2.5, 3.0, 4.0, 5.0
- Entry types: standard, momentum confirm, ATR filter
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
RESULTS_DIR = Path("results/dax_mean_reversion")
TIMEZONE = pytz.timezone("Europe/Berlin")

# EU Session Configuration
SESSION_START = time(8, 0)   # 08:00 CET
SESSION_END = time(22, 0)    # 22:00 CET

# Parameter grid to test
RSI_PERIODS = [2, 3, 4]
RSI_THRESHOLDS = [10, 15, 20, 25, 30]  # Enter when RSI BELOW these levels
RR_RATIOS = [1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
SL_LOOKBACK = 2  # Fixed at 2 bars

# Entry types
ENTRY_TYPES = [
    "standard",           # RSI crosses below threshold
    "momentum_confirm",   # RSI below threshold + price breaks prior LOW (capitulation)
]


def calculate_atr(df, period=14):
    """Calculate Average True Range (ATR)."""
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


def detect_mean_reversion_signal(df, idx, rsi_period, threshold, entry_type):
    """
    Detect mean reversion entry signal.

    Standard: RSI crosses BELOW threshold (opposite of momentum)
    Momentum Confirm: RSI below threshold + price breaks BELOW prior low (capitulation)

    Args:
        df: DataFrame with OHLC and RSI data
        idx: Current bar index
        rsi_period: RSI period
        threshold: RSI threshold (enter when RSI < this)
        entry_type: Type of entry signal

    Returns:
        bool: True if entry signal detected
    """
    if idx < 1:
        return False

    current_rsi = df["RSI"].iat[idx]
    prev_rsi = df["RSI"].iat[idx - 1]

    if entry_type == "standard":
        # RSI crosses BELOW threshold (enters oversold zone)
        rsi_cross_down = (prev_rsi >= threshold) and (current_rsi < threshold)
        return rsi_cross_down

    elif entry_type == "momentum_confirm":
        # RSI already below threshold + price breaks BELOW prior low (capitulation)
        rsi_below = current_rsi < threshold

        if not rsi_below:
            return False

        # Capitulation: current close breaks below prior bar's low
        current_close = df["Close"].iat[idx]
        prior_low = df["Low"].iat[idx - 1]

        return current_close < prior_low

    return False


def backtest_mean_reversion(df, rsi_period, threshold, sl_lookback, rr_ratio, entry_type):
    """
    Backtest mean reversion strategy.

    Buy extreme oversold conditions, expecting bounce.

    Args:
        df: DataFrame with OHLC data
        rsi_period: RSI calculation period
        threshold: RSI threshold (buy when RSI < this)
        sl_lookback: Number of bars for stop loss lookback
        rr_ratio: Risk:Reward ratio
        entry_type: Entry signal type
    """
    df = df.copy()
    close, high, low = df["Close"], df["High"], df["Low"]

    # Calculate indicators
    df["RSI"] = rsi(close, period=rsi_period)

    trades = []
    in_trade = False
    entry_price = sl = tp = entry_time = None

    # Start index after warmup period
    start_idx = max(rsi_period, sl_lookback)

    for i in range(start_idx, len(df)):
        ts = df.index[i]

        if not in_trade:
            # Only enter trades during session hours
            if not is_in_session(ts):
                continue

            # Check for mean reversion signal
            signal = detect_mean_reversion_signal(df, i, rsi_period, threshold, entry_type)

            if not signal:
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
    print("🔄 DAX MEAN REVERSION STRATEGY OPTIMIZER")
    print("=" * 80)
    print()
    print("Strategy: Buy extreme OVERSOLD conditions (opposite of momentum)")
    print()
    print("Logic:")
    print("  - Momentum strategy: RSI crosses UP from oversold → Buy dip in uptrend")
    print("  - Mean Reversion: RSI crosses DOWN below threshold → Buy panic selling")
    print()
    print("Entry Types:")
    print("  1. STANDARD: RSI crosses below threshold (e.g., RSI < 20)")
    print("  2. MOMENTUM CONFIRM: RSI < threshold + price breaks prior LOW (capitulation)")
    print()
    print(f"Session Hours: {SESSION_START.strftime('%H:%M')} - {SESSION_END.strftime('%H:%M')} Europe/Berlin")
    print()
    print(f"Testing {len(RSI_PERIODS)} RSI periods: {RSI_PERIODS}")
    print(f"Testing {len(RSI_THRESHOLDS)} RSI thresholds: {RSI_THRESHOLDS}")
    print(f"Testing {len(RR_RATIOS)} R:R ratios: {RR_RATIOS}")
    print(f"Testing {len(ENTRY_TYPES)} entry types: {ENTRY_TYPES}")
    print(f"SL Lookback: {SL_LOOKBACK} bars (fixed)")
    print()

    total_combinations = len(RSI_PERIODS) * len(RSI_THRESHOLDS) * len(RR_RATIOS) * len(ENTRY_TYPES)
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

    for entry_type in ENTRY_TYPES:
        entry_label = entry_type.replace("_", " ").title()
        print(f"\n{'='*80}")
        print(f"Testing {entry_label}...")
        print(f"{'='*80}\n")

        for rsi_period in RSI_PERIODS:
            for threshold in RSI_THRESHOLDS:
                for rr_ratio in RR_RATIOS:
                    combo_count += 1

                    variant_name = f"RSI{rsi_period}_T{threshold}_RR{rr_ratio}_SL{SL_LOOKBACK}_{entry_type}"

                    result = backtest_mean_reversion(
                        combined_df, rsi_period, threshold,
                        SL_LOOKBACK, rr_ratio, entry_type
                    )

                    result["rsi_period"] = rsi_period
                    result["rsi_threshold"] = threshold
                    result["rr_ratio"] = rr_ratio
                    result["sl_lookback"] = SL_LOOKBACK
                    result["entry_type"] = entry_type
                    result["entry_label"] = entry_label
                    result["variant"] = variant_name

                    all_results.append(result)

                    if combo_count % 20 == 0:
                        print(f"   Tested {combo_count}/{total_combinations} combinations...")

    print(f"\n✅ Completed all {combo_count} combinations")
    print()

    # Save results
    all_results_df = pd.DataFrame(all_results)
    output_file = RESULTS_DIR / "dax_mean_reversion_results.csv"
    all_results_df.to_csv(output_file, index=False)

    # Analyze results
    print("=" * 80)
    print("📊 RESULTS BY ENTRY TYPE")
    print("=" * 80)
    print()

    for entry_type in ENTRY_TYPES:
        entry_label = entry_type.replace("_", " ").title()

        subset = all_results_df[all_results_df["entry_type"] == entry_type]
        profitable = subset[subset["total_pnl_pts"] > 0].copy()

        print(f"\n{'='*80}")
        print(f"🔍 {entry_label.upper()}")
        print(f"{'='*80}\n")

        if len(profitable) > 0:
            profitable = profitable.sort_values("total_pnl_pts", ascending=False)
            best = profitable.iloc[0]

            print(f"✅ Found {len(profitable)} profitable variants out of {len(subset)} tested")
            print()
            print(f"🏆 BEST PERFORMER:")
            print(f"   Variant: {best['variant']}")
            print(f"   Total PnL: {best['total_pnl_pts']:+,.2f} points")
            print(f"   Win Rate: {best['win_rate_pct']:.1f}%")
            print(f"   Total Trades: {int(best['trades'])}")
            print(f"   Wins/Losses: {int(best['wins'])}/{int(best['losses'])}")
            print(f"   Profit Factor: {best['profit_factor']:.2f}")
            print(f"   Expectancy: {best['expectancy']:+.2f} pts per trade")
            print(f"   Avg Win: {best['avg_win_pts']:+.2f} pts")
            print(f"   Avg Loss: {best['avg_loss_pts']:.2f} pts")
            print(f"   Max Drawdown: {best['max_dd_pts']:.2f} pts")
            print()

            if len(profitable) > 1:
                print(f"📋 TOP 10 VARIANTS:")
                print(f"   {'Variant':<45} {'PnL':>10} {'WR%':>6} {'Trades':>7} {'Expect':>8}")
                print(f"   {'-'*45} {'-'*10} {'-'*6} {'-'*7} {'-'*8}")
                for idx, row in profitable.head(10).iterrows():
                    print(f"   {row['variant']:<45} {row['total_pnl_pts']:+10.2f} {row['win_rate_pct']:6.1f} {int(row['trades']):7d} {row['expectancy']:+8.2f}")
                print()
        else:
            print(f"❌ No profitable variants found for {entry_label}")
            print()

    # Overall best
    print("\n" + "=" * 80)
    print("🎯 OVERALL BEST MEAN REVERSION CONFIGURATION")
    print("=" * 80)
    print()

    all_profitable = all_results_df[all_results_df["total_pnl_pts"] > 0]

    if len(all_profitable) > 0:
        best_overall = all_profitable.sort_values("total_pnl_pts", ascending=False).iloc[0]

        print(f"🏆 WINNER: {best_overall['entry_label']}")
        print(f"   Configuration: {best_overall['variant']}")
        print(f"   Total Profit: {best_overall['total_pnl_pts']:+,.2f} points over 3 years")
        print(f"   Annual Average: {best_overall['total_pnl_pts']/3:+,.2f} pts/year")
        print(f"   Win Rate: {best_overall['win_rate_pct']:.1f}%")
        print(f"   Total Trades: {int(best_overall['trades'])} ({int(best_overall['trades'])/3:.1f}/year)")
        print(f"   Expectancy: {best_overall['expectancy']:+.2f} pts per trade")
        print(f"   Profit Factor: {best_overall['profit_factor']:.2f}")
        print(f"   Max Drawdown: {best_overall['max_dd_pts']:.2f} pts")
        print()

        # Compare to momentum strategy baseline
        print("=" * 80)
        print("📊 COMPARISON: MEAN REVERSION vs MOMENTUM STRATEGY")
        print("=" * 80)
        print()

        momentum_baseline = {
            "name": "Momentum (No Filter)",
            "pnl": 3199.45,
            "wr": 20.0,
            "trades": 285,
            "expectancy": 11.23,
            "pf": 1.26,
            "max_dd": 1177.28
        }

        print(f"{'Metric':<20} {'Mean Reversion':>18} {'Momentum':>18} {'Difference':>18}")
        print(f"{'-'*20} {'-'*18} {'-'*18} {'-'*18}")
        print(f"{'Total PnL (pts)':<20} {best_overall['total_pnl_pts']:+18.2f} {momentum_baseline['pnl']:+18.2f} {best_overall['total_pnl_pts']-momentum_baseline['pnl']:+18.2f}")
        print(f"{'Win Rate (%)':<20} {best_overall['win_rate_pct']:18.1f} {momentum_baseline['wr']:18.1f} {best_overall['win_rate_pct']-momentum_baseline['wr']:+18.1f}")
        print(f"{'Total Trades':<20} {int(best_overall['trades']):18d} {momentum_baseline['trades']:18d} {int(best_overall['trades'])-momentum_baseline['trades']:+18d}")
        print(f"{'Expectancy (pts)':<20} {best_overall['expectancy']:+18.2f} {momentum_baseline['expectancy']:+18.2f} {best_overall['expectancy']-momentum_baseline['expectancy']:+18.2f}")
        print(f"{'Profit Factor':<20} {best_overall['profit_factor']:18.2f} {momentum_baseline['pf']:18.2f} {best_overall['profit_factor']-momentum_baseline['pf']:+18.2f}")
        print(f"{'Max Drawdown':<20} {best_overall['max_dd_pts']:18.2f} {momentum_baseline['max_dd']:18.2f} {best_overall['max_dd_pts']-momentum_baseline['max_dd']:+18.2f}")
        print()

        if best_overall['total_pnl_pts'] > momentum_baseline['pnl']:
            improvement_pct = ((best_overall['total_pnl_pts'] - momentum_baseline['pnl']) / momentum_baseline['pnl']) * 100
            print(f"✅ MEAN REVERSION WINS! {improvement_pct:+.1f}% more profitable than momentum")
        else:
            decline_pct = ((best_overall['total_pnl_pts'] - momentum_baseline['pnl']) / momentum_baseline['pnl']) * 100
            print(f"⚠️  Momentum strategy still better ({decline_pct:.1f}% more profitable)")

        print()

    else:
        print("❌ No profitable mean reversion configurations found")
        print()

    print(f"💾 Full results saved to: {output_file}")
    print()
    print("=" * 80)
    print("✅ OPTIMIZATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
