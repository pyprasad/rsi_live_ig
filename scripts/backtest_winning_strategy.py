"""
Simple Backtest Script for Winning Strategy

Tests the validated winning strategy on your historical data.

Winning Strategy: RSI2_L15_S90_RR5.0_SL2_both (with_filters)
"""
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, time, timedelta
import pytz
import sys

# Import from optimizer
sys.path.insert(0, str(Path(__file__).parent))
from optimize_dax_advanced import (
    calculate_rsi,
    should_skip_trade,
    TIMEZONE,
    BASE_SESSION_START,
    BASE_SESSION_END
)

# WINNING STRATEGY CONFIGURATION
CONFIG = {
    'name': 'RSI2_L15_S90_RR5.0_SL2_both_with_filters',
    'rsi_period': 2,
    'long_threshold': 15,
    'short_threshold': 90,
    'rr_ratio': 5.0,
    'sl_lookback': 2,
    'trade_mode': 'both',
    'skip_dax_open': True,
    'skip_us_open': True
}

# Capital Management Configuration
CAPITAL_CONFIG = {
    'starting_capital': 10000,          # £10,000 starting capital per year
    'ig_margin_requirement': 0.05,      # IG's 5% margin requirement for DAX
    'safety_buffer': 0.03,              # Our 3% safety buffer on top
    'max_margin_usage': 0.08,           # Total max margin: 5% + 3% = 8%
    'margin_call_threshold': 0.05,      # Account closes if equity drops below 5% of starting capital
    'use_fixed_position_size': True,    # True = fixed position size, False = dynamic sizing
    'fixed_position_size': 2.0,         # Fixed position size in £/point (when use_fixed_position_size = True)
}

DATA_DIR = Path("data/dax_monthly")
OUTPUT_DIR = Path("results/backtest")


def calculate_position_size(current_capital, dax_price):
    """
    Calculate position size based on configuration.

    Two modes:
    1. Fixed Position Size (use_fixed_position_size = True):
       - Always use fixed_position_size (e.g., £1/point)
       - Check if we have enough capital to support this trade
       - Required capital = DAX price × position size × 8%
       - Returns None if insufficient capital

    2. Dynamic Position Size (use_fixed_position_size = False):
       - Calculate position size based on available capital
       - Formula: Position size = Capital / 8% / DAX price
       - Ensures we maintain 8% of position value as available balance

    Example (Fixed £1/point, DAX at 24,420):
    - Nominal exposure = 24,420 × £1 = £24,420
    - Margin required (5%) = £24,420 × 5% = £1,221
    - Safety buffer (3%) = £24,420 × 3% = £733
    - Total needed (8%) = £1,221 + £733 = £1,954
    - Can trade if capital >= £1,954 ✓

    Returns: position_size in £/point, or None if insufficient capital
    """
    if CAPITAL_CONFIG['use_fixed_position_size']:
        # Fixed position size mode
        position_size = CAPITAL_CONFIG['fixed_position_size']

        # Calculate required capital for this trade
        nominal_exposure = dax_price * position_size
        required_capital = nominal_exposure * CAPITAL_CONFIG['max_margin_usage']

        # Check if we have enough capital
        if current_capital < required_capital:
            return None  # Cannot afford this trade

        return position_size

    else:
        # Dynamic position size mode
        max_nominal_exposure = current_capital / CAPITAL_CONFIG['max_margin_usage']
        position_size = max_nominal_exposure / dax_price
        return round(position_size, 2)


