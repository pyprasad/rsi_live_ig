"""
DAX LONG + SHORT Strategy Optimizer

Tests RSI strategy with BOTH directions:
- LONG: RSI crosses UP from oversold (< threshold)
- SHORT: RSI crosses DOWN from overbought (> threshold)

Compares:
1. LONG only (baseline)
2. SHORT only
3. LONG + SHORT combined

Goal: See if adding SHORT trades improves total profitability.
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
RESULTS_DIR = Path("results/dax_long_short")
TIMEZONE = pytz.timezone("Europe/Berlin")

# EU Session Configuration
SESSION_START = time(8, 0)   # 08:00 CET
SESSION_END = time(22, 0)    # 22:00 CET

# Parameter grid to test (proven winners from previous tests)
RSI_PERIODS = [2, 3, 4]
LONG_THRESHOLDS = [5, 7, 10, 15]      # LONG when RSI crosses ABOVE these
SHORT_THRESHOLDS = [70, 80, 90, 95]   # SHORT when RSI crosses BELOW these
RR_RATIOS = [2.0, 3.0, 4.0, 5.0]
SL_LOOKBACK_PERIODS = [2, 3, 4, 5]    # Test multiple SL lookback periods

# Trading modes
TRADE_MODES = ["long_only", "short_only", "both"]


def is_in_session(timestamp):
    """Check if timestamp is within EU trading session (08:00-22:00 CET)."""
    if timestamp.tzinfo is None:
        local_time = TIMEZONE.localize(timestamp)
    else:
        local_time = timestamp.astimezone(TIMEZONE)

    current_time = local_time.time()
    return SESSION_START <= current_time <= SESSION_END


def compute_sl_long(df, idx, lookback):
    """Calculate stop loss for LONG position (lowest low)."""
    if idx < lookback:
        return None

    lows = [df.iloc[idx - i]["Low"] for i in range(1, lookback + 1)]
    sl = min(lows)
    entry = df.iloc[idx]["Close"]

    if entry <= sl:
        return None

    return sl


def compute_sl_short(df, idx, lookback):
    """Calculate stop loss for SHORT position (highest high)."""
    if idx < lookback:
        return None

    highs = [df.iloc[idx - i]["High"] for i in range(1, lookback + 1)]
    sl = max(highs)
    entry = df.iloc[idx]["Close"]

    if entry >= sl:
        return None

    return sl


def backtest_long_short(df, rsi_period, long_threshold, short_threshold,
                        sl_lookback, rr_ratio, trade_mode):
    """
    Backtest strategy with LONG and/or SHORT trades.

    Args:
        df: DataFrame with OHLC data
        rsi_period: RSI calculation period
        long_threshold: RSI level for LONG entries (cross above)
        short_threshold: RSI level for SHORT entries (cross below)
        sl_lookback: Bars to look back for stop loss
        rr_ratio: Risk:Reward ratio
        trade_mode: "long_only", "short_only", or "both"
    """
    df = df.copy()
    close, high, low = df["Close"], df["High"], df["Low"]

    # Calculate RSI
    df["RSI"] = rsi(close, period=rsi_period)

    # Detect signals
    # LONG: RSI crosses from below to above threshold
    df["long_signal"] = (df["RSI"].shift(1) <= long_threshold) & (df["RSI"] > long_threshold)

    # SHORT: RSI crosses from above to below threshold
    df["short_signal"] = (df["RSI"].shift(1) >= short_threshold) & (df["RSI"] < short_threshold)

    trades = []
    in_trade = False
    position_type = None  # "long" or "short"
    entry_price = sl = tp = entry_time = None

    start_idx = max(rsi_period, sl_lookback)

    for i in range(start_idx, len(df)):
        ts = df.index[i]

        if not in_trade:
            # Only enter during session hours
            if not is_in_session(ts):
                continue

            # Check LONG signal
            if trade_mode in ["long_only", "both"] and df["long_signal"].iat[i]:
                # Avoid overlapping trades
                if trades and (df.index[i] <= trades[-1]["exit_time"]):
                    continue

                # Calculate SL for LONG
                sl_price = compute_sl_long(df, i, sl_lookback)
                if sl_price is None:
                    continue

                entry_price = close.iat[i]
                sl = sl_price
                risk = entry_price - sl

                if risk <= 0:
                    continue

                tp = entry_price + (risk * rr_ratio)
                in_trade = True
                position_type = "long"
                entry_time = ts

            # Check SHORT signal (only if not already in LONG)
            elif trade_mode in ["short_only", "both"] and df["short_signal"].iat[i]:
                # Avoid overlapping trades
                if trades and (df.index[i] <= trades[-1]["exit_time"]):
                    continue

                # Calculate SL for SHORT
                sl_price = compute_sl_short(df, i, sl_lookback)
                if sl_price is None:
                    continue

                entry_price = close.iat[i]
                sl = sl_price
                risk = sl - entry_price  # Risk is reversed for SHORT

                if risk <= 0:
                    continue

                tp = entry_price - (risk * rr_ratio)  # TP is below entry for SHORT
                in_trade = True
                position_type = "short"
                entry_time = ts

        else:
            # Check for exit
            bar_low, bar_high = low.iat[i], high.iat[i]

            if position_type == "long":
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
                        "side": "LONG",
                        "pnl_pts": float(pnl_pts),
                        "bars_held": i - df.index.get_loc(entry_time),
                        "risk_pts": float(entry_price - sl)
                    })

                    in_trade = False
                    position_type = None

            elif position_type == "short":
                sl_hit = bar_high >= sl
                tp_hit = bar_low <= tp

                if sl_hit or tp_hit:
                    exit_reason = "SL" if sl_hit else "TP"
                    exit_price = sl if sl_hit else tp
                    pnl_pts = entry_price - exit_price  # Reversed for SHORT

                    trades.append({
                        "entry_time": entry_time,
                        "entry": float(entry_price),
                        "exit_time": ts,
                        "exit": float(exit_price),
                        "reason": exit_reason,
                        "side": "SHORT",
                        "pnl_pts": float(pnl_pts),
                        "bars_held": i - df.index.get_loc(entry_time),
                        "risk_pts": float(sl - entry_price)
                    })

                    in_trade = False
                    position_type = None

    # Calculate statistics
    if not trades:
        return {
            "trades": 0, "wins": 0, "losses": 0,
            "long_trades": 0, "short_trades": 0,
            "win_rate_pct": 0.0, "total_pnl_pts": 0.0,
            "profit_factor": 0.0, "expectancy": 0.0,
            "max_dd_pts": 0.0
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

    # Count LONG vs SHORT
    long_trades = len(trades_df[trades_df["side"] == "LONG"])
    short_trades = len(trades_df[trades_df["side"] == "SHORT"])

    return {
        "trades": len(trades_df),
        "wins": len(wins),
        "losses": len(losses),
        "long_trades": long_trades,
        "short_trades": short_trades,
        "win_rate_pct": round(100 * len(wins) / len(trades_df), 1),
        "total_pnl_pts": round(trades_df["pnl_pts"].sum(), 2),
        "profit_factor": round(pf, 2),
        "expectancy": round(trades_df["pnl_pts"].mean(), 2),
        "max_dd_pts": round(max_dd, 2)
    }


def main():
    print("=" * 80)
    print("📊 DAX LONG + SHORT STRATEGY OPTIMIZER")
    print("=" * 80)
    print()
    print("Testing RSI strategy in BOTH directions:")
    print()
    print("LONG Signals:")
    print("  - RSI crosses ABOVE threshold (e.g., RSI crosses above 10)")
    print("  - Entry: Close, SL: Lowest of last 2 bars, TP: Entry + (Risk × R:R)")
    print()
    print("SHORT Signals:")
    print("  - RSI crosses BELOW threshold (e.g., RSI crosses below 90)")
    print("  - Entry: Close, SL: Highest of last 2 bars, TP: Entry - (Risk × R:R)")
    print()
    print(f"Session Hours: {SESSION_START.strftime('%H:%M')} - {SESSION_END.strftime('%H:%M')} Europe/Berlin")
    print()
    print(f"Testing {len(RSI_PERIODS)} RSI periods: {RSI_PERIODS}")
    print(f"Testing {len(LONG_THRESHOLDS)} LONG thresholds: {LONG_THRESHOLDS}")
    print(f"Testing {len(SHORT_THRESHOLDS)} SHORT thresholds: {SHORT_THRESHOLDS}")
    print(f"Testing {len(RR_RATIOS)} R:R ratios: {RR_RATIOS}")
    print(f"Testing {len(SL_LOOKBACK_PERIODS)} SL lookback periods: {SL_LOOKBACK_PERIODS}")
    print(f"Testing {len(TRADE_MODES)} trade modes: {TRADE_MODES}")
    print()

    # Calculate total combinations
    total_per_mode = len(RSI_PERIODS) * len(LONG_THRESHOLDS) * len(SHORT_THRESHOLDS) * len(RR_RATIOS) * len(SL_LOOKBACK_PERIODS)
    total_combinations = total_per_mode * len(TRADE_MODES)

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

    # Calculate actual time period in years
    date_range_days = (combined_df.index.max() - combined_df.index.min()).days
    years_in_data = date_range_days / 365.25
    print(f"📅 Time Period: {years_in_data:.2f} years ({date_range_days} days)")
    print()

    # Run optimization
    print("=" * 80)
    print("🔄 Running optimization...")
    print("=" * 80)
    print()

    all_results = []
    combo_count = 0

    for trade_mode in TRADE_MODES:
        mode_label = trade_mode.replace("_", " ").upper()
        print(f"\n{'='*80}")
        print(f"Testing {mode_label}...")
        print(f"{'='*80}\n")

        for rsi_period in RSI_PERIODS:
            for long_threshold in LONG_THRESHOLDS:
                for short_threshold in SHORT_THRESHOLDS:
                    for rr_ratio in RR_RATIOS:
                        for sl_lookback in SL_LOOKBACK_PERIODS:
                            combo_count += 1

                            variant_name = f"RSI{rsi_period}_L{long_threshold}_S{short_threshold}_RR{rr_ratio}_SL{sl_lookback}_{trade_mode}"

                            result = backtest_long_short(
                                combined_df, rsi_period, long_threshold, short_threshold,
                                sl_lookback, rr_ratio, trade_mode
                            )

                            result["rsi_period"] = rsi_period
                            result["long_threshold"] = long_threshold
                            result["short_threshold"] = short_threshold
                            result["rr_ratio"] = rr_ratio
                            result["sl_lookback"] = sl_lookback
                            result["trade_mode"] = trade_mode
                            result["variant"] = variant_name

                            all_results.append(result)

                            if combo_count % 100 == 0:
                                print(f"   Tested {combo_count}/{total_combinations} combinations...")

    print(f"\n✅ Completed all {combo_count} combinations")
    print()

    # Save results
    all_results_df = pd.DataFrame(all_results)
    output_file = RESULTS_DIR / "dax_long_short_results.csv"
    all_results_df.to_csv(output_file, index=False)

    # Analyze results by trade mode
    print("=" * 80)
    print("📊 RESULTS BY TRADE MODE")
    print("=" * 80)
    print()

    best_by_mode = {}

    for mode in TRADE_MODES:
        subset = all_results_df[all_results_df["trade_mode"] == mode]
        profitable = subset[subset["total_pnl_pts"] > 0]

        mode_label = mode.replace("_", " ").upper()
        print(f"\n{'='*80}")
        print(f"🔍 {mode_label}")
        print(f"{'='*80}\n")

        if len(profitable) > 0:
            profitable = profitable.sort_values("total_pnl_pts", ascending=False)
            best = profitable.iloc[0]
            best_by_mode[mode_label] = best

            print(f"✅ Found {len(profitable)} profitable variants")
            print()
            print(f"🏆 BEST PERFORMER:")
            print(f"   Variant: {best['variant']}")
            print(f"   Total PnL: {best['total_pnl_pts']:+,.2f} points")
            print(f"   Annual Average: {best['total_pnl_pts']/years_in_data:+,.2f} pts/year")
            print(f"   Win Rate: {best['win_rate_pct']:.1f}%")
            print(f"   Total Trades: {int(best['trades'])} ({int(best['trades'])/years_in_data:.1f}/year)")

            if mode != "short_only":
                print(f"   LONG Trades: {int(best['long_trades'])}")
            if mode != "long_only":
                print(f"   SHORT Trades: {int(best['short_trades'])}")

            print(f"   Expectancy: {best['expectancy']:+.2f} pts/trade")
            print(f"   Profit Factor: {best['profit_factor']:.2f}")
            print(f"   Max Drawdown: {best['max_dd_pts']:.2f} pts")
            print()

            print(f"📋 TOP 5 VARIANTS:")
            print(f"   {'Variant':<55} {'PnL':>10} {'WR%':>6} {'Trades':>7} {'Expect':>8}")
            print(f"   {'-'*55} {'-'*10} {'-'*6} {'-'*7} {'-'*8}")
            for idx, row in profitable.head(5).iterrows():
                print(f"   {row['variant']:<55} {row['total_pnl_pts']:+10.2f} {row['win_rate_pct']:6.1f} {int(row['trades']):7d} {row['expectancy']:+8.2f}")
            print()
        else:
            print(f"❌ No profitable variants found")
            print()

    # Head-to-head comparison
    print("\n" + "=" * 80)
    print("🎯 HEAD-TO-HEAD: LONG vs SHORT vs BOTH")
    print("=" * 80)
    print()

    if best_by_mode:
        print(f"{'Mode':<15} {'PnL (pts)':>12} {'WR%':>6} {'Trades':>8} {'L/S Split':>12} {'Expect':>8} {'PF':>6}")
        print(f"{'-'*15} {'-'*12} {'-'*6} {'-'*8} {'-'*12} {'-'*8} {'-'*6}")

        for mode_label in ["LONG ONLY", "SHORT ONLY", "BOTH"]:
            if mode_label in best_by_mode:
                result = best_by_mode[mode_label]

                if mode_label == "BOTH":
                    split = f"{int(result['long_trades'])}/{int(result['short_trades'])}"
                elif mode_label == "LONG ONLY":
                    split = f"{int(result['long_trades'])}/0"
                else:
                    split = f"0/{int(result['short_trades'])}"

                print(f"{mode_label:<15} {result['total_pnl_pts']:+12.2f} {result['win_rate_pct']:6.1f} {int(result['trades']):8d} {split:>12} {result['expectancy']:+8.2f} {result['profit_factor']:6.2f}")

        print()

        # Winner analysis
        winner = max(best_by_mode.items(), key=lambda x: x[1]["total_pnl_pts"])
        winner_label, winner_data = winner

        print(f"🏆 WINNER: {winner_label}")
        print(f"   Total Profit: {winner_data['total_pnl_pts']:+,.2f} points over {years_in_data:.2f} years")
        print(f"   Annual: {winner_data['total_pnl_pts']/years_in_data:+,.2f} pts/year")
        print()

        # Compare BOTH vs LONG ONLY
        if "BOTH" in best_by_mode and "LONG ONLY" in best_by_mode:
            both = best_by_mode["BOTH"]
            long = best_by_mode["LONG ONLY"]

            print(f"📈 ADDING SHORT TRADES:")
            pnl_diff = both['total_pnl_pts'] - long['total_pnl_pts']
            pnl_pct = (pnl_diff / long['total_pnl_pts']) * 100
            trades_diff = int(both['trades']) - int(long['trades'])

            print(f"   PnL Change: {pnl_diff:+.2f} pts ({pnl_pct:+.1f}%)")
            print(f"   Additional Trades: {trades_diff:+d}")
            print(f"   SHORT Contribution: {both['total_pnl_pts'] - long['total_pnl_pts']:+.2f} pts (estimated)")
            print()

            if pnl_diff > 0:
                print(f"✅ Adding SHORT trades IMPROVES strategy by {pnl_pct:+.1f}%")
            else:
                print(f"⚠️  Adding SHORT trades HURTS strategy by {abs(pnl_pct):.1f}%")

        print()

    print(f"💾 Full results saved to: {output_file}")
    print()
    print("=" * 80)
    print("✅ OPTIMIZATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
