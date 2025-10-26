"""
Convert FTSE tick data from SQLite to monthly CSV files with 30-minute OHLC bars.
Same structure as DAX converter.
"""
import sqlite3
import pandas as pd
from pathlib import Path

# Configuration
DB_FILES = [
    "ftse_2021.db",
    "ftse_2022.db",
    "ftse_2023.db",
    "ftse_2024.db",
    "ftse_2025.db"
]
OUTPUT_DIR = Path("data/ftse_monthly")
TIMEFRAME = "30T"  # 30 minutes
PRICE_DIVISOR = 1.0  # Adjust if FTSE prices need scaling (check first run)

def main():
    print(f"📊 Converting FTSE tick data to monthly CSV files...")

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_ticks = []

    # Load ticks from all database files
    for db_file in DB_FILES:
        db_path = Path(db_file)
        if not db_path.exists():
            print(f"⚠️ Skipping {db_file} (not found)")
            continue

        print(f"📥 Loading tick data from {db_file}...")
        conn = sqlite3.connect(db_file)

        query = """
            SELECT ts, mid as price
            FROM ticks
            WHERE symbol = 'GBRIDXGBP'
            ORDER BY ts
        """
        df = pd.read_sql_query(query, conn)
        conn.close()

        print(f"   ✓ Loaded {len(df):,} ticks from {db_file}")
        all_ticks.append(df)

    if not all_ticks:
        print("❌ No data loaded. Check database files exist.")
        return

    # Combine all ticks
    df = pd.concat(all_ticks, ignore_index=True)
    print(f"\n✅ Total ticks loaded: {len(df):,}")

    # Convert timestamp to datetime
    df['ts'] = pd.to_datetime(df['ts'], format='ISO8601', utc=True)
    df = df.set_index('ts')
    df = df.sort_index()  # Ensure chronological order

    # Resample to OHLC bars
    print(f"🔄 Converting to {TIMEFRAME} OHLC bars...")
    ohlc = df['price'].resample(TIMEFRAME).ohlc()
    ohlc = ohlc.dropna()  # Remove bars with no data

    # Rename columns to match backtest format
    ohlc.columns = ['Open', 'High', 'Low', 'Close']

    # Apply price scaling if needed
    if PRICE_DIVISOR != 1.0:
        print(f"🔧 Correcting price scaling (÷{PRICE_DIVISOR})...")
        price_columns = ['Open', 'High', 'Low', 'Close']
        for col in price_columns:
            ohlc[col] = ohlc[col] / PRICE_DIVISOR

    ohlc = ohlc.reset_index()
    ohlc = ohlc.rename(columns={'ts': 'Datetime'})

    print(f"✅ Created {len(ohlc):,} OHLC bars")
    print(f"   Date range: {ohlc['Datetime'].min()} to {ohlc['Datetime'].max()}")
    print(f"   Sample price: {ohlc['Close'].iloc[0]:.2f} (should be ~7,000-8,500 for FTSE)")

    # Split by month and save
    ohlc['YearMonth'] = ohlc['Datetime'].dt.to_period('M')
    months = ohlc['YearMonth'].unique()

    print(f"📁 Splitting into {len(months)} monthly files...")

    for month in months:
        month_data = ohlc[ohlc['YearMonth'] == month].copy()
        month_data = month_data.drop(columns=['YearMonth'])

        # Save to CSV
        filename = f"ftse_{month}.csv"
        filepath = OUTPUT_DIR / filename
        month_data.to_csv(filepath, index=False)

        print(f"  ✓ {filename}: {len(month_data)} bars")

    print(f"\n✅ Done! Files saved to {OUTPUT_DIR}/")
    print(f"📊 Total months: {len(months)}")
    print(f"📊 Total bars: {len(ohlc):,}")

if __name__ == "__main__":
    main()
