"""
DAX Entry Signal Optimizer

Tests different entry signal variations to improve win rate:
1. Deeper oversold levels (RSI < 3, 5, 7, 10, 15, 20)
2. Momentum confirmation (price breaks above prior bar high)
3. Combination approaches

Goal: Find more selective entry signals that improve win rate while maintaining profitability.
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
RESULTS_DIR = Path("results/dax_entry_signals")
TIMEZONE = pytz.timezone("Europe/Berlin")

# EU Session Configuration
SESSION_START = time(8, 0)   # 08:00 CET
SESSION_END = time(22, 0)    # 22:00 CET

# Parameter grid to test
RSI_PERIODS = [2, 3, 4]
CROSS_UP_LEVELS = [3, 5, 7, 10, 15, 20]  # Test deeper oversold levels
RR_RATIOS = [3.0, 4.0, 5.0]
SL_LOOKBACK = 2  # Fixed at 2 (proven winner)

# Entry signal types to test
ENTRY_TYPES = [
    "standard",           # Standard RSI cross-up (baseline)
    "momentum_confirm",   # RSI cross-up + price breaks prior high
    "double_confirm"      # RSI cross-up + price > prior close + breaks prior high
]


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


def detect_entry_signal(df, idx, rsi_period, cross_level, entry_type):
    """
    Detect entry signal based on entry type.

    Args:
        df: DataFrame with OHLC and RSI data
        idx: Current bar index
        rsi_period: RSI period
        cross_level: RSI cross-up level
        entry_type: Type of entry signal to use

    Returns:
        bool: True if entry signal detected
    """
    if idx < 1:
        return False

    # Get current and previous RSI values
    current_rsi = df["RSI"].iat[idx]
    prev_rsi = df["RSI"].iat[idx - 1]

    # Base condition: RSI crosses above level
    rsi_cross_up = (prev_rsi <= cross_level) and (current_rsi > cross_level)

    if not rsi_cross_up:
        return False

    # Apply additional filters based on entry type
    if entry_type == "standard":
        # Standard RSI cross-up (no additional filters)
        return True

    elif entry_type == "momentum_confirm":
        # RSI cross-up + current close breaks above prior bar's high
        current_close = df["Close"].iat[idx]
        prior_high = df["High"].iat[idx - 1]
        return current_close > prior_high

    elif entry_type == "double_confirm":
        # RSI cross-up + close > prior close + breaks prior high
        current_close = df["Close"].iat[idx]
        prior_close = df["Close"].iat[idx - 1]
        prior_high = df["High"].iat[idx - 1]
        return (current_close > prior_close) and (current_close > prior_high)

    return False


def backtest_entry_signal(df, rsi_period, cross_level, sl_lookback, rr_ratio, entry_type):
    """
    Backtest RSI strategy with specified entry signal type.

    Args:
        df: DataFrame with OHLC data
        rsi_period: RSI calculation period
        cross_level: RSI cross-up level
        sl_lookback: Number of bars to look back for stop loss
        rr_ratio: Risk:Reward ratio
        entry_type: Type of entry signal to use
    """
    df = df.copy()
    close, high, low = df["Close"], df["High"], df["Low"]

    # Calculate RSI
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

            # Check for entry signal using specified entry type
            signal = detect_entry_signal(df, i, rsi_period, cross_level, entry_type)

            if signal:
                # Avoid overlapping trades
                if trades and (df.index[i] <= trades[-1]["exit_time"]):
                    continue

                # Calculate SL using bars lookback
                sl_price = compute_bars_lookback_sl(df, i, sl_lookback)
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

    # Calculate expectancy (average profit per trade)
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
    print("🎯 DAX ENTRY SIGNAL OPTIMIZER")
    print("=" * 80)
    print()
    print("Testing different entry signal variations:")
    print()
    print("1. STANDARD: RSI crosses above level")
    print("   - Baseline approach")
    print()
    print("2. MOMENTUM CONFIRM: RSI crosses up + price breaks prior high")
    print("   - Ensures upward momentum on entry")
    print("   - More selective (fewer trades, potentially higher quality)")
    print()
    print("3. DOUBLE CONFIRM: RSI crosses up + close > prior close + breaks prior high")
    print("   - Most selective (requires both higher close AND breakout)")
    print("   - Fewest trades, potentially highest quality")
    print()
    print(f"Session Hours: {SESSION_START.strftime('%H:%M')} - {SESSION_END.strftime('%H:%M')} Europe/Berlin")
    print()
    print(f"Testing {len(RSI_PERIODS)} RSI periods: {RSI_PERIODS}")
    print(f"Testing {len(CROSS_UP_LEVELS)} cross-up levels: {CROSS_UP_LEVELS}")
    print(f"Testing {len(RR_RATIOS)} R:R ratios: {RR_RATIOS}")
    print(f"Testing {len(ENTRY_TYPES)} entry types: {ENTRY_TYPES}")
    print(f"SL Lookback: {SL_LOOKBACK} bars (fixed)")
    print()

    total_combinations = len(RSI_PERIODS) * len(CROSS_UP_LEVELS) * len(RR_RATIOS) * len(ENTRY_TYPES)
    print(f"📊 Total combinations: {total_combinations}")
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
            for cross_level in CROSS_UP_LEVELS:
                for rr_ratio in RR_RATIOS:
                    combo_count += 1

                    variant_name = f"RSI{rsi_period}_L{cross_level}_RR{rr_ratio}_SL{SL_LOOKBACK}_{entry_type}"

                    result = backtest_entry_signal(
                        combined_df, rsi_period, cross_level,
                        SL_LOOKBACK, rr_ratio, entry_type
                    )

                    result["rsi_period"] = rsi_period
                    result["cross_level"] = cross_level
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

    # Save all results
    all_results_df = pd.DataFrame(all_results)
    output_file = RESULTS_DIR / "dax_entry_signals_results.csv"
    all_results_df.to_csv(output_file, index=False)

    # Analyze results by entry type
    print("=" * 80)
    print("📊 RESULTS BY ENTRY SIGNAL TYPE")
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
                print(f"📋 TOP 5 VARIANTS:")
                print(f"   {'Variant':<50} {'PnL':>10} {'WR%':>6} {'Trades':>7} {'Expect':>7}")
                print(f"   {'-'*50} {'-'*10} {'-'*6} {'-'*7} {'-'*7}")
                for idx, row in profitable.head(5).iterrows():
                    print(f"   {row['variant']:<50} {row['total_pnl_pts']:+10.2f} {row['win_rate_pct']:6.1f} {int(row['trades']):7d} {row['expectancy']:+7.2f}")
                print()
        else:
            print(f"❌ No profitable variants found for {entry_label}")
            print()

    # Head-to-head comparison
    print("\n" + "=" * 80)
    print("🎯 HEAD-TO-HEAD: BEST OF EACH ENTRY TYPE")
    print("=" * 80)
    print()

    best_by_entry = {}
    for entry_type in ENTRY_TYPES:
        subset = all_results_df[all_results_df["entry_type"] == entry_type]
        profitable = subset[subset["total_pnl_pts"] > 0]

        if len(profitable) > 0:
            best = profitable.sort_values("total_pnl_pts", ascending=False).iloc[0]
            entry_label = entry_type.replace("_", " ").title()
            best_by_entry[entry_label] = best

    if best_by_entry:
        # Sort by profit
        sorted_best = sorted(best_by_entry.items(), key=lambda x: x[1]["total_pnl_pts"], reverse=True)

        print(f"{'Entry Type':<20} {'PnL (pts)':>12} {'Win Rate':>10} {'Trades':>8} {'PF':>6} {'Expect':>8}")
        print(f"{'-'*20} {'-'*12} {'-'*10} {'-'*8} {'-'*6} {'-'*8}")

        for entry_label, result in sorted_best:
            print(f"{entry_label:<20} {result['total_pnl_pts']:+12.2f} {result['win_rate_pct']:9.1f}% {int(result['trades']):8d} {result['profit_factor']:6.2f} {result['expectancy']:+8.2f}")

        print()

        # Winner analysis
        winner_label, winner = sorted_best[0]
        baseline_label, baseline = next((item for item in sorted_best if item[0] == "Standard"), (None, None))

        print(f"🏆 WINNER: {winner_label}")
        print(f"   Configuration: {winner['variant']}")
        print(f"   Total Profit: {winner['total_pnl_pts']:+,.2f} points over 3 years")
        print(f"   Win Rate: {winner['win_rate_pct']:.1f}%")
        print(f"   Total Trades: {int(winner['trades'])}")
        print(f"   Expectancy: {winner['expectancy']:+.2f} pts per trade")
        print()

        if baseline is not None:
            pnl_improvement = winner['total_pnl_pts'] - baseline['total_pnl_pts']
            wr_improvement = winner['win_rate_pct'] - baseline['win_rate_pct']
            trades_change = int(winner['trades']) - int(baseline['trades'])
            expect_improvement = winner['expectancy'] - baseline['expectancy']

            print(f"📈 IMPROVEMENT vs BASELINE (Standard Entry):")
            print(f"   PnL: {pnl_improvement:+.2f} points ({pnl_improvement/baseline['total_pnl_pts']*100:+.1f}%)")
            print(f"   Win Rate: {wr_improvement:+.1f} percentage points")
            print(f"   Trades: {trades_change:+d} ({trades_change/baseline['trades']*100:+.1f}%)")
            print(f"   Expectancy: {expect_improvement:+.2f} pts per trade ({expect_improvement/baseline['expectancy']*100:+.1f}%)")
            print()

            if winner_label != "Standard":
                print(f"✅ {winner_label.upper()} ENTRY WORKS! Outperforms standard entry")
            else:
                print(f"⚠️  Standard entry is still the best performer")

        print()

    print(f"💾 Full results saved to: {output_file}")
    print()
    print("=" * 80)
    print("✅ OPTIMIZATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
