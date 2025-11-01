"""
Convert DAX tick data from SQLite to monthly CSV files with 5-minute OHLC bars.
Simple and clean implementation.
"""
import sqlite3
import pandas as pd
from pathlib import Path

# Configuration
DB_PATH = "dax_2024.db"  # 206MB database with tick data
OUTPUT_DIR = Path("data/dax_monthly")
TIMEFRAME = "5T"  # 5 minutes
PRICE_DIVISOR = 10.0  # Divide prices by 10 to fix scaling issue

def main():
    print(f"📊 Converting DAX tick data to monthly CSV files...")

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Connect to database
    conn = sqlite3.connect(DB_PATH)

    # Load all ticks
    print(f"📥 Loading tick data from {DB_PATH}...")
    query = """
        SELECT ts, mid as price
        FROM ticks
        WHERE symbol = 'DEUIDXEUR'
        ORDER BY ts
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    print(f"✅ Loaded {len(df):,} ticks")

    # Convert timestamp to datetime (handle mixed formats)
    df['ts'] = pd.to_datetime(df['ts'], format='ISO8601', utc=True)
    df = df.set_index('ts')

    # Resample to OHLC bars
    print(f"🔄 Converting to {TIMEFRAME} OHLC bars...")
    ohlc = df['price'].resample(TIMEFRAME).ohlc()
    ohlc = ohlc.dropna()  # Remove bars with no data

    # Rename columns to match backtest format
    ohlc.columns = ['Open', 'High', 'Low', 'Close']

    # Fix price scaling - divide by 10
    print(f"🔧 Correcting price scaling (÷{PRICE_DIVISOR})...")
    price_columns = ['Open', 'High', 'Low', 'Close']
    for col in price_columns:
        ohlc[col] = ohlc[col] / PRICE_DIVISOR

    ohlc = ohlc.reset_index()
    ohlc = ohlc.rename(columns={'ts': 'Datetime'})

    print(f"✅ Created {len(ohlc):,} OHLC bars")
    print(f"   Sample price: {ohlc['Close'].iloc[0]:.2f} (should be ~13,000-16,000 for DAX)")

    # Split by month and save
    ohlc['YearMonth'] = ohlc['Datetime'].dt.to_period('M')
    months = ohlc['YearMonth'].unique()

    print(f"📁 Splitting into {len(months)} monthly files...")

    for month in months:
        month_data = ohlc[ohlc['YearMonth'] == month].copy()
        month_data = month_data.drop(columns=['YearMonth'])

        # Save to CSV
        filename = f"dax_{month}.csv"
        filepath = OUTPUT_DIR / filename
        month_data.to_csv(filepath, index=False)

        print(f"  ✓ {filename}: {len(month_data)} bars")

    print(f"\n✅ Done! Files saved to {OUTPUT_DIR}/")
    print(f"📊 Total months: {len(months)}")
    print(f"📊 Total bars: {len(ohlc):,}")

if __name__ == "__main__":
    main()
