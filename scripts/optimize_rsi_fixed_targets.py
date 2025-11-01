#!/usr/bin/env python3
"""
RSI Fixed Target Optimizer
Tests RSI(2) reversal with FIXED POINT profit targets.
Designed to capture quick bounces shown in DAX chart.

Strategy:
- Entry: RSI(2) < 5 (LONG), RSI(2) > 95 (SHORT)
- Exit: Fixed point targets (5, 10, 15, 20 points)
- Stop Loss: Wider levels (30, 40, 50 points) to avoid noise
- Max Hold: 60 minutes
- Cooldown: 15 minutes after stop loss
- Time Filter: 8:00-22:00 only
"""

from pathlib import Path
import pandas as pd
import multiprocessing as mp
import warnings
warnings.filterwarnings('ignore')


# ==================== CONFIGURATION ====================

CONFIG = {
    # Strategy parameters
    'entry_rsi_long': 5,         # Enter LONG when RSI < 5
    'entry_rsi_short': 95,       # Enter SHORT when RSI > 95

    # Fixed point profit targets to test
    'profit_targets': [5, 10, 15, 20],

    # Stop loss levels to test (wider to avoid noise)
    'stop_loss_points': [30, 40, 50],

    # Trade modes
    'modes': ['LONG_ONLY', 'SHORT_ONLY', 'BOTH'],

    # Time management
    'max_hold_minutes': 60,      # Exit after 60 min even if no signal
    'cooldown_minutes': 15,      # Wait 15 min after SL before next trade
    'trading_hours': (8.0, 22.0),  # Trade 8:00-22:00 only

    # Costs
    'slippage_pips': 1,

    # Spread by time (hour_start, hour_end, spread_points)
    'spread_schedule': [
        (8.0, 17.5, 1.5),        # Main hours: 08:00-17:30, 1.5 points
        (17.5, 22.0, 3.0),       # Extended: 17:30-22:00, 3 points
        (22.0, 8.0, 6.0),        # Night: 22:00-08:00, 6 points (avoid this)
    ],
}

DATA_DIR = Path("data/dax_monthly")
OUTPUT_DIR = Path("results/rsi_fixed_targets")


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
        else:  # Wraps midnight
            if hour >= start or hour < end:
                return spread

    return 3.0


def is_trading_hours(dt):
    """Check if time is within trading hours."""
    hour = dt.hour + dt.minute / 60.0
    start, end = CONFIG['trading_hours']
    return start <= hour < end


# ==================== BACKTEST FUNCTION ====================

