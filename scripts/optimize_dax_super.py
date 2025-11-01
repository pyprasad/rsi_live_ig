#!/usr/bin/env python3
"""
DAX RSI Super Optimizer
Tests EVERY possible combination to find profitable strategies.

Testing:
1. Profit Targets: 5, 7, 10, 12, 15, 20, 25 points
2. Stop Loss: 20, 25, 30, 35, 40, 50, 60 points
3. Max Hold Time: None, 30, 45, 60, 90, 120, 180 minutes
4. Trailing Stop: None, 5, 10, 15, 20 points
5. Cooldown: 0, 10, 15, 20, 30 minutes
6. Modes: LONG_ONLY, SHORT_ONLY, BOTH
"""

from pathlib import Path
import pandas as pd
import multiprocessing as mp
import warnings
warnings.filterwarnings('ignore')


# ==================== CONFIGURATION ====================

CONFIG = {
    # Entry signals (fixed)
    'entry_rsi_long': 5,
    'entry_rsi_short': 95,

    # Parameter grid to test
    'profit_targets': [5, 7, 10, 12, 15, 20, 25],
    'stop_loss_points': [20, 25, 30, 35, 40, 50, 60],
    'max_hold_minutes': [None, 30, 45, 60, 90, 120, 180],  # None = no time limit
    'trailing_stop_points': [None, 5, 10, 15, 20],  # None = no trailing stop
    'cooldown_minutes': [0, 10, 15, 20, 30],
    'modes': ['LONG_ONLY', 'SHORT_ONLY', 'BOTH'],

    # Fixed settings
    'trading_hours': (8.0, 22.0),
    'slippage_pips': 1,
    'spread_schedule': [
        (8.0, 17.5, 1.5),
        (17.5, 22.0, 3.0),
        (22.0, 8.0, 6.0),
    ],
}

DATA_DIR = Path("data/dax_monthly")
OUTPUT_DIR = Path("results/dax_super_optimizer")


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
        if start < end:
            if start <= hour < end:
                return spread
        else:
            if hour >= start or hour < end:
                return spread
    return 3.0


def is_trading_hours(dt):
    """Check if time is within trading hours."""
    hour = dt.hour + dt.minute / 60.0
    start, end = CONFIG['trading_hours']
    return start <= hour < end


# ==================== BACKTEST FUNCTION ====================

