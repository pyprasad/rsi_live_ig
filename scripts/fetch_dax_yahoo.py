"""
Fetch DAX data from Yahoo Finance for the last 2 years (30-minute candles).
This provides out-of-sample data to validate the strategy.
"""
import yfinance as yf
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

# Configuration
OUTPUT_DIR = Path("data/dax_yahoo")
TICKER = "^GDAXI"  # DAX index symbol on Yahoo Finance
INTERVAL = "1h"    # 1-hour candles (Yahoo limit: 730 days max)
PERIOD = "730d"    # Last 730 days (~2 years from today)

def main():
    print("=" * 80)
    print("📊 Fetching DAX Data from Yahoo Finance")
    print("=" * 80)
    print()
    print(f"📈 Ticker: {TICKER} (DAX Index)")
    print(f"⏰ Interval: {INTERVAL} (1 hour)")
    print(f"📅 Period: {PERIOD} (Last ~2 years from today)")
    print()

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Fetch data from Yahoo Finance
    print("📥 Downloading data from Yahoo Finance...")
    try:
        dax = yf.Ticker(TICKER)
        df = dax.history(period=PERIOD, interval=INTERVAL)
    except Exception as e:
        print(f"❌ Error fetching data: {e}")
        print("\nTip: Make sure you have installed yfinance:")
        print("  pip install yfinance")
        return

    if df.empty:
        print("❌ No data received from Yahoo Finance")
        return

    print(f"✅ Downloaded {len(df):,} candles")
    print(f"📅 Date Range: {df.index.min()} to {df.index.max()}")
    print()

    # Clean and format data
    print("🔄 Processing data...")

    # Reset index to get Datetime as a column
    df = df.reset_index()

    # Rename columns to match backtest format
    df = df.rename(columns={
        'Datetime': 'Datetime',
        'Open': 'Open',
        'High': 'High',
        'Low': 'Low',
        'Close': 'Close',
        'Volume': 'Volume'
    })

    # Keep only OHLC columns
    df = df[['Datetime', 'Open', 'High', 'Low', 'Close', 'Volume']]

    # Remove any NaN rows
    df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])

    print(f"✅ Processed {len(df):,} valid candles")
    print()

    # Save full dataset
    full_file = OUTPUT_DIR / "dax_yahoo_730d_1h.csv"
    df.to_csv(full_file, index=False)
    print(f"💾 Full dataset saved: {full_file}")

    # Split by month for monthly analysis
    print()
    print("📁 Splitting into monthly files...")

    df['Datetime'] = pd.to_datetime(df['Datetime'])
    df['YearMonth'] = df['Datetime'].dt.to_period('M')

    months = df['YearMonth'].unique()
    monthly_files = []

    for month in sorted(months):
        month_data = df[df['YearMonth'] == month].copy()
        month_data = month_data.drop(columns=['YearMonth'])

        # Save monthly file
        filename = f"dax_yahoo_{month}.csv"
        filepath = OUTPUT_DIR / filename
        month_data.to_csv(filepath, index=False)

        monthly_files.append(filename)
        print(f"  ✓ {filename}: {len(month_data)} candles")

    print()
    print("=" * 80)
    print("✅ DOWNLOAD COMPLETE")
    print("=" * 80)
    print(f"📊 Total Candles: {len(df):,}")
    print(f"📁 Monthly Files: {len(monthly_files)}")
    print(f"📅 Date Range: {df['Datetime'].min()} to {df['Datetime'].max()}")
    print(f"💾 Output Directory: {OUTPUT_DIR}/")
    print()
    print("🚀 Next Steps:")
    print("1. Run optimization on Yahoo data:")
    print("   - Edit scripts/optimize_dax_strategy.py")
    print("   - Change DATA_DIR to 'data/dax_yahoo'")
    print("   - Run: python scripts/optimize_dax_strategy.py")
    print()
    print("2. Compare results:")
    print("   - 2023 DB data (in-sample)")
    print("   - 2024 Yahoo data (out-of-sample)")
    print("   - If both profitable → strategy is robust!")
    print()

if __name__ == "__main__":
    main()
