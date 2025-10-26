"""
DAX Moving Average Trend Filter Optimizer

Tests RSI(2) strategy with trend filters:
- Only take RSI cross-up signals when price is ABOVE the moving average
- Logic: "Only buy dips in an uptrend"
- Tests MA(20), MA(50), and MA(200) to find optimal filter

Compares performance against baseline (no filter).
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
RESULTS_DIR = Path("results/dax_ma_filter")
TIMEZONE = pytz.timezone("Europe/Berlin")

# EU Session Configuration
SESSION_START = time(8, 0)   # 08:00 CET
SESSION_END = time(22, 0)    # 22:00 CET

# Parameter grid to test
RSI_PERIODS = [2, 3, 4, 5]
CROSS_UP_LEVELS = [5, 10, 15, 20]
RR_RATIOS = [3.0, 4.0, 5.0]
SL_LOOKBACK = 2  # Fixed at 2 (proven winner from previous tests)
MA_PERIODS = [20, 50, 200, None]  # None = no filter (baseline)


def rsi_cross_up_custom(series, level, period):
    """Custom RSI cross-up detection."""
    rsi_series = rsi(series, period=period)
    prev_below = rsi_series.shift(1) <= level
    curr_above = rsi_series > level
    return prev_below & curr_above


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


def simple_moving_average(series, period):
    """Calculate simple moving average."""
    return series.rolling(window=period).mean()


def backtest_ma_filter(df, rsi_period, cross_level, sl_lookback, rr_ratio, ma_period=None):
    """
    Backtest RSI strategy with optional MA trend filter.

    Args:
        df: DataFrame with OHLC data
        rsi_period: RSI calculation period
        cross_level: RSI cross-up level
        sl_lookback: Number of bars to look back for stop loss
        rr_ratio: Risk:Reward ratio
        ma_period: Moving average period (None = no filter)
    """
    df = df.copy()
    close, high, low = df["Close"], df["High"], df["Low"]

    # Calculate RSI
    df["RSI"] = rsi(close, period=rsi_period)
    df["signal"] = rsi_cross_up_custom(close, level=cross_level, period=rsi_period)

    # Calculate MA if filter is enabled
    if ma_period is not None:
        df["MA"] = simple_moving_average(close, period=ma_period)
        # Only valid signals are when price > MA
        df["signal"] = df["signal"] & (close > df["MA"])

    trades = []
    in_trade = False
    entry_price = sl = tp = entry_time = None

    # Start index after warmup period
    start_idx = max(rsi_period, sl_lookback)
    if ma_period is not None:
        start_idx = max(start_idx, ma_period)

    for i in range(start_idx, len(df)):
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
            "avg_loss_pts": 0.0, "max_dd_pts": 0.0
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
        "max_dd_pts": round(max_dd, 2)
    }


def main():
    print("=" * 80)
    print("📊 DAX MOVING AVERAGE TREND FILTER OPTIMIZER")
    print("=" * 80)
    print()
    print("Strategy: RSI cross-up + MA trend filter")
    print("Logic: Only buy dips when price is ABOVE moving average (uptrend)")
    print()
    print(f"Session Hours: {SESSION_START.strftime('%H:%M')} - {SESSION_END.strftime('%H:%M')} Europe/Berlin")
    print(f"Entry allowed: Only during session hours")
    print(f"Exit allowed: Anytime (24/7)")
    print()
    print(f"Testing {len(RSI_PERIODS)} RSI periods: {RSI_PERIODS}")
    print(f"Testing {len(CROSS_UP_LEVELS)} cross-up levels: {CROSS_UP_LEVELS}")
    print(f"Testing {len(RR_RATIOS)} R:R ratios: {RR_RATIOS}")
    print(f"Testing {len(MA_PERIODS)} MA filters: {[f'MA({p})' if p else 'No Filter' for p in MA_PERIODS]}")
    print(f"SL Lookback: {SL_LOOKBACK} bars (fixed)")
    print()

    total_combinations = len(RSI_PERIODS) * len(CROSS_UP_LEVELS) * len(RR_RATIOS) * len(MA_PERIODS)
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

    for ma_period in MA_PERIODS:
        ma_label = f"MA({ma_period})" if ma_period else "No Filter"
        print(f"\n{'='*80}")
        print(f"Testing {ma_label}...")
        print(f"{'='*80}\n")

        for rsi_period in RSI_PERIODS:
            for cross_level in CROSS_UP_LEVELS:
                for rr_ratio in RR_RATIOS:
                    combo_count += 1

                    ma_str = f"MA{ma_period}" if ma_period else "NoFilter"
                    variant_name = f"RSI{rsi_period}_L{cross_level}_RR{rr_ratio}_SL{SL_LOOKBACK}_{ma_str}"

                    result = backtest_ma_filter(
                        combined_df, rsi_period, cross_level,
                        SL_LOOKBACK, rr_ratio, ma_period
                    )

                    result["rsi_period"] = rsi_period
                    result["cross_level"] = cross_level
                    result["rr_ratio"] = rr_ratio
                    result["sl_lookback"] = SL_LOOKBACK
                    result["ma_period"] = ma_period if ma_period else 0
                    result["ma_label"] = ma_label
                    result["variant"] = variant_name

                    all_results.append(result)

                    if combo_count % 10 == 0:
                        print(f"   Tested {combo_count}/{total_combinations} combinations...")

    print(f"\n✅ Completed all {combo_count} combinations")
    print()

    # Save all results
    all_results_df = pd.DataFrame(all_results)
    output_file = RESULTS_DIR / "dax_ma_filter_results.csv"
    all_results_df.to_csv(output_file, index=False)

    # Analyze results by MA period
    print("=" * 80)
    print("📊 RESULTS BY MA FILTER TYPE")
    print("=" * 80)
    print()

    for ma_period in MA_PERIODS:
        ma_label = f"MA({ma_period})" if ma_period else "No Filter (Baseline)"

        subset = all_results_df[all_results_df["ma_period"] == (ma_period if ma_period else 0)]
        profitable = subset[subset["total_pnl_pts"] > 0].copy()

        print(f"\n{'='*80}")
        print(f"🔍 {ma_label}")
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
            print(f"   Avg Win: {best['avg_win_pts']:+.2f} pts")
            print(f"   Avg Loss: {best['avg_loss_pts']:.2f} pts")
            print(f"   Max Drawdown: {best['max_dd_pts']:.2f} pts")
            print(f"   Avg Bars Held: {best['avg_bars_held']:.1f}")
            print()

            if len(profitable) > 1:
                print(f"📋 TOP 5 VARIANTS:")
                print(f"   {'Variant':<40} {'PnL':>10} {'WR%':>6} {'Trades':>7} {'PF':>6}")
                print(f"   {'-'*40} {'-'*10} {'-'*6} {'-'*7} {'-'*6}")
                for idx, row in profitable.head(5).iterrows():
                    print(f"   {row['variant']:<40} {row['total_pnl_pts']:+10.2f} {row['win_rate_pct']:6.1f} {int(row['trades']):7d} {row['profit_factor']:6.2f}")
                print()
        else:
            print(f"❌ No profitable variants found for {ma_label}")
            print()

    # Head-to-head comparison
    print("\n" + "=" * 80)
    print("🎯 HEAD-TO-HEAD: BEST OF EACH MA FILTER")
    print("=" * 80)
    print()

    best_by_ma = {}
    for ma_period in MA_PERIODS:
        subset = all_results_df[all_results_df["ma_period"] == (ma_period if ma_period else 0)]
        profitable = subset[subset["total_pnl_pts"] > 0]

        if len(profitable) > 0:
            best = profitable.sort_values("total_pnl_pts", ascending=False).iloc[0]
            ma_label = f"MA({ma_period})" if ma_period else "No Filter"
            best_by_ma[ma_label] = best

    if best_by_ma:
        # Sort by profit
        sorted_best = sorted(best_by_ma.items(), key=lambda x: x[1]["total_pnl_pts"], reverse=True)

        print(f"{'Filter Type':<15} {'PnL (pts)':>12} {'Win Rate':>10} {'Trades':>8} {'PF':>6} {'Max DD':>10}")
        print(f"{'-'*15} {'-'*12} {'-'*10} {'-'*8} {'-'*6} {'-'*10}")

        for ma_label, result in sorted_best:
            print(f"{ma_label:<15} {result['total_pnl_pts']:+12.2f} {result['win_rate_pct']:9.1f}% {int(result['trades']):8d} {result['profit_factor']:6.2f} {result['max_dd_pts']:10.2f}")

        print()

        # Winner analysis
        winner_label, winner = sorted_best[0]
        baseline_label, baseline = next((item for item in sorted_best if item[0] == "No Filter"), (None, None))

        print(f"🏆 WINNER: {winner_label}")
        print(f"   Configuration: {winner['variant']}")
        print(f"   Total Profit: {winner['total_pnl_pts']:+,.2f} points over 3 years")
        print(f"   Win Rate: {winner['win_rate_pct']:.1f}%")
        print(f"   Total Trades: {int(winner['trades'])}")
        print()

        if baseline is not None:
            pnl_improvement = winner['total_pnl_pts'] - baseline['total_pnl_pts']
            wr_improvement = winner['win_rate_pct'] - baseline['win_rate_pct']
            trades_change = int(winner['trades']) - int(baseline['trades'])

            print(f"📈 IMPROVEMENT vs BASELINE (No Filter):")
            print(f"   PnL: {pnl_improvement:+.2f} points ({pnl_improvement/baseline['total_pnl_pts']*100:+.1f}%)")
            print(f"   Win Rate: {wr_improvement:+.1f} percentage points")
            print(f"   Trades: {trades_change:+d} ({trades_change/baseline['trades']*100:+.1f}%)")
            print()

            if winner_label != "No Filter":
                print(f"✅ MA FILTER WORKS! {winner_label} outperforms baseline")
            else:
                print(f"⚠️  Baseline (no filter) is still the best performer")

        print()

    print(f"💾 Full results saved to: {output_file}")
    print()
    print("=" * 80)
    print("✅ OPTIMIZATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
