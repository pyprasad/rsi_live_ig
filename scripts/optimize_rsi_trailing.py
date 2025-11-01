#!/usr/bin/env python3
"""
RSI Trailing Exit Optimizer
Tests RSI(2) reversal strategy with multiple exit levels and stop losses.
Uses multiprocessing for speed.
"""

from pathlib import Path
import pandas as pd
import multiprocessing as mp
import warnings
warnings.filterwarnings('ignore')


# ==================== CONFIGURATION ====================

CONFIG = {
    # Strategy parameters to test
    'entry_rsi_long': 5,         # Enter LONG when RSI < 5
    'entry_rsi_short': 95,       # Enter SHORT when RSI > 95
    'exit_rsi_levels': [10, 15, 20, 25, 30, 40, 50],  # Exit thresholds to test
    'stop_loss_points': [10, 20, 30, 50],              # Stop loss levels to test

    # Trade modes to test
    'modes': ['LONG_ONLY', 'SHORT_ONLY', 'BOTH'],

    # Costs
    'slippage_pips': 1,          # Slippage on entry/exit

    # Spread by time (hour_start, hour_end, spread_points)
    'spread_schedule': [
        (8.0, 17.5, 1.5),        # Main hours: 08:00-17:30, 1.5 points
        (17.5, 22.0, 3.0),       # Extended: 17:30-22:00, 3 points
        (22.0, 8.0, 6.0),        # Night: 22:00-08:00, 6 points (wraps midnight)
    ],
}

DATA_DIR = Path("data/dax_monthly")
OUTPUT_DIR = Path("results/rsi2_optimizer")


# ==================== HELPER FUNCTIONS ====================

