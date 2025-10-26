"""
Optimize RSI strategy parameters for DAX.
Tests multiple R:R ratios and Gap×N multipliers on monthly data.
Finds the best performing variant for each month and overall.
"""
import pandas as pd
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from strategy_core import rsi, rsi_cross_up, compute_sl_tp_fixed_rr, compute_tp_gapN

# Configuration
DATA_DIR = Path("data/dax_monthly")
RESULTS_DIR = Path("results/dax_optimization")

# Test these variations (same as backtest_config.yaml)
FIXED_RR_LIST = [1.0, 1.5, 2.0, 3.0]
GAPN_LIST = [3, 4, 5, 6]

# EU Session Filter (set to True to only trade during EU hours)
USE_EU_SESSION = True  # Toggle this: True = filter by hours, False = trade 24/7
EU_SESSION_START = "08:00"  # Frankfurt/XETRA open (CET/CEST)
EU_SESSION_END = "22:00"    # DAX futures close (CET/CEST)

def session_filter(df: pd.DataFrame, start: str, end: str):
    """Filter dataframe to only include EU trading hours."""
    # Filter weekdays only (Mon-Fri)
    df = df[df.index.dayofweek < 5]
    # Filter by time range
    return df.between_time(start, end)

def backtest_variant(df: pd.DataFrame, mode: str, param: float):
    """Run backtest with specific mode and parameter."""
    df = df.copy()

    # Apply session filter if enabled
    if USE_EU_SESSION:
        df = session_filter(df, EU_SESSION_START, EU_SESSION_END)
        if len(df) == 0:
            return {
                "trades": 0, "wins": 0, "losses": 0,
                "win_rate_pct": 0.0, "total_pnl_pts": 0.0, "profit_factor": 0.0
            }

    close, high, low = df["Close"], df["High"], df["Low"]

    # Calculate RSI
    df["RSI2"] = rsi(close, period=2)
    df["rsi_cross_up_10"] = rsi_cross_up(close, level=10, period=2)

    trades = []
    in_trade = False
    entry_price = sl = tp = entry_time = None

    for i in range(2, len(df)):
        ts = df.index[i]

        if not in_trade:
            # Check for entry signal
            if bool(df["rsi_cross_up_10"].iat[i]):
                if trades and (df.index[i] <= trades[-1]["exit_time"]):
                    continue

                # Calculate SL/TP based on mode
                if mode == "fixed":
                    pack = compute_sl_tp_fixed_rr(df, i, float(param))
                elif mode == "gapN":
                    pack = compute_tp_gapN(df, i, float(param))
                else:
                    continue

                if not pack:
                    continue

                entry_price, sl, tp = pack["entry"], pack["sl"], pack["tp"]
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
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "total_pnl_pts": 0.0,
            "profit_factor": 0.0
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
        "profit_factor": round(pf, 2)
    }

