"""
Validate Single Configuration Across Multiple Years

Tests ONE specific configuration on different year ranges to ensure
it's profitable across ALL periods (not just optimized for one year).

This prevents curve-fitting and validates robustness.
"""
import pandas as pd
import numpy as np
from pathlib import Path
import sys
from datetime import time
import pytz

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from strategy_core import rsi

# Configuration to test (adjust these)
TEST_CONFIG = {
    "rsi_period": 2,
    "long_threshold": 7,
    "short_threshold": 90,
    "rr_ratio": 5.0,
    "sl_lookback": 5,
    "trade_mode": "both"  # "long_only", "short_only", or "both"
}

DATA_DIR = Path("data/dax_monthly")
TIMEZONE = pytz.timezone("Europe/Berlin")
SESSION_START = time(8, 0)
SESSION_END = time(22, 0)


def is_in_session(timestamp):
    """Check if timestamp is within EU trading session."""
    if timestamp.tzinfo is None:
        local_time = TIMEZONE.localize(timestamp)
    else:
        local_time = timestamp.astimezone(TIMEZONE)
    current_time = local_time.time()
    return SESSION_START <= current_time <= SESSION_END


def compute_sl_long(df, idx, lookback):
    """Calculate stop loss for LONG position."""
    if idx < lookback:
        return None
    lows = [df.iloc[idx - i]["Low"] for i in range(1, lookback + 1)]
    sl = min(lows)
    entry = df.iloc[idx]["Close"]
    if entry <= sl:
        return None
    return sl


def compute_sl_short(df, idx, lookback):
    """Calculate stop loss for SHORT position."""
    if idx < lookback:
        return None
    highs = [df.iloc[idx - i]["High"] for i in range(1, lookback + 1)]
    sl = max(highs)
    entry = df.iloc[idx]["Close"]
    if entry >= sl:
        return None
    return sl


def backtest_config(df, config):
    """Backtest with specific configuration."""
    df = df.copy()
    close, high, low = df["Close"], df["High"], df["Low"]

    # Calculate RSI
    df["RSI"] = rsi(close, period=config["rsi_period"])

    # Detect signals
    df["long_signal"] = (df["RSI"].shift(1) <= config["long_threshold"]) & (df["RSI"] > config["long_threshold"])
    df["short_signal"] = (df["RSI"].shift(1) >= config["short_threshold"]) & (df["RSI"] < config["short_threshold"])

    trades = []
    in_trade = False
    position_type = None
    entry_price = sl = tp = entry_time = None

    start_idx = max(config["rsi_period"], config["sl_lookback"])

    for i in range(start_idx, len(df)):
        ts = df.index[i]

        if not in_trade:
            if not is_in_session(ts):
                continue

            # Check LONG signal
            if config["trade_mode"] in ["long_only", "both"] and df["long_signal"].iat[i]:
                if trades and (df.index[i] <= trades[-1]["exit_time"]):
                    continue

                sl_price = compute_sl_long(df, i, config["sl_lookback"])
                if sl_price is None:
                    continue

                entry_price = close.iat[i]
                sl = sl_price
                risk = entry_price - sl

                if risk <= 0:
                    continue

                tp = entry_price + (risk * config["rr_ratio"])
                in_trade = True
                position_type = "long"
                entry_time = ts

            # Check SHORT signal
            elif config["trade_mode"] in ["short_only", "both"] and df["short_signal"].iat[i]:
                if trades and (df.index[i] <= trades[-1]["exit_time"]):
                    continue

                sl_price = compute_sl_short(df, i, config["sl_lookback"])
                if sl_price is None:
                    continue

                entry_price = close.iat[i]
                sl = sl_price
                risk = sl - entry_price

                if risk <= 0:
                    continue

                tp = entry_price - (risk * config["rr_ratio"])
                in_trade = True
                position_type = "short"
                entry_time = ts

        else:
            # Check for exit
            bar_low, bar_high = low.iat[i], high.iat[i]

            if position_type == "long":
                sl_hit = bar_low <= sl
                tp_hit = bar_high >= tp

                if sl_hit or tp_hit:
                    exit_reason = "SL" if sl_hit else "TP"
                    exit_price = sl if sl_hit else tp
                    pnl_pts = exit_price - entry_price

                    trades.append({
                        "entry_time": entry_time,
                        "exit_time": ts,
                        "side": "LONG",
                        "pnl_pts": float(pnl_pts),
                        "reason": exit_reason
                    })
                    in_trade = False
                    position_type = None

            elif position_type == "short":
                sl_hit = bar_high >= sl
                tp_hit = bar_low <= tp

                if sl_hit or tp_hit:
                    exit_reason = "SL" if sl_hit else "TP"
                    exit_price = sl if sl_hit else tp
                    pnl_pts = entry_price - exit_price

                    trades.append({
                        "entry_time": entry_time,
                        "exit_time": ts,
                        "side": "SHORT",
                        "pnl_pts": float(pnl_pts),
                        "reason": exit_reason
                    })
                    in_trade = False
                    position_type = None

    # Calculate statistics
    if not trades:
        return {
            "trades": 0, "wins": 0, "losses": 0,
            "long_trades": 0, "short_trades": 0,
            "win_rate_pct": 0.0, "total_pnl_pts": 0.0,
            "profit_factor": 0.0, "expectancy": 0.0,
            "max_dd_pts": 0.0, "profitable": False
        }

    trades_df = pd.DataFrame(trades)
    wins = trades_df[trades_df["reason"] == "TP"]
    losses = trades_df[trades_df["reason"] == "SL"]

    total_win_pts = wins["pnl_pts"].sum() if not wins.empty else 0.0
    total_loss_pts = abs(losses["pnl_pts"].sum()) if not losses.empty else 0.0
    pf = (total_win_pts / total_loss_pts) if total_loss_pts > 0 else 999.0

    # Calculate drawdown
    trades_df["cumulative_pnl"] = trades_df["pnl_pts"].cumsum()
    trades_df["running_max"] = trades_df["cumulative_pnl"].cummax()
    trades_df["drawdown"] = trades_df["running_max"] - trades_df["cumulative_pnl"]
    max_dd = trades_df["drawdown"].max()

    total_pnl = trades_df["pnl_pts"].sum()
    long_trades = len(trades_df[trades_df["side"] == "LONG"])
    short_trades = len(trades_df[trades_df["side"] == "SHORT"])

    return {
        "trades": len(trades_df),
        "wins": len(wins),
        "losses": len(losses),
        "long_trades": long_trades,
        "short_trades": short_trades,
        "win_rate_pct": round(100 * len(wins) / len(trades_df), 1),
        "total_pnl_pts": round(total_pnl, 2),
        "profit_factor": round(pf, 2),
        "expectancy": round(trades_df["pnl_pts"].mean(), 2),
        "max_dd_pts": round(max_dd, 2),
        "profitable": total_pnl > 0
    }


