"""
Advanced DAX Strategy Optimizer - Tests Multiple Parameters
Tests combinations of RSI period, cross-up level, SL lookback, and R:R ratios.
Finds the most profitable and consistent strategy variant.
"""
import pandas as pd
import numpy as np
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from strategy_core import rsi

# Configuration
DATA_DIR = Path("data/dax_monthly")
RESULTS_DIR = Path("results/dax_advanced")

# Parameter grid to test
RSI_PERIODS = [2, 3, 4, 5]                    # RSI calculation period
CROSS_UP_LEVELS = [5, 10, 15, 20]             # Entry threshold
SL_LOOKBACK_PERIODS = [2, 3, 4, 5]            # Bars to look back for SL
RR_RATIOS = [1.0, 1.5, 2.0, 3.0, 4.0, 5.0]    # Risk:Reward ratios

def rsi_cross_up_custom(series, level, period):
    """Custom RSI cross-up detection with configurable level and period."""
    rsi_series = rsi(series, period=period)
    prev_below = rsi_series.shift(1) <= level
    curr_above = rsi_series > level
    return prev_below & curr_above

def compute_sl_custom(df, idx, lookback):
    """Calculate stop loss using custom lookback period."""
    if idx < lookback:
        return None

    lows = [df.iloc[idx - i]["Low"] for i in range(1, lookback + 1)]
    sl = min(lows)
    entry = df.iloc[idx]["Close"]

    if entry <= sl:
        return None

    return sl

def backtest_variant(df, rsi_period, cross_level, sl_lookback, rr_ratio):
    """Run backtest with specific parameter combination."""
    df = df.copy()
    close, high, low = df["Close"], df["High"], df["Low"]

    # Calculate RSI with custom period
    df["RSI"] = rsi(close, period=rsi_period)
    df["signal"] = rsi_cross_up_custom(close, level=cross_level, period=rsi_period)

    trades = []
    in_trade = False
    entry_price = sl = tp = entry_time = None

    for i in range(max(rsi_period, sl_lookback), len(df)):
        ts = df.index[i]

        if not in_trade:
            # Check for entry signal
            if bool(df["signal"].iat[i]):
                if trades and (df.index[i] <= trades[-1]["exit_time"]):
                    continue

                # Calculate SL with custom lookback
                sl_price = compute_sl_custom(df, i, sl_lookback)
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
                    "bars_held": i - df.index.get_loc(entry_time)
                })

                in_trade = False
                entry_price = sl = tp = entry_time = None

    # Calculate statistics
    if not trades:
        return {
            "trades": 0, "wins": 0, "losses": 0,
            "win_rate_pct": 0.0, "total_pnl_pts": 0.0,
            "profit_factor": 0.0, "avg_bars_held": 0.0
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
        "avg_bars_held": round(trades_df["bars_held"].mean(), 1)
    }