def backtest_strategy(df, config):
    """
    Backtest the winning strategy on given data.
    """
    df = df.copy()
    df['RSI'] = calculate_rsi(df['Close'], period=config['rsi_period'])

    # Generate signals
    df['prev_RSI'] = df['RSI'].shift(1)
    df['long_signal'] = (df['prev_RSI'] <= config['long_threshold']) & (df['RSI'] > config['long_threshold'])
    df['short_signal'] = (df['prev_RSI'] >= config['short_threshold']) & (df['RSI'] < config['short_threshold'])

    # Apply trade mode filter
    if config['trade_mode'] == "long_only":
        df['short_signal'] = False
    elif config['trade_mode'] == "short_only":
        df['long_signal'] = False

    # Track trades
    trades = []
    in_position = False
    position_type = None
    entry_price = None
    entry_idx = None
    stop_loss = None
    take_profit = None
    position_size = None
    sl_lookback = config['sl_lookback']

    # Capital tracking
    current_capital = CAPITAL_CONFIG['starting_capital']
    margin_called = False

    for i in range(sl_lookback, len(df)):
        row = df.iloc[i]
        dt_berlin = row['Datetime']

        # Check for margin call - stop trading if equity below 5% threshold
        margin_call_equity = CAPITAL_CONFIG['starting_capital'] * CAPITAL_CONFIG['margin_call_threshold']
        if current_capital < margin_call_equity:
            if not margin_called:
                margin_called = True
                # Close any open position immediately at current price
                if in_position:
                    exit_price = row['Close']
                    if position_type == "LONG":
                        pnl_pts = exit_price - entry_price
                    else:
                        pnl_pts = entry_price - exit_price

                    pnl_gbp = pnl_pts * position_size
                    current_capital += pnl_gbp

                    trades.append({
                        "entry_time": df.iloc[entry_idx]['Datetime'],
                        "exit_time": row['Datetime'],
                        "type": position_type,
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "sl": stop_loss,
                        "tp": take_profit,
                        "pnl_pts": pnl_pts,
                        "exit_reason": "MARGIN_CALL",
                        "bars_held": i - entry_idx,
                        "position_size": position_size,
                        "pnl_gbp": pnl_gbp,
                        "capital_after": current_capital
                    })

                    in_position = False
                    position_type = None
            break  # Stop trading for this dataset

        # Skip if in filtered session periods
        if should_skip_trade(dt_berlin, config['skip_dax_open'], config['skip_us_open']):
            continue

        # Skip if outside base session hours
        trade_time = dt_berlin.time()
        if not (BASE_SESSION_START <= trade_time < BASE_SESSION_END):
            continue

        # Check if in position
        if in_position:
            hit_tp = False
            hit_sl = False

            if position_type == "LONG":
                hit_tp = row['High'] >= take_profit
                hit_sl = row['Low'] <= stop_loss
            else:  # SHORT
                hit_tp = row['Low'] <= take_profit
                hit_sl = row['High'] >= stop_loss

            exit_price = None
            exit_reason = None

            if hit_sl and hit_tp:
                exit_price = stop_loss
                exit_reason = "SL"
            elif hit_sl:
                exit_price = stop_loss
                exit_reason = "SL"
            elif hit_tp:
                exit_price = take_profit
                exit_reason = "TP"

            if exit_price:
                if position_type == "LONG":
                    pnl_pts = exit_price - entry_price
                else:  # SHORT
                    pnl_pts = entry_price - exit_price

                # Calculate P&L in GBP and update capital
                pnl_gbp = pnl_pts * position_size
                current_capital += pnl_gbp

                trades.append({
                    "entry_time": df.iloc[entry_idx]['Datetime'],
                    "exit_time": row['Datetime'],
                    "type": position_type,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "sl": stop_loss,
                    "tp": take_profit,
                    "pnl_pts": pnl_pts,
                    "exit_reason": exit_reason,
                    "bars_held": i - entry_idx,
                    "position_size": position_size,
                    "pnl_gbp": pnl_gbp,
                    "capital_after": current_capital
                })

                in_position = False
                position_type = None

        # Check for new entry signals
        if not in_position:
            if row['long_signal']:
                entry_price = row['Close']
                entry_idx = i
                position_type = "LONG"

                lookback_slice = df.iloc[i - sl_lookback:i]
                stop_loss = lookback_slice['Low'].min()

                risk = entry_price - stop_loss
                if risk <= 0:
                    continue
                take_profit = entry_price + (risk * config['rr_ratio'])

                # Calculate position size based on current capital and DAX price
                position_size = calculate_position_size(current_capital, entry_price)

                # Skip trade if insufficient capital
                if position_size is None:
                    continue

                in_position = True

            elif row['short_signal']:
                entry_price = row['Close']
                entry_idx = i
                position_type = "SHORT"

                lookback_slice = df.iloc[i - sl_lookback:i]
                stop_loss = lookback_slice['High'].max()

                risk = stop_loss - entry_price
                if risk <= 0:
                    continue
                take_profit = entry_price - (risk * config['rr_ratio'])

                # Calculate position size based on current capital and DAX price
                position_size = calculate_position_size(current_capital, entry_price)

                # Skip trade if insufficient capital
                if position_size is None:
                    continue

                in_position = True

    # Calculate metrics
    if not trades:
        return None

    trades_df = pd.DataFrame(trades)
    wins = trades_df[trades_df['pnl_pts'] > 0]
    losses = trades_df[trades_df['pnl_pts'] <= 0]

    total_pnl = trades_df['pnl_pts'].sum()
    win_rate = len(wins) / len(trades_df) * 100

    total_win_pts = wins['pnl_pts'].sum() if len(wins) > 0 else 0.0
    total_loss_pts = abs(losses['pnl_pts'].sum()) if len(losses) > 0 else 0.0
    profit_factor = total_win_pts / total_loss_pts if total_loss_pts > 0 else 0.0

    avg_win = wins['pnl_pts'].mean() if len(wins) > 0 else 0.0
    avg_loss = losses['pnl_pts'].mean() if len(losses) > 0 else 0.0

    cumulative = trades_df['pnl_pts'].cumsum()
    running_max = cumulative.cummax()
    drawdown = running_max - cumulative
    max_drawdown = drawdown.max()

    long_trades = trades_df[trades_df['type'] == 'LONG']
    short_trades = trades_df[trades_df['type'] == 'SHORT']
    long_wins = long_trades[long_trades['pnl_pts'] > 0]
    short_wins = short_trades[short_trades['pnl_pts'] > 0]

    # Calculate GBP metrics
    total_pnl_gbp = trades_df['pnl_gbp'].sum()
    final_capital = current_capital
    gbp_wins = trades_df[trades_df['pnl_gbp'] > 0]
    gbp_losses = trades_df[trades_df['pnl_gbp'] <= 0]

    avg_win_gbp = gbp_wins['pnl_gbp'].mean() if len(gbp_wins) > 0 else 0.0
    avg_loss_gbp = gbp_losses['pnl_gbp'].mean() if len(gbp_losses) > 0 else 0.0

    # Calculate max drawdown in GBP
    cumulative_gbp = trades_df['pnl_gbp'].cumsum()
    running_max_gbp = cumulative_gbp.cummax()
    drawdown_gbp = running_max_gbp - cumulative_gbp
    max_drawdown_gbp = drawdown_gbp.max()

    # Get average and max position size
    avg_position_size = trades_df['position_size'].mean()
    max_position_size = trades_df['position_size'].max()

    return {
        'trades_df': trades_df,
        'total_trades': len(trades_df),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate_pct': round(win_rate, 2),
        'total_pnl_pts': round(total_pnl, 2),
        'avg_win_pts': round(avg_win, 2),
        'avg_loss_pts': round(avg_loss, 2),
        'profit_factor': round(profit_factor, 2),
        'max_drawdown_pts': round(max_drawdown, 2),
        'long_trades': len(long_trades),
        'short_trades': len(short_trades),
        'long_win_rate': round(len(long_wins) / len(long_trades) * 100, 1) if len(long_trades) > 0 else 0.0,
        'short_win_rate': round(len(short_wins) / len(short_trades) * 100, 1) if len(short_trades) > 0 else 0.0,
        'total_pnl_gbp': round(total_pnl_gbp, 2),
        'final_capital': round(final_capital, 2),
        'avg_win_gbp': round(avg_win_gbp, 2),
        'avg_loss_gbp': round(avg_loss_gbp, 2),
        'max_drawdown_gbp': round(max_drawdown_gbp, 2),
        'avg_position_size': round(avg_position_size, 2),
        'max_position_size': round(max_position_size, 2),
        'margin_called': margin_called
    }