def backtest_strategy(df, mode, profit_target_pts, stop_loss_pts):
    """
    Backtest with FIXED POINT profit targets.
    Captures quick bounces shown in DAX chart.
    """
    df = df.copy()
    df['RSI'] = calculate_rsi(df['Close'], period=2)

    trades = []
    in_position = False
    position_type = None
    entry_price = None
    entry_time = None
    entry_idx = None
    stop_loss = None
    take_profit = None
    cooldown_until = None

    slippage = CONFIG['slippage_pips']
    max_hold_minutes = CONFIG['max_hold_minutes']
    cooldown_minutes = CONFIG['cooldown_minutes']

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
                # Take Profit: Hit target
                if row['High'] >= take_profit:
                    exit_price = take_profit - slippage  # Slippage on exit
                    exit_reason = f"TP_{profit_target_pts}"

                # Stop Loss: Hit SL
                elif row['Low'] <= stop_loss:
                    exit_price = stop_loss - slippage
                    exit_reason = "SL"

                # End of Trading Day: Force exit at 22:00
                elif not is_trading_hours(current_time):
                    exit_price = row['Close'] - slippage
                    exit_reason = "EOD"

                # Max Hold Time: Exit after 60 minutes
                elif hold_minutes >= max_hold_minutes:
                    exit_price = row['Close'] - slippage
                    exit_reason = "MAX_HOLD"

            elif position_type == "SHORT":
                # Take Profit: Hit target
                if row['Low'] <= take_profit:
                    exit_price = take_profit + slippage
                    exit_reason = f"TP_{profit_target_pts}"

                # Stop Loss: Hit SL
                elif row['High'] >= stop_loss:
                    exit_price = stop_loss + slippage
                    exit_reason = "SL"

                # End of Trading Day: Force exit at 22:00
                elif not is_trading_hours(current_time):
                    exit_price = row['Close'] + slippage
                    exit_reason = "EOD"

                # Max Hold Time
                elif hold_minutes >= max_hold_minutes:
                    exit_price = row['Close'] + slippage
                    exit_reason = "MAX_HOLD"

            # Record trade
            if exit_price:
                # Calculate raw P&L
                if position_type == "LONG":
                    raw_pnl = exit_price - entry_price
                else:
                    raw_pnl = entry_price - exit_price

                # Costs (spread paid ONCE at entry)
                spread_cost = get_spread_for_time(entry_time)
                slippage_cost = 2 * slippage  # Entry + exit

                # Net P&L
                net_pnl = raw_pnl - spread_cost - slippage_cost

                trades.append({
                    'entry_time': entry_time,
                    'exit_time': current_time,
                    'hold_minutes': hold_minutes,
                    'type': position_type,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'tp': take_profit,
                    'sl': stop_loss,
                    'raw_pnl': raw_pnl,
                    'spread_cost': spread_cost,
                    'slippage_cost': slippage_cost,
                    'net_pnl': net_pnl,
                    'exit_reason': exit_reason,
                    'entry_hour': entry_time.hour + entry_time.minute/60.0,
                })

                # Set cooldown if stop loss hit
                if exit_reason == "SL":
                    cooldown_until = current_time + pd.Timedelta(minutes=cooldown_minutes)

                in_position = False

        # Entry logic
        if not in_position:
            # Skip if in cooldown period
            if cooldown_until and current_time < cooldown_until:
                continue

            # Only trade during trading hours
            if not is_trading_hours(current_time):
                continue

            # LONG entry
            if mode in ['LONG_ONLY', 'BOTH'] and row['RSI'] < CONFIG['entry_rsi_long']:
                entry_price = row['Close'] + slippage
                entry_time = current_time
                entry_idx = i
                position_type = "LONG"

                # Fixed point targets
                take_profit = entry_price + profit_target_pts
                stop_loss = entry_price - stop_loss_pts

                in_position = True

            # SHORT entry
            elif mode in ['SHORT_ONLY', 'BOTH'] and row['RSI'] > CONFIG['entry_rsi_short']:
                entry_price = row['Close'] - slippage
                entry_time = current_time
                entry_idx = i
                position_type = "SHORT"

                # Fixed point targets
                take_profit = entry_price - profit_target_pts
                stop_loss = entry_price + stop_loss_pts

                in_position = True

    return trades


# ==================== WORKER FUNCTION ====================

def process_strategy(args):
    """Process one strategy combination across all months."""
    mode, profit_target_pts, stop_loss_pts = args

    strategy_name = f"{mode}_TP{profit_target_pts}_SL{stop_loss_pts}"

    # Load all monthly files
    csv_files = sorted(DATA_DIR.glob("*.csv"))

    all_trades = []

    for csv_file in csv_files:
        month_name = csv_file.stem

        # Load data
        df = pd.read_csv(csv_file)
        df['Datetime'] = pd.to_datetime(df['Datetime'])

        # Backtest
        trades = backtest_strategy(df, mode, profit_target_pts, stop_loss_pts)

        # Add metadata
        for trade in trades:
            trade['month'] = month_name
            trade['strategy'] = strategy_name

        all_trades.extend(trades)

    return strategy_name, all_trades


# ==================== MAIN ====================