def main():
    print("=" * 80)
    print("🔬 DAX ADVANCED STRATEGY OPTIMIZER")
    print("=" * 80)
    print()
    print(f"Testing {len(RSI_PERIODS)} RSI periods: {RSI_PERIODS}")
    print(f"Testing {len(CROSS_UP_LEVELS)} cross-up levels: {CROSS_UP_LEVELS}")
    print(f"Testing {len(SL_LOOKBACK_PERIODS)} SL lookback periods: {SL_LOOKBACK_PERIODS}")
    print(f"Testing {len(RR_RATIOS)} R:R ratios: {RR_RATIOS}")
    print()

    total_combinations = (len(RSI_PERIODS) * len(CROSS_UP_LEVELS) *
                         len(SL_LOOKBACK_PERIODS) * len(RR_RATIOS))
    print(f"📊 Total combinations to test: {total_combinations}")
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
        df["Datetime"] = pd.to_datetime(df["Datetime"])
        dfs.append(df)

    combined_df = pd.concat(dfs, ignore_index=True)
    combined_df = combined_df.set_index("Datetime")
    combined_df = combined_df.sort_index()

    print(f"✅ Loaded {len(combined_df)} total bars")
    print(f"📅 Date Range: {combined_df.index.min()} to {combined_df.index.max()}")
    print()

    all_results = []
    combo_count = 0

    print("🔄 Testing all combinations...")
    print()

    # Test all combinations
    for rsi_period in RSI_PERIODS:
        for cross_level in CROSS_UP_LEVELS:
            for sl_lookback in SL_LOOKBACK_PERIODS:
                for rr_ratio in RR_RATIOS:
                    combo_count += 1

                    variant_name = f"RSI{rsi_period}_L{cross_level}_SL{sl_lookback}_RR{rr_ratio}"

                    # Run backtest
                    result = backtest_variant(combined_df, rsi_period, cross_level, sl_lookback, rr_ratio)

                    result["rsi_period"] = rsi_period
                    result["cross_level"] = cross_level
                    result["sl_lookback"] = sl_lookback
                    result["rr_ratio"] = rr_ratio
                    result["variant"] = variant_name

                    all_results.append(result)

                    # Show progress every 50 combinations
                    if combo_count % 50 == 0:
                        print(f"   Tested {combo_count}/{total_combinations} combinations...")

    print(f"✅ Completed {combo_count} combinations")
    print()

    # Save all results
    results_df = pd.DataFrame(all_results)
    output_file = RESULTS_DIR / "dax_advanced_all_results.csv"
    results_df.to_csv(output_file, index=False)

    # Analyze results
    print("=" * 80)
    print("📊 OPTIMIZATION RESULTS")
    print("=" * 80)
    print()

    # Filter profitable variants only
    profitable = results_df[results_df["total_pnl_pts"] > 0].copy()

    if len(profitable) == 0:
        print("❌ No profitable variants found!")
        print(f"💾 Full results saved to: {output_file}")
        return

    # Sort by total PnL
    profitable = profitable.sort_values("total_pnl_pts", ascending=False)

    print(f"✅ Found {len(profitable)} profitable variants (out of {total_combinations})")
    print()

    # Top 10 by profit
    print("🏆 TOP 10 BY TOTAL PROFIT:")
    print("-" * 80)
    for idx, row in profitable.head(10).iterrows():
        print(f"{row['variant']:30s} | PnL: {row['total_pnl_pts']:+8.2f} pts | "
              f"Trades: {row['trades']:3d} | Win Rate: {row['win_rate_pct']:5.1f}% | "
              f"PF: {row['profit_factor']:5.2f}")
    print()

    # Top 10 by win rate
    print("🎯 TOP 10 BY WIN RATE:")
    print("-" * 80)
    top_winrate = profitable.sort_values("win_rate_pct", ascending=False).head(10)
    for idx, row in top_winrate.iterrows():
        print(f"{row['variant']:30s} | Win Rate: {row['win_rate_pct']:5.1f}% | "
              f"PnL: {row['total_pnl_pts']:+8.2f} pts | Trades: {row['trades']:3d} | "
              f"PF: {row['profit_factor']:5.2f}")
    print()

    # Best overall
    best = profitable.iloc[0]
    print("🎯 BEST OVERALL STRATEGY:")
    print("-" * 80)
    print(f"Variant: {best['variant']}")
    print(f"  RSI Period: {best['rsi_period']}")
    print(f"  Cross-Up Level: {best['cross_level']}")
    print(f"  SL Lookback: {best['sl_lookback']} bars")
    print(f"  Risk:Reward: {best['rr_ratio']}")
    print()
    print(f"Performance:")
    print(f"  Total PnL: {best['total_pnl_pts']:+.2f} points")
    print(f"  Total Trades: {int(best['trades'])}")
    print(f"  Win Rate: {best['win_rate_pct']:.1f}%")
    print(f"  Profit Factor: {best['profit_factor']:.2f}")
    print(f"  Avg Bars Held: {best['avg_bars_held']:.1f}")
    print()

    print(f"💾 Detailed results saved to: {output_file}")
    print()

if __name__ == "__main__":
    main()
