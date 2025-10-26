"""
Find Robust Configuration Across All Years

Tests multiple configurations and finds the one that is:
1. Profitable in MOST years (not just average)
2. Has consistent performance
3. Avoids curve-fitting

This is the FINAL validation before live trading.
"""
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Import the backtest function from validator
from validate_single_config import backtest_config, is_in_session

DATA_DIR = Path("data/dax_monthly")

# Test these configurations (based on previous optimization results)
CONFIGS_TO_TEST = [
    # Original recommendation
    {"name": "RSI3_L7_S95_RR5.0", "rsi_period": 3, "long_threshold": 7, "short_threshold": 95, "rr_ratio": 5.0, "sl_lookback": 2, "trade_mode": "both"},

    # Variations with different thresholds
    {"name": "RSI2_L7_S95_RR5.0", "rsi_period": 2, "long_threshold": 7, "short_threshold": 95, "rr_ratio": 5.0, "sl_lookback": 2, "trade_mode": "both"},
    {"name": "RSI2_L10_S95_RR5.0", "rsi_period": 2, "long_threshold": 10, "short_threshold": 95, "rr_ratio": 5.0, "sl_lookback": 2, "trade_mode": "both"},
    {"name": "RSI2_L15_S95_RR5.0", "rsi_period": 2, "long_threshold": 15, "short_threshold": 95, "rr_ratio": 5.0, "sl_lookback": 2, "trade_mode": "both"},

    # Lower R:R for better win rate
    {"name": "RSI2_L10_S95_RR3.0", "rsi_period": 2, "long_threshold": 10, "short_threshold": 95, "rr_ratio": 3.0, "sl_lookback": 2, "trade_mode": "both"},
    {"name": "RSI2_L15_S95_RR3.0", "rsi_period": 2, "long_threshold": 15, "short_threshold": 95, "rr_ratio": 3.0, "sl_lookback": 2, "trade_mode": "both"},

    # Different SHORT thresholds
    {"name": "RSI2_L10_S90_RR5.0", "rsi_period": 2, "long_threshold": 10, "short_threshold": 90, "rr_ratio": 5.0, "sl_lookback": 2, "trade_mode": "both"},
    {"name": "RSI2_L10_S80_RR5.0", "rsi_period": 2, "long_threshold": 10, "short_threshold": 80, "rr_ratio": 5.0, "sl_lookback": 2, "trade_mode": "both"},

    # LONG only (for comparison)
    {"name": "RSI2_L10_RR5.0_LONG", "rsi_period": 2, "long_threshold": 10, "short_threshold": 95, "rr_ratio": 5.0, "sl_lookback": 2, "trade_mode": "long_only"},
]


def main():
    print("=" * 80)
    print("🔍 FINDING ROBUST CONFIGURATION")
    print("=" * 80)
    print()
    print(f"Testing {len(CONFIGS_TO_TEST)} configurations across all years")
    print("Looking for consistent profitability (not just high average)")
    print()

    # Load data
    csv_files = sorted(DATA_DIR.glob("dax_*.csv"))
    dfs = []
    for csv_file in csv_files:
        df = pd.read_csv(csv_file)
        df["Datetime"] = pd.to_datetime(df["Datetime"], utc=True)
        dfs.append(df)

    combined_df = pd.concat(dfs, ignore_index=True)
    combined_df = combined_df.set_index("Datetime")
    combined_df = combined_df.sort_index()

    years = sorted(combined_df.index.year.unique())
    print(f"Years available: {years}")
    print()

    # Test each configuration
    results_summary = []

    for config in CONFIGS_TO_TEST:
        print(f"Testing: {config['name']}...", end=" ")

        year_results = {}
        profitable_years = 0

        for year in years:
            year_data = combined_df[combined_df.index.year == year]
            if len(year_data) < 100:
                continue

            result = backtest_config(year_data, config)
            year_results[year] = result

            if result["profitable"]:
                profitable_years += 1

        total_pnl = sum(r["total_pnl_pts"] for r in year_results.values())
        total_trades = sum(r["trades"] for r in year_results.values())
        avg_pnl_per_year = total_pnl / len(year_results)

        consistency_score = profitable_years / len(year_results) * 100

        results_summary.append({
            "config": config["name"],
            "total_pnl": total_pnl,
            "avg_annual": avg_pnl_per_year,
            "profitable_years": profitable_years,
            "total_years": len(year_results),
            "consistency_pct": consistency_score,
            "total_trades": total_trades,
            "year_results": year_results
        })

        print(f"PnL: {total_pnl:+.0f} | {profitable_years}/{len(year_results)} years profitable ({consistency_score:.0f}%)")

    print()
    print("=" * 80)
    print("📊 CONFIGURATION RANKINGS")
    print("=" * 80)
    print()

    # Sort by consistency first, then by profit
    results_summary.sort(key=lambda x: (x["consistency_pct"], x["total_pnl"]), reverse=True)

    print(f"{'Rank':<5} {'Configuration':<25} {'Total PnL':>12} {'Avg/Year':>10} {'Consistency':>12} {'Trades':>8}")
    print(f"{'-'*5} {'-'*25} {'-'*12} {'-'*10} {'-'*12} {'-'*8}")

    for i, r in enumerate(results_summary, 1):
        status = "✅" if r["consistency_pct"] >= 80 else "⚠️" if r["consistency_pct"] >= 60 else "❌"
        print(f"{i:<5} {r['config']:<25} {r['total_pnl']:+12.2f} {r['avg_annual']:+10.2f} {r['profitable_years']}/{r['total_years']} ({r['consistency_pct']:3.0f}%) {status:>2} {r['total_trades']:8d}")

    print()

    # Show best configuration details
    best = results_summary[0]

    print("=" * 80)
    print(f"🏆 MOST ROBUST CONFIGURATION: {best['config']}")
    print("=" * 80)
    print()
    print("Year-by-year breakdown:")
    print()

    for year, result in sorted(best['year_results'].items()):
        status = "✅" if result["profitable"] else "❌"
        print(f"{status} {year}: {result['total_pnl_pts']:+8.2f} pts | WR: {result['win_rate_pct']:5.1f}% | "
              f"Trades: {result['trades']:3d} | Expect: {result['expectancy']:+7.2f} pts/trade")

    print()
    print(f"Overall Performance:")
    print(f"  Total PnL: {best['total_pnl']:+,.2f} points ({len(best['year_results'])} years)")
    print(f"  Average Annual: {best['avg_annual']:+,.2f} points/year")
    print(f"  Consistency: {best['profitable_years']}/{best['total_years']} years ({best['consistency_pct']:.0f}%)")
    print(f"  Total Trades: {best['total_trades']} ({best['total_trades']/len(best['year_results']):.0f}/year)")
    print()

    if best['consistency_pct'] >= 80:
        print("✅ RECOMMENDED FOR LIVE TRADING")
        print("   This configuration is profitable in 80%+ of years tested.")
    elif best['consistency_pct'] >= 60:
        print("⚠️  PROCEED WITH CAUTION")
        print("   This configuration is only profitable in 60-80% of years.")
    else:
        print("❌ NOT RECOMMENDED")
        print("   No configuration found that is consistently profitable.")
        print("   Consider:")
        print("   1. Testing more parameter combinations")
        print("   2. Adding additional filters (ATR, MA, etc.)")
        print("   3. Using different strategy approach")

    print()
    print("=" * 80)


if __name__ == "__main__":
    main()
