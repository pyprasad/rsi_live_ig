"""
Run RSI strategy backtest on monthly DAX CSV files.
Generates monthly profitability report.
"""
import pandas as pd
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from strategy_core import rsi, rsi_cross_up, compute_sl_tp_fixed_rr

# Configuration
DATA_DIR = Path("data/dax_monthly")
RESULTS_DIR = Path("results/dax_monthly")
RR = 1.5  # Risk:Reward ratio (same as live config)
TIMEFRAME = "30 minutes"  # For display only

def backtest_month(df: pd.DataFrame, month_name: str):
    """Run backtest on a single month's data."""
    df = df.copy()
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
                # Skip if too close to previous exit
                if trades and (df.index[i] <= trades[-1]["exit_time"]):
                    continue

                # Calculate SL/TP
                pack = compute_sl_tp_fixed_rr(df, i, RR)
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
            "month": month_name,
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "total_pnl_pts": 0.0,
            "avg_win_pts": 0.0,
            "avg_loss_pts": 0.0,
            "profit_factor": 0.0
        }

    trades_df = pd.DataFrame(trades)
    wins = trades_df[trades_df["reason"] == "TP"]
    losses = trades_df[trades_df["reason"] == "SL"]

    total_win_pts = wins["pnl_pts"].sum() if not wins.empty else 0.0
    total_loss_pts = abs(losses["pnl_pts"].sum()) if not losses.empty else 0.0

    pf = (total_win_pts / total_loss_pts) if total_loss_pts > 0 else (999.0 if total_win_pts > 0 else 0.0)

    return {
        "month": month_name,
        "trades": len(trades_df),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(100 * len(wins) / len(trades_df), 1),
        "total_pnl_pts": round(trades_df["pnl_pts"].sum(), 2),
        "avg_win_pts": round(wins["pnl_pts"].mean(), 2) if not wins.empty else 0.0,
        "avg_loss_pts": round(losses["pnl_pts"].mean(), 2) if not losses.empty else 0.0,
        "profit_factor": round(pf, 2)
    }

def main():
    print(f"📊 Running DAX Monthly Backtest (RSI Cross-Up Strategy)")
    print(f"   Risk:Reward = {RR}:1")
    print(f"   Timeframe = {TIMEFRAME}")
    print()

    # Create results directory
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Get all monthly CSV files
    csv_files = sorted(DATA_DIR.glob("dax_*.csv"))

    if not csv_files:
        print(f"❌ No CSV files found in {DATA_DIR}")
        print(f"   Please run convert_dax_to_csv.py first!")
        return

    print(f"📁 Found {len(csv_files)} monthly files")
    print()

    monthly_results = []

    for csv_file in csv_files:
        month_name = csv_file.stem.replace("dax_", "")  # e.g., "2023-01"

        # Load data
        df = pd.read_csv(csv_file)
        df["Datetime"] = pd.to_datetime(df["Datetime"])
        df = df.set_index("Datetime")

        # Run backtest
        result = backtest_month(df, month_name)
        monthly_results.append(result)

        # Print result
        status = "✅" if result["total_pnl_pts"] > 0 else "❌"
        print(f"{status} {month_name}: {result['trades']} trades, "
              f"Win Rate: {result['win_rate_pct']}%, "
              f"PnL: {result['total_pnl_pts']:+.2f} pts, "
              f"PF: {result['profit_factor']}")

    # Save results
    results_df = pd.DataFrame(monthly_results)
    output_file = RESULTS_DIR / "dax_monthly_results.csv"
    results_df.to_csv(output_file, index=False)

    # Print summary
    print()
    print("=" * 70)
    print("📊 SUMMARY")
    print("=" * 70)

    total_trades = results_df["trades"].sum()
    total_wins = results_df["wins"].sum()
    total_losses = results_df["losses"].sum()
    total_pnl = results_df["total_pnl_pts"].sum()

    profitable_months = len(results_df[results_df["total_pnl_pts"] > 0])
    losing_months = len(results_df[results_df["total_pnl_pts"] < 0])

    overall_win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0

    print(f"Total Months: {len(results_df)}")
    print(f"Profitable Months: {profitable_months} ({profitable_months/len(results_df)*100:.1f}%)")
    print(f"Losing Months: {losing_months} ({losing_months/len(results_df)*100:.1f}%)")
    print()
    print(f"Total Trades: {total_trades}")
    print(f"Total Wins: {total_wins}")
    print(f"Total Losses: {total_losses}")
    print(f"Overall Win Rate: {overall_win_rate:.1f}%")
    print()
    print(f"Total PnL: {total_pnl:+.2f} points")
    print(f"Best Month: {results_df.loc[results_df['total_pnl_pts'].idxmax(), 'month']} "
          f"({results_df['total_pnl_pts'].max():+.2f} pts)")
    print(f"Worst Month: {results_df.loc[results_df['total_pnl_pts'].idxmin(), 'month']} "
          f"({results_df['total_pnl_pts'].min():+.2f} pts)")
    print()
    print(f"💾 Results saved to: {output_file}")

if __name__ == "__main__":
    main()
