#!/usr/bin/env python3
"""
Simple RSI(2) Reversal Backtest - LONG ONLY
Tests on DAX monthly data with monthly P&L breakdown.

Strategy:
- Entry: RSI(2) < 5 = LONG (buy oversold)
- Exit: RSI(2) returns to 50 (mean reversion)
- Stop Loss: 2 × last candle range (safety only)
"""

from pathlib import Path
import pandas as pd


def calculate_rsi(prices, period=2):
    """Calculate RSI indicator."""
    deltas = prices.diff()
    gain = deltas.where(deltas > 0, 0.0)
    loss = -deltas.where(deltas < 0, 0.0)

    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi


def backtest_month(df):
    """
    Backtest RSI(2) strategy on one month of data.

    Returns: list of trades
    """
    df = df.copy()

    # Calculate RSI(2)
    df['RSI'] = calculate_rsi(df['Close'], period=2)
    df['RSI_prev'] = df['RSI'].shift(1)

    # Calculate candle range
    df['Range'] = df['High'] - df['Low']
    df['Range_prev'] = df['Range'].shift(1)

    trades = []
    in_position = False
    position_type = None
    entry_price = None
    entry_idx = None
    stop_loss = None
    take_profit = None

    for i in range(3, len(df)):  # Start at 3 to have enough data for RSI
        row = df.iloc[i]

        # Exit conditions if in position
        if in_position:
            exit_price = None
            exit_reason = None

            # LONG exit logic
            if position_type == "LONG":
                # Primary exit: RSI reaches 50 (mean reversion)
                if row['RSI'] >= 50:
                    exit_price = row['Close']
                    exit_reason = "RSI_50"
                # Safety: Stop loss only
                elif row['Low'] <= stop_loss:
                    exit_price = stop_loss
                    exit_reason = "SL"

            # Record trade if exited
            if exit_price:
                pnl_pts = exit_price - entry_price  # LONG only

                trades.append({
                    'entry_time': df.iloc[entry_idx]['Datetime'],
                    'exit_time': row['Datetime'],
                    'type': position_type,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'sl': stop_loss,
                    'tp': take_profit,
                    'pnl_pts': pnl_pts,
                    'exit_reason': exit_reason
                })

                in_position = False
                position_type = None

        # Entry signals if not in position
        if not in_position:
            # LONG ONLY: RSI(2) < 5
            if row['RSI'] < 5:
                entry_price = row['Close']
                entry_idx = i
                position_type = "LONG"

                # SL: 2 × last candle range (safety only)
                sl_distance = 2 * df.iloc[i-1]['Range']
                stop_loss = entry_price - sl_distance
                take_profit = None  # Exit on RSI=50, not TP

                in_position = True

    return trades


def main():
    print("=" * 70)
    print("RSI(2) REVERSAL BACKTEST")
    print("=" * 70)
    print()

    print("Strategy: LONG ONLY")
    print("  Entry: RSI(2) < 5 (buy extreme oversold)")
    print("  Exit: RSI(2) returns to 50 (mean reversion)")
    print("  Stop Loss: 2 × last candle range (safety net only)")
    print()

    # Load all monthly files
    data_dir = Path("data/dax_monthly")
    csv_files = sorted(data_dir.glob("*.csv"))

    if not csv_files:
        print(f"❌ No CSV files found in {data_dir}")
        return

    print(f"📂 Found {len(csv_files)} monthly files")
    print()

    # Results storage
    monthly_results = []
    all_trades = []

    # Process each month
    for csv_file in csv_files:
        month_name = csv_file.stem  # e.g., "dax_2024-01"

        print(f"Testing {month_name}...", end=" ")

        # Load data
        df = pd.read_csv(csv_file)
        df['Datetime'] = pd.to_datetime(df['Datetime'])

        # Backtest
        trades = backtest_month(df)

        if not trades:
            print("No trades")
            continue

        # Calculate P&L
        trades_df = pd.DataFrame(trades)
        total_pnl = trades_df['pnl_pts'].sum()
        wins = len(trades_df[trades_df['pnl_pts'] > 0])
        losses = len(trades_df[trades_df['pnl_pts'] <= 0])
        win_rate = wins / len(trades_df) * 100 if len(trades_df) > 0 else 0

        print(f"{len(trades)} trades | WR: {win_rate:.1f}% | P&L: {total_pnl:+.2f} pts")

        # Store results
        monthly_results.append({
            'month': month_name,
            'trades': len(trades),
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'pnl_pts': total_pnl
        })

        # Add month identifier to trades
        trades_df['month'] = month_name
        all_trades.append(trades_df)

    print()

    if not monthly_results:
        print("❌ No trades generated")
        return

    # Summary
    print("=" * 70)
    print("MONTHLY P&L STATEMENT (Points)")
    print("=" * 70)
    print()

    summary_df = pd.DataFrame(monthly_results)

    # Display monthly breakdown
    for _, row in summary_df.iterrows():
        status = "✅" if row['pnl_pts'] > 0 else "❌"
        print(f"{row['month']:20s} | {row['trades']:3d} trades | "
              f"WR: {row['win_rate']:5.1f}% | P&L: {row['pnl_pts']:+8.2f} pts {status}")

    print()
    print("=" * 70)
    print("TOTAL SUMMARY")
    print("=" * 70)
    print()

    total_trades = summary_df['trades'].sum()
    total_wins = summary_df['wins'].sum()
    total_losses = summary_df['losses'].sum()
    total_pnl = summary_df['pnl_pts'].sum()
    overall_wr = total_wins / total_trades * 100 if total_trades > 0 else 0

    profitable_months = len(summary_df[summary_df['pnl_pts'] > 0])
    total_months = len(summary_df)
    consistency = profitable_months / total_months * 100 if total_months > 0 else 0

    print(f"Total Months Tested: {total_months}")
    print(f"Total Trades: {total_trades}")
    print(f"Wins: {total_wins} | Losses: {total_losses}")
    print(f"Overall Win Rate: {overall_wr:.1f}%")
    print(f"Total P&L: {total_pnl:+.2f} points")
    print(f"Profitable Months: {profitable_months}/{total_months} ({consistency:.1f}%)")
    print()

    # Save results
    output_dir = Path("results/rsi2_backtest")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save monthly summary
    summary_file = output_dir / "monthly_pnl.csv"
    summary_df.to_csv(summary_file, index=False)
    print(f"💾 Monthly P&L saved: {summary_file}")

    # Save all trades
    if all_trades:
        all_trades_df = pd.concat(all_trades, ignore_index=True)
        trades_file = output_dir / "all_trades.csv"
        all_trades_df.to_csv(trades_file, index=False)
        print(f"💾 All trades saved: {trades_file}")

    print()
    print("=" * 70)
    print("✅ BACKTEST COMPLETE")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