def main():
    print("=" * 80)
    print("BACKTEST: WINNING STRATEGY")
    print("=" * 80)
    print()

    print("Strategy Configuration:")
    print(f"  Name: {CONFIG['name']}")
    print(f"  RSI Period: {CONFIG['rsi_period']}")
    print(f"  LONG Entry: RSI crosses above {CONFIG['long_threshold']}")
    print(f"  SHORT Entry: RSI crosses below {CONFIG['short_threshold']}")
    print(f"  Risk:Reward: {CONFIG['rr_ratio']}")
    print(f"  SL Lookback: {CONFIG['sl_lookback']} bars")
    print(f"  Trade Mode: {CONFIG['trade_mode']}")
    print(f"  Skip DAX Open: {CONFIG['skip_dax_open']}")
    print(f"  Skip US Open: {CONFIG['skip_us_open']}")
    print()

    print("Capital Management:")
    print(f"  Starting Capital: £{CAPITAL_CONFIG['starting_capital']:,} per year")
    print(f"  IG Margin Requirement: {CAPITAL_CONFIG['ig_margin_requirement']*100}%")
    print(f"  Safety Buffer: {CAPITAL_CONFIG['safety_buffer']*100}%")
    print(f"  Max Margin Usage: {CAPITAL_CONFIG['max_margin_usage']*100}%")
    print(f"  Margin Call Threshold: {CAPITAL_CONFIG['margin_call_threshold']*100}% of starting capital")
    if CAPITAL_CONFIG['use_fixed_position_size']:
        print(f"  Position Size: FIXED £{CAPITAL_CONFIG['fixed_position_size']:.2f}/point")
    else:
        print(f"  Position Size: DYNAMIC (based on available capital)")
    print()

    # Load all monthly data
    print(f"📂 Loading data from {DATA_DIR}...")
    csv_files = sorted(DATA_DIR.glob("*.csv"))

    if not csv_files:
        print(f"❌ No CSV files found in {DATA_DIR}")
        return

    all_data = []
    for csv_file in csv_files:
        df = pd.read_csv(csv_file)
        df['Datetime'] = pd.to_datetime(df['Datetime'])
        if df['Datetime'].dt.tz is None:
            df['Datetime'] = df['Datetime'].dt.tz_localize('UTC').dt.tz_convert(TIMEZONE)
        else:
            df['Datetime'] = df['Datetime'].dt.tz_convert(TIMEZONE)
        all_data.append(df)

    df_full = pd.concat(all_data, ignore_index=True)
    df_full = df_full.sort_values('Datetime').reset_index(drop=True)

    print(f"✅ Loaded {len(df_full):,} bars")
    print(f"   Date range: {df_full['Datetime'].min()} to {df_full['Datetime'].max()}")
    print()

    # Get years available
    df_full['Year'] = df_full['Datetime'].dt.year
    years = sorted(df_full['Year'].unique())
    print(f"📅 Years available: {years}")
    print()

    # Run backtest year-by-year with capital reset
    print("🚀 Running backtest year-by-year...")
    print()

    print("=" * 80)
    print("YEAR-BY-YEAR BREAKDOWN")
    print("=" * 80)
    print()

    yearly_summary = []
    all_trades = []
    total_profit_gbp = 0.0

    for year in years:
        year_data = df_full[df_full['Year'] == year].copy()

        if len(year_data) == 0:
            continue

        print(f"Testing {year}...", end=" ")
        result = backtest_strategy(year_data, CONFIG)

        if result is None:
            print("No trades")
            continue

        year_pnl_gbp = result['total_pnl_gbp']
        total_profit_gbp += year_pnl_gbp

        # Store trades from this year
        year_trades = result['trades_df'].copy()
        all_trades.append(year_trades)

        yearly_summary.append({
            'year': year,
            'trades': result['total_trades'],
            'wins': result['wins'],
            'win_rate': result['win_rate_pct'],
            'pnl_pts': result['total_pnl_pts'],
            'pnl_gbp': year_pnl_gbp,
            'cumulative_gbp': total_profit_gbp,
            'final_capital': result['final_capital'],
            'avg_position_size': result['avg_position_size'],
            'max_position_size': result['max_position_size'],
            'margin_called': result['margin_called']
        })

        print(f"✅ {result['total_trades']} trades | £{year_pnl_gbp:+,.2f}")

    print()

    if not yearly_summary:
        print("❌ No trades generated!")
        return

    # Combine all trades for overall stats
    all_trades_df = pd.concat(all_trades, ignore_index=True)

    # Display yearly results
    print("=" * 80)
    print("YEARLY RESULTS (£10,000 starting capital each year)")
    print("=" * 80)
    print()

    for yr in yearly_summary:
        status = "✅" if yr['pnl_gbp'] > 0 else "❌"
        margin_warning = " ⚠️ MARGIN CALL!" if yr['margin_called'] else ""

        print(f"{yr['year']}: {yr['trades']:3d} trades | WR: {yr['win_rate']:5.1f}% | "
              f"P&L: £{yr['pnl_gbp']:+8.2f} | End Capital: £{yr['final_capital']:,.2f} | "
              f"Cumulative: £{yr['cumulative_gbp']:+,.2f} {status}{margin_warning}")
        print(f"       Avg Position: £{yr['avg_position_size']:.2f}/pt | "
              f"Max Position: £{yr['max_position_size']:.2f}/pt | "
              f"P&L (points): {yr['pnl_pts']:+.2f} pts")
        print()

    # Calculate profitability
    profitable_years = len([y for y in yearly_summary if y['pnl_gbp'] > 0])
    total_years = len(yearly_summary)
    consistency_pct = (profitable_years / total_years * 100) if total_years > 0 else 0.0

    # Calculate overall stats
    total_trades = sum(y['trades'] for y in yearly_summary)
    total_pnl_pts = sum(y['pnl_pts'] for y in yearly_summary)
    avg_pnl_per_year_gbp = total_profit_gbp / total_years if total_years > 0 else 0.0

    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()

    print(f"Years Tested: {total_years}")
    print(f"Total Trades: {total_trades}")
    print(f"Profitable Years: {profitable_years}/{total_years} ({consistency_pct:.1f}%)")
    print()
    print(f"Total P&L (all years): £{total_profit_gbp:+,.2f}")
    print(f"Total P&L (points): {total_pnl_pts:+,.2f} pts")
    print(f"Average per Year: £{avg_pnl_per_year_gbp:+,.2f}")
    print()

    if consistency_pct >= 60:
        print("✅ Strategy shows GOOD consistency (60%+)")
        print("   Recommendation: Test on DEMO")
    else:
        print("⚠️  Strategy shows LOW consistency (< 60%)")
        print("   Recommendation: Consider different approach")

    print()

    # Save detailed trade log
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    trade_log_file = OUTPUT_DIR / "trade_log.csv"
    all_trades_df.to_csv(trade_log_file, index=False)
    print(f"💾 Trade log saved to: {trade_log_file}")

    # Save yearly summary
    yearly_file = OUTPUT_DIR / "yearly_summary.csv"
    pd.DataFrame(yearly_summary).to_csv(yearly_file, index=False)
    print(f"💾 Yearly summary saved to: {yearly_file}")
    print()


if __name__ == "__main__":
    main()