def main():
    print("=" * 80)
    print("📊 DAX STRATEGY OPTIMIZATION - Testing All Parameter Variations")
    print("=" * 80)
    print()
    print(f"⏰ EU Session Filter: {'ENABLED' if USE_EU_SESSION else 'DISABLED'}")
    if USE_EU_SESSION:
        print(f"   Trading Hours: {EU_SESSION_START} - {EU_SESSION_END} (CET/CEST, Mon-Fri only)")
    else:
        print(f"   Trading Hours: 24/7 (All hours)")
    print()

    # Create results directory
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Get all monthly CSV files
    csv_files = sorted(DATA_DIR.glob("dax_*.csv"))

    if not csv_files:
        print(f"❌ No CSV files found in {DATA_DIR}")
        return

    print(f"📁 Found {len(csv_files)} monthly files")
    print(f"🔬 Testing {len(FIXED_RR_LIST)} R:R ratios: {FIXED_RR_LIST}")
    print(f"🔬 Testing {len(GAPN_LIST)} Gap×N values: {GAPN_LIST}")
    print(f"📊 Total combinations: {len(FIXED_RR_LIST) + len(GAPN_LIST)}")
    print()

    all_results = []

    # Test each month
    for csv_file in csv_files:
        month_name = csv_file.stem.replace("dax_", "")

        # Load data
        df = pd.read_csv(csv_file)
        df["Datetime"] = pd.to_datetime(df["Datetime"])
        df = df.set_index("Datetime")

        print(f"📅 {month_name} ({len(df)} bars)")

        # Test Fixed R:R variations
        for rr in FIXED_RR_LIST:
            result = backtest_variant(df, "fixed", rr)
            result["month"] = month_name
            result["mode"] = "fixed"
            result["param"] = rr
            result["variant"] = f"R:R_{rr}"
            all_results.append(result)

            status = "✅" if result["total_pnl_pts"] > 0 else "❌"
            print(f"  {status} R:R {rr}: {result['trades']} trades, "
                  f"Win: {result['win_rate_pct']}%, "
                  f"PnL: {result['total_pnl_pts']:+.2f} pts, "
                  f"PF: {result['profit_factor']}")

        # Test Gap×N variations
        for N in GAPN_LIST:
            result = backtest_variant(df, "gapN", N)
            result["month"] = month_name
            result["mode"] = "gapN"
            result["param"] = N
            result["variant"] = f"Gap×{N}"
            all_results.append(result)

            status = "✅" if result["total_pnl_pts"] > 0 else "❌"
            print(f"  {status} Gap×{N}: {result['trades']} trades, "
                  f"Win: {result['win_rate_pct']}%, "
                  f"PnL: {result['total_pnl_pts']:+.2f} pts, "
                  f"PF: {result['profit_factor']}")

        print()

    # Save all results
    results_df = pd.DataFrame(all_results)
    output_file = RESULTS_DIR / "dax_all_variations.csv"
    results_df.to_csv(output_file, index=False)

    # Analyze results
    print("=" * 80)
    print("📊 OPTIMIZATION RESULTS")
    print("=" * 80)
    print()

    # Best variant overall
    print("🏆 BEST PERFORMING VARIANTS (Overall):")
    print("-" * 80)

    variant_totals = results_df.groupby("variant").agg({
        "total_pnl_pts": "sum",
        "trades": "sum",
        "wins": "sum",
        "losses": "sum"
    }).reset_index()

    variant_totals["win_rate_pct"] = round(100 * variant_totals["wins"] / variant_totals["trades"], 1)
    variant_totals = variant_totals.sort_values("total_pnl_pts", ascending=False)

    for idx, row in variant_totals.iterrows():
        status = "✅" if row["total_pnl_pts"] > 0 else "❌"
        print(f"{status} {row['variant']:10s}: Total PnL = {row['total_pnl_pts']:+10.2f} pts | "
              f"Trades: {row['trades']:3d} | Win Rate: {row['win_rate_pct']:5.1f}%")

    print()

    # Best variant per month
    print("📅 BEST VARIANT PER MONTH:")
    print("-" * 80)

    best_per_month = results_df.loc[results_df.groupby("month")["total_pnl_pts"].idxmax()]
    best_per_month = best_per_month.sort_values("month")

    for idx, row in best_per_month.iterrows():
        status = "✅" if row["total_pnl_pts"] > 0 else "❌"
        print(f"{status} {row['month']}: {row['variant']:10s} | "
              f"PnL: {row['total_pnl_pts']:+8.2f} pts | "
              f"Win Rate: {row['win_rate_pct']:5.1f}%")

    print()

    # Summary statistics
    best_variant = variant_totals.iloc[0]
    print("🎯 RECOMMENDATION:")
    print("-" * 80)
    print(f"Best Overall Strategy: {best_variant['variant']}")
    print(f"Total PnL: {best_variant['total_pnl_pts']:+.2f} points")
    print(f"Total Trades: {int(best_variant['trades'])}")
    print(f"Win Rate: {best_variant['win_rate_pct']:.1f}%")
    print()

    profitable_months = len(best_per_month[best_per_month["total_pnl_pts"] > 0])
    print(f"Profitable Months: {profitable_months}/{len(csv_files)} ({profitable_months/len(csv_files)*100:.1f}%)")
    print()

    print(f"💾 Detailed results saved to: {output_file}")
    print()

if __name__ == "__main__":
    main()
