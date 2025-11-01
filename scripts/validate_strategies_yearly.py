"""
Year-by-Year Strategy Validator

Takes top strategies from optimizer results and tests each one on individual years
to assess consistency and robustness.

Purpose:
- Find which strategies are consistently profitable across years
- Identify if recent years are still profitable
- Compare LONG-only vs SHORT-only vs BOTH modes
- Avoid curve-fitting by validating year-by-year performance
"""
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, time, timedelta
import pytz
import sys

# Import functions from the optimizer
sys.path.insert(0, str(Path(__file__).parent))
from optimize_dax_advanced import (
    calculate_rsi,
    should_skip_trade,
    TIMEZONE,
    BASE_SESSION_START,
    BASE_SESSION_END
)

# Configuration
OPTIMIZER_RESULTS = Path("results/dax_advanced/dax_advanced_results.csv")
DATA_DIR = Path("data/dax_monthly")
OUTPUT_DIR = Path("results/yearly_validation")
OUTPUT_FILE = OUTPUT_DIR / "yearly_breakdown.csv"
SUMMARY_FILE = OUTPUT_DIR / "yearly_summary.txt"

# Selection criteria
TOP_N_STRATEGIES = 15  # Top 15 strategies to validate
MIN_TRADES_OVERALL = 100  # Minimum trades in aggregate results
MIN_PROFIT_FACTOR = 1.05  # Minimum PF to consider
MIN_TRADES_PER_YEAR = 5  # Flag years with fewer trades


