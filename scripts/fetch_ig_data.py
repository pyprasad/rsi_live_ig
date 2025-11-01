#!/usr/bin/env python3
"""
IG Data Fetcher
Fetches historical candle data from IG Trading API and saves to CSV.
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
from dotenv import load_dotenv

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.ig_api import IGApi

# Load environment variables
load_dotenv()

# Configuration
CONFIG = {
    'epic': 'IX.D.DAX.DAILY.IP',       # DAX 40 (Germany 40)
    'timeframe': '5Min',                # Options: 1Min, 5Min, 15Min, 1Hour, 4Hour, Day
    'max_candles': 10000,               # IG allows max 10,000 candles per request
    'output_dir': 'data/fetched',
}

# Timeframe mapping for IG API
TIMEFRAME_MAP = {
    '1Min': ('MINUTE', 1),
    '5Min': ('MINUTE', 5),
    '15Min': ('MINUTE', 15),
    '30Min': ('MINUTE', 30),
    '1Hour': ('HOUR', 1),
    '4Hour': ('HOUR', 4),
    'Day': ('DAY', 1),
}


def fetch_historical_data(ig_api, epic, timeframe, max_candles):
    """
    Fetch historical candle data from IG.

    Args:
        ig_api: IGApi instance
        epic: Epic identifier (e.g., 'IX.D.DAX.DAILY.IP')
        timeframe: Timeframe string (e.g., '5Min', '1Hour')
        max_candles: Maximum number of candles to fetch

    Returns:
        pandas.DataFrame with OHLC data
    """
    if timeframe not in TIMEFRAME_MAP:
        raise ValueError(f"Invalid timeframe: {timeframe}. Options: {list(TIMEFRAME_MAP.keys())}")

    resolution, interval = TIMEFRAME_MAP[timeframe]

    print(f"📊 Fetching {max_candles} candles for {epic} ({timeframe})...")

    try:
        # Fetch prices from IG
        # IG API endpoint: GET /prices/{epic}/{resolution}/{numPoints}
        url = f"/prices/{epic}"
        params = {
            'resolution': resolution,
            'max': max_candles,
            'pageSize': 0  # Return all results in one page
        }

        # Add interval if not 1
        if interval > 1:
            params['resolution'] = f"{resolution}_{interval}"

        response = ig_api.rest_client.fetch_by_url(url, params=params, version='3')

        if 'prices' not in response:
            print(f"❌ No price data returned from IG API")
            return None

        prices = response['prices']

        if not prices:
            print(f"❌ Empty price data received")
            return None

        # Convert to DataFrame
        data = []
        for candle in prices:
            # IG returns data in reverse chronological order (newest first)
            data.append({
                'Datetime': candle['snapshotTime'],
                'Open': candle['openPrice']['bid'],
                'High': candle['highPrice']['bid'],
                'Low': candle['lowPrice']['bid'],
                'Close': candle['closePrice']['bid'],
                'Volume': candle.get('lastTradedVolume', 0)
            })

        df = pd.DataFrame(data)

        # Reverse to chronological order (oldest first)
        df = df.iloc[::-1].reset_index(drop=True)

        # Parse datetime
        df['Datetime'] = pd.to_datetime(df['Datetime'])

        # Sort by datetime
        df = df.sort_values('Datetime').reset_index(drop=True)

        print(f"✅ Fetched {len(df)} candles")
        print(f"   Date range: {df['Datetime'].min()} to {df['Datetime'].max()}")

        return df

    except Exception as e:
        print(f"❌ Error fetching data: {e}")
        return None


def save_to_csv(df, epic, timeframe, output_dir):
    """
    Save DataFrame to CSV with naming convention: epic_timeframe.csv

    Args:
        df: pandas.DataFrame with OHLC data
        epic: Epic identifier
        timeframe: Timeframe string
        output_dir: Output directory path

    Returns:
        Path to saved CSV file
    """
    # Create output directory if it doesn't exist
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Clean epic name for filename (replace dots with underscores)
    epic_clean = epic.replace('.', '_')

    # Create filename: epic_timeframe.csv
    filename = f"{epic_clean}_{timeframe}.csv"
    filepath = output_path / filename

    # Save to CSV
    df.to_csv(filepath, index=False)

    print(f"💾 Saved to: {filepath}")
    print(f"   Rows: {len(df)}")
    print(f"   Columns: {', '.join(df.columns)}")

    return filepath


def main():
    """Main execution function."""
    print("=" * 80)
    print("IG DATA FETCHER")
    print("=" * 80)
    print()

    # Check for command-line arguments
    if len(sys.argv) > 1:
        CONFIG['epic'] = sys.argv[1]
    if len(sys.argv) > 2:
        CONFIG['timeframe'] = sys.argv[2]
    if len(sys.argv) > 3:
        CONFIG['max_candles'] = int(sys.argv[3])

    print("Configuration:")
    print(f"  Epic: {CONFIG['epic']}")
    print(f"  Timeframe: {CONFIG['timeframe']}")
    print(f"  Max Candles: {CONFIG['max_candles']}")
    print(f"  Output Directory: {CONFIG['output_dir']}")
    print()

    # Initialize IG API
    print("🔐 Connecting to IG API...")
    ig_api = IGApi()

    if not ig_api.connect():
        print("❌ Failed to connect to IG API")
        sys.exit(1)

    print("✅ Connected to IG API")
    print()

    # Fetch data
    df = fetch_historical_data(
        ig_api,
        CONFIG['epic'],
        CONFIG['timeframe'],
        CONFIG['max_candles']
    )

    if df is None or len(df) == 0:
        print("❌ No data fetched")
        sys.exit(1)

    print()

    # Save to CSV
    filepath = save_to_csv(
        df,
        CONFIG['epic'],
        CONFIG['timeframe'],
        CONFIG['output_dir']
    )

    print()
    print("=" * 80)
    print("✅ FETCH COMPLETE")
    print("=" * 80)
    print()
    print(f"Data saved to: {filepath}")
    print(f"Total candles: {len(df)}")
    print()


if __name__ == "__main__":
    main()