def calculate_rsi(prices, period=2):
    """Calculate RSI."""
    deltas = prices.diff()
    gain = deltas.where(deltas > 0, 0.0)
    loss = -deltas.where(deltas < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def get_spread_for_time(dt):
    """Get spread cost based on time of day."""
    hour = dt.hour + dt.minute / 60.0

    for start, end, spread in CONFIG['spread_schedule']:
        if start < end:  # Normal range (e.g., 8-17.5)
            if start <= hour < end:
                return spread
        else:  # Wraps midnight (e.g., 22-8)
            if hour >= start or hour < end:
                return spread

    return 3.0  # Default spread


# ==================== BACKTEST FUNCTION ====================

def backtest_strategy(df, mode, exit_rsi, stop_loss_pts):
    """
    Backtest one strategy combination.
    """
    df = df.copy()
    df['RSI'] = calculate_rsi(df['Close'], period=2)

    trades = []
    in_position = False
    position_type = None
    entry_price = None
    entry_time = None
    stop_loss = None
    slippage = CONFIG['slippage_pips']

    for i in range(3, len(df)):
        row = df.iloc[i]

        # Exit logic
        if in_position:
            exit_price = None
            exit_reason = None

            if position_type == "LONG":
                # Exit: RSI reaches target or SL hit
                if row['RSI'] >= exit_rsi:
                    exit_price = row['Close'] - slippage
                    exit_reason = f"RSI_{exit_rsi}"
                elif row['Low'] <= stop_loss:
                    exit_price = stop_loss - slippage
                    exit_reason = "SL"

            elif position_type == "SHORT":
                # Exit: RSI reaches target or SL hit
                if row['RSI'] <= exit_rsi:
                    exit_price = row['Close'] + slippage
                    exit_reason = f"RSI_{exit_rsi}"
                elif row['High'] >= stop_loss:
                    exit_price = stop_loss + slippage
                    exit_reason = "SL"

            # Record trade
            if exit_price:
                # Calculate raw P&L
                if position_type == "LONG":
                    raw_pnl = exit_price - entry_price
                else:
                    raw_pnl = entry_price - exit_price

                # Calculate costs
                # Spread is paid ONCE when entering (difference between bid/ask)
                spread_cost = get_spread_for_time(entry_time)

                # Slippage on entry and exit
                slippage_cost = 2 * slippage

                # Net P&L
                net_pnl = raw_pnl - spread_cost - slippage_cost

                trades.append({
                    'entry_time': entry_time,
                    'exit_time': row['Datetime'],
                    'type': position_type,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'raw_pnl': raw_pnl,
                    'spread_cost': spread_cost,
                    'slippage_cost': slippage_cost,
                    'net_pnl': net_pnl,
                    'exit_reason': exit_reason,
                    'entry_hour': entry_time.hour + entry_time.minute/60.0,
                })

                in_position = False

        # Entry logic
        if not in_position:
            # LONG entry
            if mode in ['LONG_ONLY', 'BOTH'] and row['RSI'] < CONFIG['entry_rsi_long']:
                entry_price = row['Close'] + slippage
                entry_time = row['Datetime']
                position_type = "LONG"
                stop_loss = entry_price - stop_loss_pts
                in_position = True

            # SHORT entry
            elif mode in ['SHORT_ONLY', 'BOTH'] and row['RSI'] > CONFIG['entry_rsi_short']:
                entry_price = row['Close'] - slippage
                entry_time = row['Datetime']
                position_type = "SHORT"
                stop_loss = entry_price + stop_loss_pts
                in_position = True

    return trades


# ==================== WORKER FUNCTION ====================

def process_strategy(args):
    """Process one strategy combination across all months."""
    mode, exit_rsi, stop_loss_pts = args

    strategy_name = f"{mode}_RSI{exit_rsi}_SL{stop_loss_pts}"

    # Load all monthly files
    csv_files = sorted(DATA_DIR.glob("*.csv"))

    all_trades = []

    for csv_file in csv_files:
        month_name = csv_file.stem

        # Load data
        df = pd.read_csv(csv_file)
        df['Datetime'] = pd.to_datetime(df['Datetime'])

        # Backtest
        trades = backtest_strategy(df, mode, exit_rsi, stop_loss_pts)

        # Add metadata
        for trade in trades:
            trade['month'] = month_name
            trade['strategy'] = strategy_name

        all_trades.extend(trades)

    return strategy_name, all_trades


# ==================== MAIN ====================

def main():
    print("=" * 80)
    print("RSI TRAILING EXIT OPTIMIZER")
    print("=" * 80)
    print()

    print("Configuration:")
    print(f"  Entry: RSI < {CONFIG['entry_rsi_long']} (LONG), RSI > {CONFIG['entry_rsi_short']} (SHORT)")
    print(f"  Exit RSI Levels: {CONFIG['exit_rsi_levels']}")
    print(f"  Stop Loss Levels: {CONFIG['stop_loss_points']} points")
    print(f"  Modes: {CONFIG['modes']}")
    print(f"  Slippage: {CONFIG['slippage_pips']} pip")
    print()

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "trades").mkdir(exist_ok=True)

    # Generate all strategy combinations
    strategies = []
    for mode in CONFIG['modes']:
        for exit_rsi in CONFIG['exit_rsi_levels']:
            for stop_loss in CONFIG['stop_loss_points']:
                strategies.append((mode, exit_rsi, stop_loss))

    print(f"📊 Testing {len(strategies)} strategy combinations...")
    print(f"🚀 Using {mp.cpu_count()-1} parallel processes")
    print()

    # Run in parallel
    with mp.Pool(processes=mp.cpu_count()-1) as pool:
        results = pool.map(process_strategy, strategies)

    print("✅ Backtesting complete!")
    print()

    # Process results
    print("📁 Saving results...")

    all_summary = []

    for strategy_name, trades in results:
        if not trades:
            continue

        # Save individual strategy trades
        trades_df = pd.DataFrame(trades)
        trades_file = OUTPUT_DIR / "trades" / f"{strategy_name}.csv"
        trades_df.to_csv(trades_file, index=False)

        # Calculate summary stats
        total_pnl = trades_df['net_pnl'].sum()
        wins = len(trades_df[trades_df['net_pnl'] > 0])
        losses = len(trades_df[trades_df['net_pnl'] <= 0])
        win_rate = wins / len(trades_df) * 100 if len(trades_df) > 0 else 0

        # Monthly breakdown
        monthly = trades_df.groupby('month')['net_pnl'].sum()
        profitable_months = len(monthly[monthly > 0])
        total_months = len(monthly)
        consistency = profitable_months / total_months * 100 if total_months > 0 else 0

        all_summary.append({
            'strategy': strategy_name,
            'total_trades': len(trades_df),
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'net_pnl': total_pnl,
            'profitable_months': profitable_months,
            'total_months': total_months,
            'consistency': consistency,
        })

    # Save summary
    summary_df = pd.DataFrame(all_summary)
    summary_df = summary_df.sort_values('net_pnl', ascending=False)

    summary_file = OUTPUT_DIR / "summary_by_strategy.csv"
    summary_df.to_csv(summary_file, index=False)

    print(f"💾 Saved {len(results)} strategy results")
    print(f"💾 Summary: {summary_file}")
    print()

    # Show top 10
    print("=" * 80)
    print("TOP 10 STRATEGIES")
    print("=" * 80)
    print()

    top10 = summary_df.head(10)
    for _, row in top10.iterrows():
        print(f"{row['strategy']:30s} | Trades: {row['total_trades']:4.0f} | "
              f"WR: {row['win_rate']:5.1f}% | Net P&L: {row['net_pnl']:+9.2f} | "
              f"Consistency: {row['consistency']:5.1f}%")

    print()
    print("=" * 80)
    print("✅ COMPLETE")
    print("=" * 80)
    print()
    print(f"Results saved to: {OUTPUT_DIR}")
    print()


if __name__ == "__main__":
    main()
