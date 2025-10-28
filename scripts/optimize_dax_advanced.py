"""
DAX Advanced Optimizer - Fixed Take Profit + Session Filters

Key Differences from Previous Optimizer:
1. FIXED TP points [5, 10, 15, 20, 25] instead of R:R ratios
2. Optional session filters: skip DAX open (08:00-08:30)
3. Optional session filters: skip US open (15:30-16:00 CET with DST)
4. Tests WITH and WITHOUT filters (2 scenarios per combo)
5. Progressive CSV saving (append immediately, not batch)

Total Combinations: 4,500 × 2 = 9,000 tests
"""
import pandas as pd
import numpy as np
import yaml
from pathlib import Path
from datetime import datetime, time, timedelta
import pytz
from itertools import product
import sys
from multiprocessing import Pool, cpu_count
import os

# Parameter Grid (from config, but defined here for speed)
RSI_PERIODS = [2, 3, 4]
LONG_THRESHOLDS = [5, 7, 10, 12, 15]
SHORT_THRESHOLDS = [70, 80, 85, 90, 95]

# Take Profit: Test BOTH fixed points AND R:R ratios
FIXED_TP_POINTS = [5, 10, 15, 20, 25]  # Fixed TP in points
RR_RATIOS = [2.0, 3.0, 5.0]             # Risk:Reward ratios

SL_LOOKBACK_PERIODS = [2, 3, 4, 5]
TRADE_MODES = ["long_only", "short_only", "both"]

# Session Filter Scenarios
FILTER_SCENARIOS = [
    {"skip_dax_open": False, "skip_us_open": False, "scenario_name": "no_filters"},
    {"skip_dax_open": True, "skip_us_open": True, "scenario_name": "with_filters"}
]

# Session Settings
DAX_OPEN_START = time(8, 0)
DAX_OPEN_END = time(8, 30)
US_OPEN_DURATION_MINS = 30
BASE_SESSION_START = time(8, 0)
BASE_SESSION_END = time(22, 0)
TIMEZONE = pytz.timezone("Europe/Berlin")

# Paths
DATA_DIR = Path("data/dax_monthly")
RESULTS_DIR = Path("results/dax_advanced")
RESULTS_FILE = RESULTS_DIR / "dax_advanced_results.csv"


def get_us_open_cet_time(dt_berlin):
    """
    Get US market open time in CET/CEST, handling DST transitions.

    US market opens at 09:30 ET (Eastern Time)
    This is 15:30 CET (winter) or 14:30 CEST (summer)

    But both US and Europe have different DST dates, so we need to convert properly.
    """
    # Convert Berlin time to UTC, then to US/Eastern
    dt_utc = dt_berlin.astimezone(pytz.utc)
    dt_eastern = dt_utc.astimezone(pytz.timezone("US/Eastern"))

    # US market open at 09:30 ET
    us_open_et = dt_eastern.replace(hour=9, minute=30, second=0, microsecond=0)

    # Convert back to Berlin time
    us_open_berlin = us_open_et.astimezone(TIMEZONE)

    return us_open_berlin.time()


def is_us_open_period(dt_berlin, duration_mins=30):
    """
    Check if timestamp falls within US market open period.

    Args:
        dt_berlin: datetime in Europe/Berlin timezone
        duration_mins: how many minutes to skip (default 30)

    Returns:
        True if within US open period, False otherwise
    """
    us_open_time = get_us_open_cet_time(dt_berlin)

    # Create datetime objects for comparison
    us_open_start = dt_berlin.replace(
        hour=us_open_time.hour,
        minute=us_open_time.minute,
        second=0,
        microsecond=0
    )
    us_open_end = us_open_start + timedelta(minutes=duration_mins)

    return us_open_start <= dt_berlin < us_open_end