def backtest_strategy_on_year(df, config):
    """
    Backtest a strategy configuration on a specific year's data.

    Returns dict with year-specific metrics.
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
    sl_lookback = config['sl_lookback']

    for i in range(sl_lookback, len(df)):
        row = df.iloc[i]
        dt_berlin = row['Datetime']

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

                trades.append({
                    "entry_time": df.iloc[entry_idx]['Datetime'],
                    "exit_time": row['Datetime'],
                    "type": position_type,
                    "pnl_pts": pnl_pts,
                    "exit_reason": exit_reason,
                    "bars_held": i - entry_idx
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

                if config['tp_type'] == 'fixed':
                    take_profit = entry_price + config['fixed_tp_points']
                else:  # ratio
                    risk = entry_price - stop_loss
                    if risk <= 0:
                        continue
                    take_profit = entry_price + (risk * config['rr_ratio'])

                in_position = True

            elif row['short_signal']:
                entry_price = row['Close']
                entry_idx = i
                position_type = "SHORT"

                lookback_slice = df.iloc[i - sl_lookback:i]
                stop_loss = lookback_slice['High'].max()

                if config['tp_type'] == 'fixed':
                    take_profit = entry_price - config['fixed_tp_points']
                else:  # ratio
                    risk = stop_loss - entry_price
                    if risk <= 0:
                        continue
                    take_profit = entry_price - (risk * config['rr_ratio'])

                in_position = True

    # Calculate metrics
    if not trades:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "total_pnl_pts": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_pts": 0.0,
            "avg_bars_held": 0.0
        }

    trades_df = pd.DataFrame(trades)
    wins = trades_df[trades_df['pnl_pts'] > 0]
    losses = trades_df[trades_df['pnl_pts'] <= 0]

    total_pnl = trades_df['pnl_pts'].sum()
    win_rate = len(wins) / len(trades_df) * 100 if len(trades_df) > 0 else 0.0

    total_win_pts = wins['pnl_pts'].sum() if len(wins) > 0 else 0.0
    total_loss_pts = abs(losses['pnl_pts'].sum()) if len(losses) > 0 else 0.0
    profit_factor = total_win_pts / total_loss_pts if total_loss_pts > 0 else 0.0

    cumulative = trades_df['pnl_pts'].cumsum()
    running_max = cumulative.cummax()
    drawdown = running_max - cumulative
    max_drawdown = drawdown.max()

    avg_bars_held = trades_df['bars_held'].mean()

    return {
        "trades": len(trades_df),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(win_rate, 2),
        "total_pnl_pts": round(total_pnl, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown_pts": round(max_drawdown, 2),
        "avg_bars_held": round(avg_bars_held, 1)
    }


def select_top_strategies(results_df, top_n=15):
    """
    Select diverse top strategies:
    - Top 5 long_only
    - Top 5 short_only
    - Top 5 both
    """
    # Filter: profitable, enough trades, decent PF
    filtered = results_df[
        (results_df['total_pnl_pts'] > 0) &
        (results_df['trades'] >= MIN_TRADES_OVERALL) &
        (results_df['profit_factor'] >= MIN_PROFIT_FACTOR)
    ].copy()

    if len(filtered) == 0:
        print("⚠️  No strategies meet the criteria (profitable, 100+ trades, PF > 1.05)")
        print("   Lowering criteria to find ANY profitable strategies...")
        filtered = results_df[
            (results_df['total_pnl_pts'] > 0) &
            (results_df['trades'] >= 50)
        ].copy()

    # Get top 5 from each mode
    long_only = filtered[filtered['trade_mode'] == 'long_only'].nlargest(5, 'total_pnl_pts')
    short_only = filtered[filtered['trade_mode'] == 'short_only'].nlargest(5, 'total_pnl_pts')
    both = filtered[filtered['trade_mode'] == 'both'].nlargest(5, 'total_pnl_pts')

    # Combine
    top_strategies = pd.concat([long_only, short_only, both]).drop_duplicates(subset=['config_name', 'filter_scenario'])

    return top_strategies.head(top_n)


def main():
    print("=" * 80)
    print("YEAR-BY-YEAR STRATEGY VALIDATOR")
    print("=" * 80)
    print()

    # Load optimizer results
    print(f"📂 Loading optimizer results from {OPTIMIZER_RESULTS}...")
    results_df = pd.read_csv(OPTIMIZER_RESULTS)
    print(f"✅ Loaded {len(results_df):,} strategy results")
    print()

    # Select top strategies
    print(f"🔍 Selecting top {TOP_N_STRATEGIES} diverse strategies...")
    top_strategies = select_top_strategies(results_df, TOP_N_STRATEGIES)
    print(f"✅ Selected {len(top_strategies)} strategies:")
    for idx, row in top_strategies.iterrows():
        print(f"   {row['config_name']:50s} | {row['trade_mode']:10s} | "
              f"P&L: {row['total_pnl_pts']:+8.2f} | Trades: {row['trades']:3d} | "
              f"Filters: {row['filter_scenario']}")
    print()

    # Load all monthly data
    print(f"📂 Loading monthly data from {DATA_DIR}...")
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
    print()

    # Get unique years
    df_full['Year'] = df_full['Datetime'].dt.year
    years = sorted(df_full['Year'].unique())
    print(f"📅 Testing on years: {years}")
    print()

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Validate each strategy year-by-year
    all_yearly_results = []
    strategy_summaries = []

    print("🚀 Starting year-by-year validation...")
    print()

    for idx, (_, strategy_row) in enumerate(top_strategies.iterrows(), 1):
        config = {
            'rsi_period': int(strategy_row['rsi_period']),
            'long_threshold': int(strategy_row['long_threshold']),
            'short_threshold': int(strategy_row['short_threshold']),
            'fixed_tp_points': strategy_row['fixed_tp_points'] if pd.notna(strategy_row['fixed_tp_points']) else None,
            'rr_ratio': strategy_row['rr_ratio'] if pd.notna(strategy_row['rr_ratio']) else None,
            'tp_type': strategy_row['tp_type'],
            'sl_lookback': int(strategy_row['sl_lookback']),
            'trade_mode': strategy_row['trade_mode'],
            'skip_dax_open': strategy_row['skip_dax_open'],
            'skip_us_open': strategy_row['skip_us_open']
        }

        strategy_name = strategy_row['config_name']
        filter_scenario = strategy_row['filter_scenario']

        print(f"[{idx}/{len(top_strategies)}] Testing: {strategy_name} ({filter_scenario})")

        yearly_results = []
        cumulative_pnl = 0.0
        profitable_years = 0

        for year in years:
            # Filter data for this year
            year_data = df_full[df_full['Year'] == year].copy()

            if len(year_data) < 100:  # Skip years with too little data
                continue

            # Run backtest on this year
            result = backtest_strategy_on_year(year_data, config)

            cumulative_pnl += result['total_pnl_pts']
            if result['total_pnl_pts'] > 0:
                profitable_years += 1

            # Store result
            yearly_results.append({
                'strategy_name': strategy_name,
                'filter_scenario': filter_scenario,
                'trade_mode': strategy_row['trade_mode'],
                'year': year,
                'trades': result['trades'],
                'wins': result['wins'],
                'losses': result['losses'],
                'win_rate_pct': result['win_rate_pct'],
                'pnl_pts': result['total_pnl_pts'],
                'profit_factor': result['profit_factor'],
                'max_drawdown_pts': result['max_drawdown_pts'],
                'avg_bars_held': result['avg_bars_held'],
                'cumulative_pnl': round(cumulative_pnl, 2),
                'is_profitable_year': 1 if result['total_pnl_pts'] > 0 else 0,
                'has_min_trades': 1 if result['trades'] >= MIN_TRADES_PER_YEAR else 0
            })

            all_yearly_results.append(yearly_results[-1])

        # Calculate summary stats
        total_years = len(yearly_results)
        consistency_pct = (profitable_years / total_years * 100) if total_years > 0 else 0.0

        yearly_pnls = [r['pnl_pts'] for r in yearly_results]
        best_year_pnl = max(yearly_pnls) if yearly_pnls else 0.0
        worst_year_pnl = min(yearly_pnls) if yearly_pnls else 0.0
        avg_year_pnl = sum(yearly_pnls) / len(yearly_pnls) if yearly_pnls else 0.0

        strategy_summaries.append({
            'strategy_name': strategy_name,
            'filter_scenario': filter_scenario,
            'trade_mode': strategy_row['trade_mode'],
            'total_pnl': cumulative_pnl,
            'years_tested': total_years,
            'profitable_years': profitable_years,
            'consistency_pct': round(consistency_pct, 1),
            'best_year_pnl': round(best_year_pnl, 2),
            'worst_year_pnl': round(worst_year_pnl, 2),
            'avg_year_pnl': round(avg_year_pnl, 2)
        })

        print(f"   Total: {cumulative_pnl:+.2f} pts | Profitable years: {profitable_years}/{total_years} ({consistency_pct:.1f}%)")
        print()

    # Save detailed results
    yearly_df = pd.DataFrame(all_yearly_results)
    yearly_df.to_csv(OUTPUT_FILE, index=False)
    print(f"✅ Detailed results saved to: {OUTPUT_FILE}")
    print()

    # Save summary
    summary_df = pd.DataFrame(strategy_summaries)
    summary_df = summary_df.sort_values('total_pnl', ascending=False)

    with open(SUMMARY_FILE, 'w') as f:
        f.write("=" * 80 + "\n")
        f.write("YEAR-BY-YEAR VALIDATION SUMMARY\n")
        f.write("=" * 80 + "\n\n")

        f.write(f"Strategies tested: {len(top_strategies)}\n")
        f.write(f"Years analyzed: {len(years)} ({min(years)}-{max(years)})\n")
        f.write(f"Minimum trades per year: {MIN_TRADES_PER_YEAR}\n\n")

        f.write("=" * 80 + "\n")
        f.write("TOP STRATEGIES BY CONSISTENCY\n")
        f.write("=" * 80 + "\n\n")

        for idx, row in summary_df.head(10).iterrows():
            f.write(f"{row['strategy_name']} ({row['filter_scenario']})\n")
            f.write(f"  Mode: {row['trade_mode']}\n")
            f.write(f"  Total P&L: {row['total_pnl']:+.2f} pts\n")
            f.write(f"  Profitable Years: {row['profitable_years']}/{row['years_tested']} ({row['consistency_pct']:.1f}%)\n")
            f.write(f"  Best Year: {row['best_year_pnl']:+.2f} pts\n")
            f.write(f"  Worst Year: {row['worst_year_pnl']:+.2f} pts\n")
            f.write(f"  Avg per Year: {row['avg_year_pnl']:+.2f} pts\n")
            f.write("\n")

    print(f"✅ Summary saved to: {SUMMARY_FILE}")
    print()

    # Display top 5
    print("=" * 80)
    print("TOP 5 MOST CONSISTENT STRATEGIES")
    print("=" * 80)
    print()

    for idx, row in summary_df.head(5).iterrows():
        print(f"{idx+1}. {row['strategy_name']} ({row['filter_scenario']})")
        print(f"   Mode: {row['trade_mode']}")
        print(f"   Total P&L: {row['total_pnl']:+.2f} pts")
        print(f"   Profitable Years: {row['profitable_years']}/{row['years_tested']} ({row['consistency_pct']:.1f}%)")
        print(f"   Avg per Year: {row['avg_year_pnl']:+.2f} pts")
        print()

    print("=" * 80)
    print("NEXT STEPS:")
    print("=" * 80)
    print()
    print(f"1. Review detailed breakdown: {OUTPUT_FILE}")
    print(f"2. Read summary: {SUMMARY_FILE}")
    print("3. If consistency > 60%: Test top strategy on DEMO")
    print("4. If consistency < 60%: Consider different approach")
    print()


if __name__ == "__main__":
    main()