def main():
    print("=" * 80)
    print("🔬 SINGLE CONFIGURATION VALIDATOR")
    print("=" * 80)
    print()
    print("Testing ONE configuration across multiple time periods")
    print("to validate robustness and avoid curve-fitting.")
    print()

    config_name = f"RSI{TEST_CONFIG['rsi_period']}_L{TEST_CONFIG['long_threshold']}_S{TEST_CONFIG['short_threshold']}_RR{TEST_CONFIG['rr_ratio']}_{TEST_CONFIG['trade_mode']}"

    print(f"Configuration: {config_name}")
    print(f"  RSI Period: {TEST_CONFIG['rsi_period']}")
    print(f"  LONG Entry: RSI crosses above {TEST_CONFIG['long_threshold']}")
    print(f"  SHORT Entry: RSI crosses below {TEST_CONFIG['short_threshold']}")
    print(f"  R:R Ratio: {TEST_CONFIG['rr_ratio']}")
    print(f"  SL Lookback: {TEST_CONFIG['sl_lookback']} bars")
    print(f"  Trade Mode: {TEST_CONFIG['trade_mode'].upper()}")
    print()

    # Load all CSV files
    csv_files = sorted(DATA_DIR.glob("dax_*.csv"))

    if not csv_files:
        print(f"❌ No CSV files found in {DATA_DIR}")
        return

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
    print(f"📅 Full Range: {combined_df.index.min().date()} to {combined_df.index.max().date()}")

    # Determine years available
    years = sorted(combined_df.index.year.unique())
    print(f"📅 Years Available: {years}")
    print()

    # Test on each year separately
    print("=" * 80)
    print("📊 YEAR-BY-YEAR RESULTS")
    print("=" * 80)
    print()

    results_by_year = {}

    for year in years:
        year_data = combined_df[combined_df.index.year == year]

        if len(year_data) < 100:  # Skip if too little data
            continue

        result = backtest_config(year_data, TEST_CONFIG)
        results_by_year[year] = result

        status = "✅" if result["profitable"] else "❌"

        print(f"{status} {year}:")
        print(f"   Total PnL: {result['total_pnl_pts']:+,.2f} points")
        print(f"   Win Rate: {result['win_rate_pct']:.1f}%")
        print(f"   Trades: {result['trades']} (L:{result['long_trades']}, S:{result['short_trades']})")
        print(f"   Expectancy: {result['expectancy']:+.2f} pts/trade")
        print(f"   Profit Factor: {result['profit_factor']:.2f}")
        print(f"   Max DD: {result['max_dd_pts']:.2f} pts")
        print()

    # Overall summary
    print("=" * 80)
    print("📈 OVERALL SUMMARY")
    print("=" * 80)
    print()

    profitable_years = sum(1 for r in results_by_year.values() if r["profitable"])
    total_years = len(results_by_year)

    total_pnl = sum(r["total_pnl_pts"] for r in results_by_year.values())
    total_trades = sum(r["trades"] for r in results_by_year.values())
    avg_expectancy = np.mean([r["expectancy"] for r in results_by_year.values()])

    print(f"Configuration: {config_name}")
    print()
    print(f"Profitable Years: {profitable_years}/{total_years} ({100*profitable_years/total_years:.0f}%)")
    print(f"Total PnL (all years): {total_pnl:+,.2f} points")
    print(f"Average Annual PnL: {total_pnl/total_years:+,.2f} points/year")
    print(f"Total Trades: {total_trades} ({total_trades/total_years:.0f}/year)")
    print(f"Average Expectancy: {avg_expectancy:+.2f} pts/trade")
    print()

    if profitable_years == total_years:
        print("✅ ROBUST STRATEGY: Profitable in ALL years tested!")
    elif profitable_years >= total_years * 0.8:
        print(f"⚠️  MOSTLY ROBUST: Profitable in {profitable_years}/{total_years} years")
    else:
        print(f"❌ NOT ROBUST: Only profitable in {profitable_years}/{total_years} years")

    print()
    print("=" * 80)


if __name__ == "__main__":
    main()