def should_skip_trade(dt_berlin, skip_dax_open=False, skip_us_open=False):
    """
    Determine if trade should be skipped based on session filters.

    Args:
        dt_berlin: datetime in Europe/Berlin timezone
        skip_dax_open: if True, skip 08:00-08:30
        skip_us_open: if True, skip US market open (15:30-16:00 CET with DST)

    Returns:
        True if trade should be skipped, False otherwise
    """
    trade_time = dt_berlin.time()

    # Filter 1: Skip DAX market open
    if skip_dax_open:
        if DAX_OPEN_START <= trade_time < DAX_OPEN_END:
            return True

    # Filter 2: Skip US market open
    if skip_us_open:
        if is_us_open_period(dt_berlin, duration_mins=US_OPEN_DURATION_MINS):
            return True

    return False


def calculate_rsi(prices, period=14):
    """Calculate RSI indicator."""
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def backtest_strategy(
    df,
    rsi_period,
    long_threshold,
    short_threshold,
    sl_lookback,
    trade_mode,
    fixed_tp_points=None,
    rr_ratio=None,
    skip_dax_open=False,
    skip_us_open=False
):
    """
    Backtest strategy with EITHER fixed TP points OR R:R ratio.

    Args:
        fixed_tp_points: Fixed TP in points (e.g., 10 points) - use this OR rr_ratio
        rr_ratio: Risk:Reward ratio (e.g., 3.0) - use this OR fixed_tp_points
        Other args same as before

    Returns:
        dict with performance metrics
    """
    # Validate: must provide exactly one TP method
    if (fixed_tp_points is None and rr_ratio is None) or \
       (fixed_tp_points is not None and rr_ratio is not None):
        raise ValueError("Must provide either fixed_tp_points OR rr_ratio, not both or neither")
    df = df.copy()
    df['RSI'] = calculate_rsi(df['Close'], period=rsi_period)

    # Generate signals
    df['prev_RSI'] = df['RSI'].shift(1)

    # LONG: RSI crosses above threshold
    df['long_signal'] = (df['prev_RSI'] <= long_threshold) & (df['RSI'] > long_threshold)

    # SHORT: RSI crosses below threshold
    df['short_signal'] = (df['prev_RSI'] >= short_threshold) & (df['RSI'] < short_threshold)

    # Apply trade mode filter
    if trade_mode == "long_only":
        df['short_signal'] = False
    elif trade_mode == "short_only":
        df['long_signal'] = False

    # Track trades
    trades = []
    in_position = False
    position_type = None
    entry_price = None
    entry_idx = None
    stop_loss = None
    take_profit = None

    for i in range(sl_lookback, len(df)):
        row = df.iloc[i]
        dt_berlin = row['Datetime']

        # Skip if in filtered session periods
        if should_skip_trade(dt_berlin, skip_dax_open, skip_us_open):
            continue

        # Skip if outside base session hours (08:00-22:00)
        trade_time = dt_berlin.time()
        if not (BASE_SESSION_START <= trade_time < BASE_SESSION_END):
            continue

        # Check if in position
        if in_position:
            # Check exit conditions
            hit_tp = False
            hit_sl = False

            if position_type == "LONG":
                hit_tp = row['High'] >= take_profit
                hit_sl = row['Low'] <= stop_loss
            else:  # SHORT
                hit_tp = row['Low'] <= take_profit
                hit_sl = row['High'] >= stop_loss

            # Exit logic
            exit_price = None
            exit_reason = None

            if hit_sl and hit_tp:
                # Both hit - which came first? Assume SL hit first (conservative)
                exit_price = stop_loss
                exit_reason = "SL"
            elif hit_sl:
                exit_price = stop_loss
                exit_reason = "SL"
            elif hit_tp:
                exit_price = take_profit
                exit_reason = "TP"

            if exit_price:
                # Record trade
                if position_type == "LONG":
                    pnl_pts = exit_price - entry_price
                else:  # SHORT
                    pnl_pts = entry_price - exit_price

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
                    "bars_held": i - entry_idx
                })

                # Reset position
                in_position = False
                position_type = None

        # Check for new entry signals (only if not in position)
        if not in_position:
            if row['long_signal']:
                # Enter LONG
                entry_price = row['Close']
                entry_idx = i
                position_type = "LONG"

                # Calculate SL: lowest low of last N bars
                lookback_slice = df.iloc[i - sl_lookback:i]
                stop_loss = lookback_slice['Low'].min()

                # Calculate TP: Either FIXED points OR R:R ratio
                if fixed_tp_points is not None:
                    # Fixed TP in points
                    take_profit = entry_price + fixed_tp_points
                else:
                    # R:R ratio based TP
                    risk = entry_price - stop_loss
                    if risk <= 0:
                        continue  # Skip trade if SL is invalid
                    take_profit = entry_price + (risk * rr_ratio)

                in_position = True

            elif row['short_signal']:
                # Enter SHORT
                entry_price = row['Close']
                entry_idx = i
                position_type = "SHORT"

                # Calculate SL: highest high of last N bars
                lookback_slice = df.iloc[i - sl_lookback:i]
                stop_loss = lookback_slice['High'].max()

                # Calculate TP: Either FIXED points OR R:R ratio
                if fixed_tp_points is not None:
                    # Fixed TP in points
                    take_profit = entry_price - fixed_tp_points
                else:
                    # R:R ratio based TP
                    risk = stop_loss - entry_price
                    if risk <= 0:
                        continue  # Skip trade if SL is invalid
                    take_profit = entry_price - (risk * rr_ratio)

                in_position = True

    # Convert trades to DataFrame
    # Generate config name based on TP type
    if fixed_tp_points is not None:
        tp_str = f"TP{fixed_tp_points}"
        tp_type = "fixed"
    else:
        tp_str = f"RR{rr_ratio}"
        tp_type = "ratio"

    config_name = f"RSI{rsi_period}_L{long_threshold}_S{short_threshold}_{tp_str}_SL{sl_lookback}_{trade_mode}"

    if not trades:
        return {
            "config_name": config_name,
            "rsi_period": rsi_period,
            "long_threshold": long_threshold,
            "short_threshold": short_threshold,
            "fixed_tp_points": fixed_tp_points if fixed_tp_points is not None else "",
            "rr_ratio": rr_ratio if rr_ratio is not None else "",
            "tp_type": tp_type,
            "sl_lookback": sl_lookback,
            "trade_mode": trade_mode,
            "skip_dax_open": skip_dax_open,
            "skip_us_open": skip_us_open,
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "total_pnl_pts": 0.0,
            "avg_win_pts": 0.0,
            "avg_loss_pts": 0.0,
            "expectancy_pts": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_pts": 0.0,
            "long_trades": 0,
            "short_trades": 0,
            "long_win_rate_pct": 0.0,
            "short_win_rate_pct": 0.0,
            "avg_bars_held": 0.0,
            "total_win_pts": 0.0,
            "total_loss_pts": 0.0,
            "is_profitable": 0,
            "pf_above_1.1": 0,
            "pf_above_1.2": 0,
            "wr_above_15": 0,
            "wr_above_20": 0,
            "year_start": 0,
            "year_end": 0,
            "month_start": 0,
            "month_end": 0
        }

    trades_df = pd.DataFrame(trades)

    # Calculate metrics
    wins = trades_df[trades_df['pnl_pts'] > 0]
    losses = trades_df[trades_df['pnl_pts'] <= 0]

    total_pnl = trades_df['pnl_pts'].sum()
    win_rate = len(wins) / len(trades_df) * 100 if len(trades_df) > 0 else 0.0

    avg_win = wins['pnl_pts'].mean() if len(wins) > 0 else 0.0
    avg_loss = losses['pnl_pts'].mean() if len(losses) > 0 else 0.0

    expectancy = trades_df['pnl_pts'].mean()

    total_win_pts = wins['pnl_pts'].sum() if len(wins) > 0 else 0.0
    total_loss_pts = abs(losses['pnl_pts'].sum()) if len(losses) > 0 else 0.0

    profit_factor = total_win_pts / total_loss_pts if total_loss_pts > 0 else 0.0

    # Max drawdown
    cumulative = trades_df['pnl_pts'].cumsum()
    running_max = cumulative.cummax()
    drawdown = running_max - cumulative
    max_drawdown = drawdown.max()

    # Trade type breakdown
    long_trades = trades_df[trades_df['type'] == 'LONG']
    short_trades = trades_df[trades_df['type'] == 'SHORT']

    long_wins = long_trades[long_trades['pnl_pts'] > 0]
    short_wins = short_trades[short_trades['pnl_pts'] > 0]

    long_win_rate = len(long_wins) / len(long_trades) * 100 if len(long_trades) > 0 else 0.0
    short_win_rate = len(short_wins) / len(short_trades) * 100 if len(short_trades) > 0 else 0.0

    avg_bars_held = trades_df['bars_held'].mean()

    # Date range for validation
    first_trade = trades_df['entry_time'].min()
    last_trade = trades_df['exit_time'].max()
    year_start = first_trade.year
    year_end = last_trade.year
    month_start = first_trade.month
    month_end = last_trade.month

    return {
        "config_name": config_name,
        "rsi_period": rsi_period,
        "long_threshold": long_threshold,
        "short_threshold": short_threshold,
        "fixed_tp_points": fixed_tp_points if fixed_tp_points is not None else "",
        "rr_ratio": rr_ratio if rr_ratio is not None else "",
        "tp_type": tp_type,
        "sl_lookback": sl_lookback,
        "trade_mode": trade_mode,
        "skip_dax_open": skip_dax_open,
        "skip_us_open": skip_us_open,
        "trades": len(trades_df),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(win_rate, 2),
        "total_pnl_pts": round(total_pnl, 2),
        "avg_win_pts": round(avg_win, 2),
        "avg_loss_pts": round(avg_loss, 2),
        "expectancy_pts": round(expectancy, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown_pts": round(max_drawdown, 2),
        "long_trades": len(long_trades),
        "short_trades": len(short_trades),
        "long_win_rate_pct": round(long_win_rate, 1),
        "short_win_rate_pct": round(short_win_rate, 1),
        "avg_bars_held": round(avg_bars_held, 1),
        "total_win_pts": round(total_win_pts, 2),
        "total_loss_pts": round(total_loss_pts, 2),
        "is_profitable": 1 if total_pnl > 0 else 0,
        "pf_above_1.1": 1 if profit_factor > 1.1 else 0,
        "pf_above_1.2": 1 if profit_factor > 1.2 else 0,
        "wr_above_15": 1 if win_rate > 15 else 0,
        "wr_above_20": 1 if win_rate > 20 else 0,
        "year_start": year_start,
        "year_end": year_end,
        "month_start": month_start,
        "month_end": month_end
    }


def append_result_to_csv(result, output_file):
    """
    Append single result to CSV immediately (progressive saving).

    Creates file with header if it doesn't exist.
    """
    # Convert result dict to DataFrame row
    result_df = pd.DataFrame([result])

    # Check if file exists
    if output_file.exists():
        # Append without header
        result_df.to_csv(output_file, mode='a', header=False, index=False)
    else:
        # Create new file with header
        result_df.to_csv(output_file, mode='w', header=True, index=False)


# Global variable for worker processes to access
_df_full_global = None

def worker_init(df_full):
    """Initialize worker with the data (called once per worker)."""
    global _df_full_global
    _df_full_global = df_full


def process_combo(args):
    """
    Process a single combination.

    This function is called by each worker process.
    Returns the result dict directly (no CSV writing in worker).
    """
    combo_idx, combo_data, total_combos = args

    # Unpack combo based on type (fixed_tp or rr)
    combo_type = combo_data['type']
    filter_scenario = combo_data['filter_scenario']

    if combo_type == 'fixed_tp':
        rsi_period, long_thresh, short_thresh, tp_pts, sl_lookback, trade_mode = combo_data['params']

        result = backtest_strategy(
            _df_full_global,
            rsi_period=rsi_period,
            long_threshold=long_thresh,
            short_threshold=short_thresh,
            sl_lookback=sl_lookback,
            trade_mode=trade_mode,
            fixed_tp_points=tp_pts,
            skip_dax_open=filter_scenario['skip_dax_open'],
            skip_us_open=filter_scenario['skip_us_open']
        )
    else:  # rr type
        rsi_period, long_thresh, short_thresh, rr, sl_lookback, trade_mode = combo_data['params']

        result = backtest_strategy(
            _df_full_global,
            rsi_period=rsi_period,
            long_threshold=long_thresh,
            short_threshold=short_thresh,
            sl_lookback=sl_lookback,
            trade_mode=trade_mode,
            rr_ratio=rr,
            skip_dax_open=filter_scenario['skip_dax_open'],
            skip_us_open=filter_scenario['skip_us_open']
        )

    result['filter_scenario'] = filter_scenario['scenario_name']
    result['_combo_idx'] = combo_idx  # For progress tracking

    return result


def main():
    print("=" * 80)
    print("DAX ADVANCED OPTIMIZER - Fixed TP + Session Filters")
    print("=" * 80)
    print()

    # Load all monthly data files
    print(f"📂 Loading data from {DATA_DIR}...")
    csv_files = sorted(DATA_DIR.glob("*.csv"))

    if not csv_files:
        print(f"❌ No CSV files found in {DATA_DIR}")
        print("   Run: python scripts/convert_dax_to_csv.py first")
        return

    all_data = []
    for csv_file in csv_files:
        df = pd.read_csv(csv_file)
        df['Datetime'] = pd.to_datetime(df['Datetime'])
        # Ensure timezone-aware
        if df['Datetime'].dt.tz is None:
            df['Datetime'] = df['Datetime'].dt.tz_localize('UTC').dt.tz_convert(TIMEZONE)
        else:
            df['Datetime'] = df['Datetime'].dt.tz_convert(TIMEZONE)
        all_data.append(df)

    df_full = pd.concat(all_data, ignore_index=True)
    df_full = df_full.sort_values('Datetime').reset_index(drop=True)

    print(f"✅ Loaded {len(df_full):,} bars from {len(csv_files)} files")
    print(f"   Date range: {df_full['Datetime'].min()} to {df_full['Datetime'].max()}")
    print()

    # Create output directory
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Calculate total combinations (BOTH fixed TP AND R:R ratios)
    base_combos = (
        len(RSI_PERIODS) *
        len(LONG_THRESHOLDS) *
        len(SHORT_THRESHOLDS) *
        (len(FIXED_TP_POINTS) + len(RR_RATIOS)) *  # BOTH TP types!
        len(SL_LOOKBACK_PERIODS) *
        len(TRADE_MODES)
    )
    total_combos = base_combos * len(FILTER_SCENARIOS)

    print(f"🔧 Parameter Grid:")
    print(f"   RSI Periods: {RSI_PERIODS}")
    print(f"   LONG Thresholds: {LONG_THRESHOLDS}")
    print(f"   SHORT Thresholds: {SHORT_THRESHOLDS}")
    print(f"   Fixed TP Points: {FIXED_TP_POINTS}")
    print(f"   R:R Ratios: {RR_RATIOS}")
    print(f"   SL Lookback: {SL_LOOKBACK_PERIODS}")
    print(f"   Trade Modes: {TRADE_MODES}")
    print(f"   Filter Scenarios: {[s['scenario_name'] for s in FILTER_SCENARIOS]}")
    print()
    print(f"📊 Total Combinations: {base_combos:,} (fixed TP + R:R) × {len(FILTER_SCENARIOS)} = {total_combos:,}")
    print()

    # Delete existing results file if it exists (fresh start)
    if RESULTS_FILE.exists():
        print(f"🗑️  Deleting existing results file: {RESULTS_FILE}")
        RESULTS_FILE.unlink()

    print(f"💾 Results will be saved to: {RESULTS_FILE}")
    print(f"   Save mode: PROGRESSIVE (append after each combo)")
    print()
    print("🚀 Starting optimization...")
    print()

    # Generate all combinations - test BOTH fixed TP AND R:R ratios
    # Package combos with metadata for workers
    all_combos = []
    combo_idx = 0

    # Fixed TP combinations
    for combo in product(RSI_PERIODS, LONG_THRESHOLDS, SHORT_THRESHOLDS,
                         FIXED_TP_POINTS, SL_LOOKBACK_PERIODS, TRADE_MODES, FILTER_SCENARIOS):
        *params, filter_scenario = combo
        combo_idx += 1
        all_combos.append((combo_idx, {
            'type': 'fixed_tp',
            'params': params,
            'filter_scenario': filter_scenario
        }, total_combos))

    # R:R ratio combinations
    for combo in product(RSI_PERIODS, LONG_THRESHOLDS, SHORT_THRESHOLDS,
                         RR_RATIOS, SL_LOOKBACK_PERIODS, TRADE_MODES, FILTER_SCENARIOS):
        *params, filter_scenario = combo
        combo_idx += 1
        all_combos.append((combo_idx, {
            'type': 'rr',
            'params': params,
            'filter_scenario': filter_scenario
        }, total_combos))

    # Determine number of worker processes
    n_workers = max(1, cpu_count() - 1)  # Leave 1 core free
    print(f"🔧 Using {n_workers} worker processes (out of {cpu_count()} CPU cores)")
    print()

    start_time = datetime.now()

    # Run multiprocessing
    print(f"🚀 Processing {total_combos:,} combinations in parallel...")
    print()

    with Pool(processes=n_workers, initializer=worker_init, initargs=(df_full,)) as pool:
        # Process combos and save results as they complete
        results_processed = 0

        for result in pool.imap_unordered(process_combo, all_combos, chunksize=10):
            # Save result to CSV
            append_result_to_csv(result, RESULTS_FILE)

            results_processed += 1

            # Progress update every 100 results
            if results_processed % 100 == 0 or results_processed == total_combos:
                elapsed = (datetime.now() - start_time).total_seconds()
                avg_time_per_combo = elapsed / results_processed
                remaining = (total_combos - results_processed) * avg_time_per_combo

                print(f"[{results_processed:,}/{total_combos:,}] {result['config_name']}")
                print(f"            P&L: {result['total_pnl_pts']:+.2f} pts | Trades: {result['trades']} | "
                      f"WR: {result['win_rate_pct']:.1f}% | PF: {result['profit_factor']:.2f}")
                print(f"            Progress: {results_processed/total_combos*100:.1f}% | ETA: {remaining/60:.1f} mins")
                print()

    total_time = (datetime.now() - start_time).total_seconds()

    print()
    print("=" * 80)
    print("✅ OPTIMIZATION COMPLETE")
    print("=" * 80)
    print(f"⏱️  Total time: {total_time/60:.1f} minutes ({total_time:.1f} seconds)")
    print(f"📊 Total combinations tested: {total_combos:,}")
    print(f"💾 Results saved to: {RESULTS_FILE}")
    print()
    print("📈 Next Steps:")
    print("   1. Analyze results:")
    print(f"      head -1 {RESULTS_FILE}")
    print(f"      sort -t',' -k10 -rn {RESULTS_FILE} | head -20")
    print()
    print("   2. Filter by criteria:")
    print("      # Profitable configs with PF > 1.1")
    print(f"      awk -F',' '$24==1 && $25==1' {RESULTS_FILE} | sort -t',' -k10 -rn")
    print()
    print("   3. Compare filter scenarios:")
    print("      # WITH filters")
    print(f"      grep 'with_filters' {RESULTS_FILE} | sort -t',' -k10 -rn | head -10")
    print("      # WITHOUT filters")
    print(f"      grep 'no_filters' {RESULTS_FILE} | sort -t',' -k10 -rn | head -10")
    print()


if __name__ == "__main__":
    main()