def main():
    print("=" * 80)
    print("RSI FIXED TARGET OPTIMIZER")
    print("Strategy: Capture quick bounces at RSI extremes")
    print("=" * 80)
    print()

    print("Configuration:")
    print(f"  Entry: RSI < {CONFIG['entry_rsi_long']} (LONG), RSI > {CONFIG['entry_rsi_short']} (SHORT)")
    print(f"  Profit Targets: {CONFIG['profit_targets']} points")
    print(f"  Stop Loss Levels: {CONFIG['stop_loss_points']} points")
    print(f"  Max Hold Time: {CONFIG['max_hold_minutes']} minutes")
    print(f"  Cooldown After SL: {CONFIG['cooldown_minutes']} minutes")
    print(f"  Trading Hours: {CONFIG['trading_hours'][0]:02.0f}:00 - {CONFIG['trading_hours'][1]:02.0f}:00")
    print(f"  Modes: {CONFIG['modes']}")
    print(f"  Slippage: {CONFIG['slippage_pips']} pip per side")
    print()

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "trades").mkdir(exist_ok=True)

    # Generate all strategy combinations
    strategies = []
    for mode in CONFIG['modes']:
        for tp in CONFIG['profit_targets']:
            for sl in CONFIG['stop_loss_points']:
                strategies.append((mode, tp, sl))

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

        # Profit metrics
        gross_profit = trades_df[trades_df['net_pnl'] > 0]['net_pnl'].sum() if wins > 0 else 0
        gross_loss = abs(trades_df[trades_df['net_pnl'] <= 0]['net_pnl'].sum()) if losses > 0 else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        # Exit reasons breakdown
        tp_exits = len(trades_df[trades_df['exit_reason'].str.startswith('TP_')])
        sl_exits = len(trades_df[trades_df['exit_reason'] == 'SL'])
        max_hold_exits = len(trades_df[trades_df['exit_reason'] == 'MAX_HOLD'])

        # Monthly breakdown
        monthly = trades_df.groupby('month')['net_pnl'].sum()
        profitable_months = len(monthly[monthly > 0])
        total_months = len(monthly)
        consistency = profitable_months / total_months * 100 if total_months > 0 else 0

        # Average hold time
        avg_hold_minutes = trades_df['hold_minutes'].mean()

        all_summary.append({
            'strategy': strategy_name,
            'total_trades': len(trades_df),
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'net_pnl': total_pnl,
            'gross_profit': gross_profit,
            'gross_loss': gross_loss,
            'profit_factor': profit_factor,
            'tp_exits': tp_exits,
            'sl_exits': sl_exits,
            'max_hold_exits': max_hold_exits,
            'avg_hold_min': avg_hold_minutes,
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
        print(f"{row['strategy']:25s} | Trades: {row['total_trades']:4.0f} | "
              f"WR: {row['win_rate']:5.1f}% | PF: {row['profit_factor']:4.2f} | "
              f"Net: {row['net_pnl']:+9.2f} | Consistency: {row['consistency']:5.1f}%")

    print()

    # Show exit reasons for top strategy
    if len(top10) > 0:
        top = top10.iloc[0]
        print("=" * 80)
        print(f"TOP STRATEGY EXIT BREAKDOWN: {top['strategy']}")
        print("=" * 80)
        print(f"  Take Profit Exits: {top['tp_exits']:.0f} ({top['tp_exits']/top['total_trades']*100:.1f}%)")
        print(f"  Stop Loss Exits: {top['sl_exits']:.0f} ({top['sl_exits']/top['total_trades']*100:.1f}%)")
        print(f"  Max Hold Exits: {top['max_hold_exits']:.0f} ({top['max_hold_exits']/top['total_trades']*100:.1f}%)")
        print(f"  Avg Hold Time: {top['avg_hold_min']:.1f} minutes")
        print()

    print("=" * 80)
    print("✅ COMPLETE")
    print("=" * 80)
    print()
    print(f"Results saved to: {OUTPUT_DIR}")
    print()


if __name__ == "__main__":
    main()