def backtest_strategy(df, mode, profit_target_pts, stop_loss_pts, max_hold_min, trailing_stop_pts, cooldown_min):
    """
    Backtest with all possible parameters.
    """
    df = df.copy()
    df['RSI'] = calculate_rsi(df['Close'], period=2)

    trades = []
    in_position = False
    position_type = None
    entry_price = None
    entry_time = None
    stop_loss = None
    take_profit = None
    trailing_stop = None
    cooldown_until = None
    highest_price = None  # For trailing stop
    lowest_price = None

    slippage = CONFIG['slippage_pips']

    for i in range(3, len(df)):
        row = df.iloc[i]
        current_time = row['Datetime']

        # Exit logic (always check, even during cooldown)
        if in_position:
            exit_price = None
            exit_reason = None

            # Calculate hold time
            hold_minutes = (current_time - entry_time).total_seconds() / 60.0

            if position_type == "LONG":
                # Update trailing stop
                if trailing_stop_pts is not None:
                    if highest_price is None or row['High'] > highest_price:
                        highest_price = row['High']
                        trailing_stop = highest_price - trailing_stop_pts

                # Take Profit
                if row['High'] >= take_profit:
                    exit_price = take_profit - slippage
                    exit_reason = f"TP_{profit_target_pts}"

                # Stop Loss
                elif row['Low'] <= stop_loss:
                    exit_price = stop_loss - slippage
                    exit_reason = "SL"

                # Trailing Stop
                elif trailing_stop is not None and row['Low'] <= trailing_stop:
                    exit_price = trailing_stop - slippage
                    exit_reason = "TRAIL"

                # End of Trading Day
                elif not is_trading_hours(current_time):
                    exit_price = row['Close'] - slippage
                    exit_reason = "EOD"

                # Max Hold Time
                elif max_hold_min is not None and hold_minutes >= max_hold_min:
                    exit_price = row['Close'] - slippage
                    exit_reason = "MAX_HOLD"

            elif position_type == "SHORT":
                # Update trailing stop
                if trailing_stop_pts is not None:
                    if lowest_price is None or row['Low'] < lowest_price:
                        lowest_price = row['Low']
                        trailing_stop = lowest_price + trailing_stop_pts

                # Take Profit
                if row['Low'] <= take_profit:
                    exit_price = take_profit + slippage
                    exit_reason = f"TP_{profit_target_pts}"

                # Stop Loss
                elif row['High'] >= stop_loss:
                    exit_price = stop_loss + slippage
                    exit_reason = "SL"

                # Trailing Stop
                elif trailing_stop is not None and row['High'] >= trailing_stop:
                    exit_price = trailing_stop + slippage
                    exit_reason = "TRAIL"

                # End of Trading Day
                elif not is_trading_hours(current_time):
                    exit_price = row['Close'] + slippage
                    exit_reason = "EOD"

                # Max Hold Time
                elif max_hold_min is not None and hold_minutes >= max_hold_min:
                    exit_price = row['Close'] + slippage
                    exit_reason = "MAX_HOLD"

            # Record trade
            if exit_price:
                # Calculate P&L
                if position_type == "LONG":
                    raw_pnl = exit_price - entry_price
                else:
                    raw_pnl = entry_price - exit_price

                # Costs
                spread_cost = get_spread_for_time(entry_time)
                slippage_cost = 2 * slippage
                net_pnl = raw_pnl - spread_cost - slippage_cost

                trades.append({
                    'entry_time': entry_time,
                    'exit_time': current_time,
                    'hold_minutes': hold_minutes,
                    'type': position_type,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'raw_pnl': raw_pnl,
                    'net_pnl': net_pnl,
                    'exit_reason': exit_reason,
                })

                # Set cooldown if stop loss hit
                if exit_reason in ["SL", "TRAIL"] and cooldown_min > 0:
                    cooldown_until = current_time + pd.Timedelta(minutes=cooldown_min)

                in_position = False
                highest_price = None
                lowest_price = None

        # Entry logic
        if not in_position:
            # Skip if in cooldown
            if cooldown_until and current_time < cooldown_until:
                continue

            # Only trade during trading hours
            if not is_trading_hours(current_time):
                continue

            # LONG entry
            if mode in ['LONG_ONLY', 'BOTH'] and row['RSI'] < CONFIG['entry_rsi_long']:
                entry_price = row['Close'] + slippage
                entry_time = current_time
                position_type = "LONG"

                take_profit = entry_price + profit_target_pts
                stop_loss = entry_price - stop_loss_pts

                # Initialize trailing stop at entry SL level
                if trailing_stop_pts is not None:
                    trailing_stop = stop_loss
                    highest_price = entry_price
                else:
                    trailing_stop = None

                in_position = True

            # SHORT entry
            elif mode in ['SHORT_ONLY', 'BOTH'] and row['RSI'] > CONFIG['entry_rsi_short']:
                entry_price = row['Close'] - slippage
                entry_time = current_time
                position_type = "SHORT"

                take_profit = entry_price - profit_target_pts
                stop_loss = entry_price + stop_loss_pts

                # Initialize trailing stop
                if trailing_stop_pts is not None:
                    trailing_stop = stop_loss
                    lowest_price = entry_price
                else:
                    trailing_stop = None

                in_position = True

    return trades


# ==================== WORKER FUNCTION ====================

def process_strategy(args):
    """Process one strategy combination."""
    mode, tp, sl, max_hold, trail, cooldown = args

    # Create strategy name
    trail_str = f"_TRAIL{trail}" if trail is not None else ""
    hold_str = f"_HOLD{max_hold}" if max_hold is not None else "_NOHOLD"
    cool_str = f"_COOL{cooldown}" if cooldown > 0 else ""

    strategy_name = f"{mode}_TP{tp}_SL{sl}{trail_str}{hold_str}{cool_str}"

    # Load all monthly files
    csv_files = sorted(DATA_DIR.glob("*.csv"))
    all_trades = []

    for csv_file in csv_files:
        month_name = csv_file.stem

        df = pd.read_csv(csv_file)
        df['Datetime'] = pd.to_datetime(df['Datetime'])

        trades = backtest_strategy(df, mode, tp, sl, max_hold, trail, cooldown)

        for trade in trades:
            trade['month'] = month_name
            trade['strategy'] = strategy_name

        all_trades.extend(trades)

    return strategy_name, all_trades


# ==================== MAIN ====================

def main():
    print("=" * 100)
    print("DAX RSI SUPER OPTIMIZER")
    print("Finding the most profitable strategy combination")
    print("=" * 100)
    print()

    # Generate all combinations
    strategies = []
    for mode in CONFIG['modes']:
        for tp in CONFIG['profit_targets']:
            for sl in CONFIG['stop_loss_points']:
                # Skip if SL >= TP (doesn't make sense)
                if sl >= tp * 2:  # Allow SL up to 2x TP
                    for max_hold in CONFIG['max_hold_minutes']:
                        for trail in CONFIG['trailing_stop_points']:
                            for cooldown in CONFIG['cooldown_minutes']:
                                strategies.append((mode, tp, sl, max_hold, trail, cooldown))

    print(f"📊 Testing {len(strategies)} strategy combinations...")
    print(f"   Profit Targets: {CONFIG['profit_targets']}")
    print(f"   Stop Loss: {CONFIG['stop_loss_points']}")
    print(f"   Max Hold: {CONFIG['max_hold_minutes']}")
    print(f"   Trailing Stop: {CONFIG['trailing_stop_points']}")
    print(f"   Cooldown: {CONFIG['cooldown_minutes']}")
    print(f"   Modes: {CONFIG['modes']}")
    print()
    print(f"🚀 Using {mp.cpu_count()-1} parallel processes")
    print()

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Run in parallel
    with mp.Pool(processes=mp.cpu_count()-1) as pool:
        results = pool.map(process_strategy, strategies)

    print("✅ Backtesting complete!")
    print()

    # Process results
    print("📁 Analyzing results...")

    all_summary = []

    for strategy_name, trades in results:
        if not trades or len(trades) == 0:
            continue

        trades_df = pd.DataFrame(trades)

        # Calculate metrics
        total_pnl = trades_df['net_pnl'].sum()
        wins = len(trades_df[trades_df['net_pnl'] > 0])
        losses = len(trades_df[trades_df['net_pnl'] <= 0])
        win_rate = wins / len(trades_df) * 100 if len(trades_df) > 0 else 0

        gross_profit = trades_df[trades_df['net_pnl'] > 0]['net_pnl'].sum() if wins > 0 else 0
        gross_loss = abs(trades_df[trades_df['net_pnl'] <= 0]['net_pnl'].sum()) if losses > 0 else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        # Monthly breakdown
        monthly = trades_df.groupby('month')['net_pnl'].sum()
        profitable_months = len(monthly[monthly > 0])
        total_months = len(monthly)
        consistency = profitable_months / total_months * 100 if total_months > 0 else 0

        # Average metrics
        avg_hold = trades_df['hold_minutes'].mean()
        avg_win = trades_df[trades_df['net_pnl'] > 0]['net_pnl'].mean() if wins > 0 else 0
        avg_loss = trades_df[trades_df['net_pnl'] <= 0]['net_pnl'].mean() if losses > 0 else 0

        all_summary.append({
            'strategy': strategy_name,
            'total_trades': len(trades_df),
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'net_pnl': total_pnl,
            'profit_factor': profit_factor,
            'avg_hold_min': avg_hold,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profitable_months': profitable_months,
            'total_months': total_months,
            'consistency': consistency,
        })

    # Save summary
    summary_df = pd.DataFrame(all_summary)

    # Sort by net P&L descending
    summary_df = summary_df.sort_values('net_pnl', ascending=False)

    summary_file = OUTPUT_DIR / "super_optimizer_results.csv"
    summary_df.to_csv(summary_file, index=False)

    print(f"💾 Summary saved: {summary_file}")
    print()

    # Find profitable strategies
    profitable = summary_df[summary_df['net_pnl'] > 0]

    print("=" * 100)
    print(f"PROFITABLE STRATEGIES FOUND: {len(profitable)}")
    print("=" * 100)
    print()

    if len(profitable) > 0:
        print("TOP 20 PROFITABLE STRATEGIES:")
        print()

        top20 = profitable.head(20)
        for idx, row in top20.iterrows():
            print(f"{row['strategy']:60s} | Trades: {row['total_trades']:4.0f} | "
                  f"WR: {row['win_rate']:5.1f}% | PF: {row['profit_factor']:5.2f} | "
                  f"Net: {row['net_pnl']:+10.2f} | Consistency: {row['consistency']:5.1f}%")

        print()
        print("=" * 100)
        print("BEST STRATEGY DETAILS")
        print("=" * 100)

        best = profitable.iloc[0]
        print(f"Strategy: {best['strategy']}")
        print(f"Total Trades: {best['total_trades']:.0f}")
        print(f"Win Rate: {best['win_rate']:.1f}%")
        print(f"Profit Factor: {best['profit_factor']:.2f}")
        print(f"Net P&L: £{best['net_pnl']:+.2f}")
        print(f"Average Win: £{best['avg_win']:+.2f}")
        print(f"Average Loss: £{best['avg_loss']:+.2f}")
        print(f"Average Hold: {best['avg_hold_min']:.1f} minutes")
        print(f"Consistency: {best['consistency']:.1f}% ({best['profitable_months']:.0f}/{best['total_months']:.0f} months)")
        print()
    else:
        print("⚠️  NO PROFITABLE STRATEGIES FOUND")
        print()
        print("TOP 20 LEAST LOSING STRATEGIES:")
        print()

        top20 = summary_df.head(20)
        for idx, row in top20.iterrows():
            print(f"{row['strategy']:60s} | Trades: {row['total_trades']:4.0f} | "
                  f"WR: {row['win_rate']:5.1f}% | PF: {row['profit_factor']:5.2f} | "
                  f"Net: {row['net_pnl']:+10.2f}")

    print()
    print("=" * 100)
    print("✅ SUPER OPTIMIZATION COMPLETE")
    print("=" * 100)
    print()


if __name__ == "__main__":
    main()
